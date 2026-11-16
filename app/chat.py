"""Private chat aur private files. Access: sirf request ka malik, ya us ka accepted verified wakeel.
Baqi sab ko 404, taake pata hi na chale ke request maujood hai."""
import hashlib
import re
import secrets
from datetime import timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, File, Header, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, func, select

from .auth import current_user
from .config import settings
from .db import get_session
from .messages import fail, pick_lang
from .models import (Assignment, Attachment, AuditLog, Case, ChatMessage, LawyerProfile, User, utcnow)

router = APIRouter(prefix="/api/cases", tags=["chat-files"])


def access(db: Session, user: User, tracking_no: str, lang) -> tuple[Case, str]:
    c = db.exec(select(Case).where(Case.tracking_no == tracking_no.upper())).first()
    if c and c.user_id == user.id:
        return c, "user"
    if c and user.role == "lawyer" and c.status != "closed" and c.referral_consent:
        p = db.exec(select(LawyerProfile).where(LawyerProfile.user_id == user.id,
                                                LawyerProfile.verification_status == "verified")).first()
        if p and db.exec(select(Assignment).where(Assignment.request_id == c.id,
                                                  Assignment.lawyer_profile_id == p.id,
                                                  Assignment.status == "accepted")).first():
            return c, "lawyer"
    raise fail(404, "not_found", lang)


def _has_lawyer(db: Session, c: Case) -> bool:
    return db.exec(select(Assignment).where(Assignment.request_id == c.id,
                                            Assignment.status == "accepted")).first() is not None


def _key_ok(k: str | None) -> bool:
    return bool(k) and 8 <= len(k) <= 100


# ---------------- chat ----------------
class MsgIn(BaseModel):
    body: str


def _msg_view(m: ChatMessage, user: User) -> dict:
    return {"id": m.id, "from": m.sender_role, "mine": m.sender_id == user.id,
            "body": m.body, "at": m.created_at.isoformat()}


@router.get("/{tracking_no}/messages")
def list_messages(tracking_no: str, user: User = Depends(current_user), db: Session = Depends(get_session),
                  x_lang: str | None = Header(default=None)):
    c, _ = access(db, user, tracking_no, x_lang or user.language)
    rows = db.exec(select(ChatMessage).where(ChatMessage.request_id == c.id).order_by(ChatMessage.id)).all()
    return {"messages": [_msg_view(m, user) for m in rows],
            "chat_open": c.status != "closed" and _has_lawyer(db, c)}


@router.post("/{tracking_no}/messages")
def send_message(tracking_no: str, data: MsgIn, response: Response, user: User = Depends(current_user),
                 db: Session = Depends(get_session), idempotency_key: str | None = Header(default=None),
                 x_lang: str | None = Header(default=None)):
    lang = x_lang or user.language
    if not _key_ok(idempotency_key):
        raise fail(422, "idempotency_required", lang)
    c, role = access(db, user, tracking_no, lang)
    old = db.exec(select(ChatMessage).where(ChatMessage.request_id == c.id, ChatMessage.sender_id == user.id,
                                            ChatMessage.idempotency_key == idempotency_key)).first()
    if old:  # retry: wahi message, duplicate nahi
        return _msg_view(old, user)
    body = data.body.strip()
    if not (1 <= len(body) <= 2000):
        raise fail(422, "message_invalid", lang)
    if c.status == "closed":
        raise fail(409, "request_closed", lang)
    if not _has_lawyer(db, c):
        raise fail(409, "chat_not_available", lang)
    since = utcnow() - timedelta(hours=1)
    sent = db.exec(select(func.count()).select_from(ChatMessage).where(
        ChatMessage.request_id == c.id, ChatMessage.sender_id == user.id, ChatMessage.created_at > since)).one()
    if sent >= settings.chat_hourly_limit:
        raise fail(429, "chat_rate_limited", lang)
    m = ChatMessage(request_id=c.id, sender_id=user.id, sender_role=role, body=body, idempotency_key=idempotency_key)
    db.add(m)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        m = db.exec(select(ChatMessage).where(ChatMessage.request_id == c.id, ChatMessage.sender_id == user.id,
                                              ChatMessage.idempotency_key == idempotency_key)).one()
        return _msg_view(m, user)
    db.refresh(m)
    response.status_code = 201
    return _msg_view(m, user)


# ---------------- files ----------------
def sniff(b: bytes) -> tuple[str, str] | None:
    """File ki asli pehchaan uske shuru ke bytes se; name ya claim par bharosa nahi."""
    if b.startswith(b"%PDF-"):
        return "application/pdf", ".pdf"
    if b.startswith(b"\xff\xd8\xff"):
        return "image/jpeg", ".jpg"
    if b.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png", ".png"
    return None


def safe_name(original: str | None, ext: str) -> str:
    base = re.split(r"[\\/]", original or "")[-1]
    stem = re.sub(r"[^A-Za-z0-9._ ()-]", "", base.rsplit(".", 1)[0] if "." in base else base)
    stem = stem.strip(" .-_")[:80] or "file"
    return stem + ext


def _upload_path(stored: str) -> Path:
    return Path(settings.upload_dir) / stored


def _att_view(a: Attachment, user: User) -> dict:
    return {"id": a.id, "name": a.display_name, "size": a.size, "mime": a.mime,
            "uploaded_by": a.uploader_role, "mine": a.uploader_id == user.id, "at": a.created_at.isoformat()}


def _live_att(db: Session, c: Case, aid: int, lang) -> Attachment:
    a = db.get(Attachment, aid)
    if not a or a.request_id != c.id or a.deleted_at is not None:
        raise fail(404, "not_found", lang)
    return a


@router.get("/{tracking_no}/attachments")
def list_attachments(tracking_no: str, user: User = Depends(current_user), db: Session = Depends(get_session),
                     x_lang: str | None = Header(default=None)):
    c, _ = access(db, user, tracking_no, x_lang or user.language)
    rows = db.exec(select(Attachment).where(Attachment.request_id == c.id,
                                            Attachment.deleted_at.is_(None)).order_by(Attachment.id)).all()
    return {"attachments": [_att_view(a, user) for a in rows]}


@router.post("/{tracking_no}/attachments", status_code=201)
def upload(tracking_no: str, file: UploadFile = File(...), user: User = Depends(current_user),
           db: Session = Depends(get_session), x_lang: str | None = Header(default=None)):
    lang = x_lang or user.language
    c, role = access(db, user, tracking_no, lang)
    if c.status == "closed":
        raise fail(409, "request_closed", lang)
    live = db.exec(select(func.count()).select_from(Attachment).where(
        Attachment.request_id == c.id, Attachment.deleted_at.is_(None))).one()
    if live >= settings.max_files_per_case:
        raise fail(409, "too_many_files", lang)
    limit = settings.max_upload_mb * 1024 * 1024
    data = file.file.read(limit + 1)  # bari file poori memory mein nahi parhi jati
    if not data:
        raise fail(422, "file_empty", lang)
    if len(data) > limit:
        raise fail(413, "file_too_large", lang)
    kind = sniff(data)
    if not kind:
        raise fail(422, "file_type_invalid", lang)
    mime, ext = kind
    stored = secrets.token_hex(16)  # user ke input se kuch nahi: path-traversal mumkin hi nahi
    path = _upload_path(stored)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    a = Attachment(request_id=c.id, uploader_id=user.id, uploader_role=role,
                   display_name=safe_name(file.filename, ext), stored_name=stored, mime=mime,
                   size=len(data), sha256=hashlib.sha256(data).hexdigest())
    try:
        db.add(a)
        db.add(AuditLog(actor_id=user.id, action="file_uploaded", detail=c.tracking_no))
        db.commit()
    except Exception:
        db.rollback()
        path.unlink(missing_ok=True)
        raise
    db.refresh(a)
    return _att_view(a, user)


@router.get("/{tracking_no}/attachments/{aid}")
def download(tracking_no: str, aid: int, user: User = Depends(current_user), db: Session = Depends(get_session),
             x_lang: str | None = Header(default=None)):
    lang = x_lang or user.language
    c, _ = access(db, user, tracking_no, lang)
    a = _live_att(db, c, aid, lang)
    path = _upload_path(a.stored_name)
    if not path.exists():
        raise fail(404, "file_missing", lang)
    db.add(AuditLog(actor_id=user.id, action="file_downloaded", detail=f"{c.tracking_no}:{a.id}"))
    db.commit()
    # attachment ke taur par (browser mein khulta nahi); nosniff middleware lagata hai
    return FileResponse(path, media_type=a.mime, filename=a.display_name)


@router.delete("/{tracking_no}/attachments/{aid}")
def delete_file(tracking_no: str, aid: int, user: User = Depends(current_user),
                db: Session = Depends(get_session), x_lang: str | None = Header(default=None)):
    lang = x_lang or user.language
    c, role = access(db, user, tracking_no, lang)
    a = _live_att(db, c, aid, lang)
    if role == "lawyer" and a.uploader_id != user.id:  # wakeel sirf apni file hata sakta hai
        raise fail(403, "forbidden", lang)
    a.deleted_at = utcnow()
    db.add(a)
    db.add(AuditLog(actor_id=user.id, action="file_deleted", detail=f"{c.tracking_no}:{a.id}"))
    db.commit()
    _upload_path(a.stored_name).unlink(missing_ok=True)
    return {"deleted": True}
