from datetime import date, timedelta

from fastapi import APIRouter, Depends, File, Form, Header, UploadFile
from pydantic import BaseModel
from sqlmodel import Session, func, select

from . import ai, rag
from .auth import current_user
from .config import settings
from .db import get_session
from .messages import fail, pick_lang
from .models import AuditLog, LegalChunk, LegalDocument, User, utcnow
from .ops import require_admin
from .redact import redact

router = APIRouter(prefix="/api", tags=["legal-rag"])


# ---------------- admin: verified PDF daalna ----------------
@router.post("/admin/legal-docs", status_code=201)
def upload_doc(file: UploadFile = File(...), title: str = Form(...), source_url: str = Form(...), verified_on: str = Form(...),
               jurisdiction: str = Form("Pakistan"), attested: bool = Form(False),
               admin: User = Depends(require_admin), db: Session = Depends(get_session), x_lang: str | None = Header(default=None)):
    lang = x_lang or admin.language
    try:
        date.fromisoformat(verified_on)
        ok_date = True
    except ValueError:
        ok_date = False
    if not (3 <= len(title.strip()) <= 200 and source_url.startswith("https://") and ok_date and jurisdiction.strip()):
        raise fail(422, "legal_source_invalid", lang)
    if not attested:  # insaan tasdeeq kare ke yeh official source se verify hua
        raise fail(422, "legal_attest_required", lang)
    limit = settings.rag_max_pdf_mb * 1024 * 1024
    data = file.file.read(limit + 1)
    if len(data) > limit or not data.startswith(b"%PDF-"):
        raise fail(422, "pdf_invalid", lang)
    try:
        report = rag.ingest_pdf(db, data, title.strip(), source_url.strip(), verified_on, jurisdiction.strip(), admin.id)
    except rag.RagError as e:
        code = e.args[0]
        raise fail(409 if code == "doc_duplicate" else 503 if code == "rag_unavailable" else 422, code, lang) from None
    db.add(AuditLog(actor_id=admin.id, action="legal_doc_added", detail=str(report["id"])))
    db.commit()
    return report


@router.get("/admin/legal-docs")
def list_docs(_: User = Depends(require_admin), db: Session = Depends(get_session)):
    out = []
    for d in db.exec(select(LegalDocument).order_by(LegalDocument.id)).all():
        n = db.exec(select(func.count()).select_from(LegalChunk).where(LegalChunk.document_id == d.id)).one()
        out.append({"id": d.id, "title": d.title, "source_url": d.source_url, "jurisdiction": d.jurisdiction, "verified_on": d.verified_on,
                    "pages": d.pages, "ocr_pages": d.ocr_pages, "chunks": n, "status": d.status})
    return {"documents": out}


@router.delete("/admin/legal-docs/{doc_id}")
def delete_doc(doc_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_session), x_lang: str | None = Header(default=None)):
    d = db.get(LegalDocument, doc_id)
    if not d:
        raise fail(404, "not_found", x_lang or admin.language)
    for c in db.exec(select(LegalChunk).where(LegalChunk.document_id == doc_id)).all():
        db.delete(c)
    db.delete(d)
    db.add(AuditLog(actor_id=admin.id, action="legal_doc_deleted", detail=str(doc_id)))
    db.commit()
    return {"deleted": True}


@router.post("/admin/legal-docs/reindex")
def reindex(admin: User = Depends(require_admin), db: Session = Depends(get_session), x_lang: str | None = Header(default=None)):
    try:
        return {"reindexed": rag.reindex(db), "embedder": rag.embedder_name()}
    except rag.RagError:
        raise fail(503, "rag_unavailable", x_lang or admin.language) from None


# ---------------- user: sawal ----------------
@router.get("/legal/sources")
def sources(_: User = Depends(current_user), db: Session = Depends(get_session)):
    docs = db.exec(select(LegalDocument).where(LegalDocument.status == "verified").order_by(LegalDocument.id)).all()
    return {"sources": [{"title": d.title, "source_url": d.source_url, "jurisdiction": d.jurisdiction, "verified_on": d.verified_on} for d in docs]}


class AskIn(BaseModel):
    question: str
    consent: bool = False
    language: str | None = None


@router.post("/legal/ask")
def legal_ask(data: AskIn, user: User = Depends(current_user), db: Session = Depends(get_session), x_lang: str | None = Header(default=None)):
    lang = pick_lang(data.language or x_lang or user.language)
    q = data.question.strip()
    if not 5 <= len(q) <= 1000:
        raise fail(422, "question_invalid", lang)
    since = utcnow() - timedelta(hours=1)
    used = db.exec(select(func.count()).select_from(AuditLog).where(AuditLog.actor_id == user.id, AuditLog.action == "rag_ask",
                                                                    AuditLog.at > since)).one()
    if used >= settings.rag_hourly_limit:
        raise fail(429, "ai_rate_limited", lang)
    ext_embed = settings.rag_embedder == "gemini"
    llm_wanted = settings.rag_use_llm and ai.key_ready_for_user(db, user.id)
    cfg = ai.user_config(db, user.id)
    key = ai.user_gemini_key(db, user.id)
    allow_external = False
    if ext_embed or llm_wanted:  # sawal bahar jaye to ijazat aur free-tier ki hifazat (jaise AI summary mein)
        reason = ai.availability_for_user(db, user.id)
        allow_external = reason is None and data.consent
        if ext_embed and not allow_external:
            raise fail(503 if reason else 422, reason or "ai_consent_required", lang)
    db.add(AuditLog(actor_id=user.id, action="rag_ask"))  # sirf ginti; sawal ka matn kabhi nahi
    db.commit()
    try:
        res = rag.ask(db, redact(q)[0], lang, allow_llm=allow_external, api_key=key, cfg=cfg)  # email/phone/CNIC pehle hat jate hain
    except rag.RagError:
        raise fail(503, "rag_unavailable", lang) from None
    res["llm_skipped"] = bool(llm_wanted and not allow_external)
    return res
