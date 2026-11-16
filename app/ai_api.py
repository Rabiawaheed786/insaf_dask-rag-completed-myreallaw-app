from datetime import timedelta

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel
from sqlmodel import Session, func, select

from . import ai
from .auth import current_user
from .cases import CATEGORIES
from .db import get_session
from .messages import fail, pick_lang
from .models import AuditLog, User, utcnow
from .redact import redact

router = APIRouter(prefix="/api/ai", tags=["ai"])


class QA(BaseModel):
    question: str
    answer: str


class AIIn(BaseModel):
    category: str
    statement: str
    consent: bool = False
    answers: list[QA] = []
    language: str | None = None


def _prepare(data: AIIn, user: User, db: Session, lang: str):
    reason = ai.availability_for_user(db, user.id, data.category)
    if reason:
        raise fail(503, reason, lang)
    if not data.consent:
        raise fail(422, "ai_consent_required", lang)
    if data.category not in CATEGORIES:
        raise fail(422, "category_invalid", lang)
    st = data.statement.strip()
    if len(st) < 20:
        raise fail(422, "statement_short", lang)
    if len(st) > 5000 or len(data.answers) > 5 or any(len(a.answer) > 500 or len(a.question) > 300 for a in data.answers):
        raise fail(422, "field_too_long", lang)
    from .config import settings
    since = utcnow() - timedelta(hours=1)
    used = db.exec(select(func.count()).select_from(AuditLog).where(
        AuditLog.actor_id == user.id, AuditLog.action == "ai_call", AuditLog.at > since)).one()
    if used >= settings.ai_hourly_limit:
        raise fail(429, "ai_rate_limited", lang)
    db.add(AuditLog(actor_id=user.id, action="ai_call"))  # sirf ginti; text kabhi nahi
    db.commit()
    counts: dict[str, int] = {}
    clean, c = redact(st)
    for k, v in c.items():
        counts[k] = counts.get(k, 0) + v
    qa = []
    for a in data.answers:
        q, c1 = redact(a.question)
        an, c2 = redact(a.answer)
        for k, v in {**c1}.items():
            counts[k] = counts.get(k, 0) + v
        for k, v in {**c2}.items():
            counts[k] = counts.get(k, 0) + v
        qa.append((q, an))
    return clean, qa, counts


def _prompt(task: str, data: AIIn, clean: str, qa, user: User) -> str:
    lang = data.language if data.language in ("roman_urdu", "en") else user.language
    lang_name = "English" if lang == "en" else "Roman Urdu (Urdu written in Latin letters, simple words)"
    extra = "".join(f"\nQ: {q}\nA: {a}" for q, a in qa)
    if task == "CLARIFY":
        job = ('Ask at most 5 short questions about important MISSING facts (who, where, when, documents). '
               'Return {"questions": ["...", ...]}.')
    else:
        job = ('Write a neutral summary of 3 to 6 short sentences using only the facts given. '
               'Return {"summary": "..."}.')
    return (f"TASK={task}\nCategory: {data.category}\nOutput language: {lang_name}\n{job}\n"
            f"<<<USER_STATEMENT\n{clean}{extra}\nUSER_STATEMENT>>>")


@router.get("/status")
def status(category: str | None = None, user: User = Depends(current_user), db: Session = Depends(get_session),
           x_lang: str | None = Header(default=None)):
    reason = ai.availability_for_user(db, user.id, category)
    lang = pick_lang(x_lang or user.language)
    return {"available": reason is None, "reason": reason,
            "message": fail(0, reason, lang).detail["message"] if reason else None}


@router.post("/clarify")
def clarify(data: AIIn, user: User = Depends(current_user), db: Session = Depends(get_session),
            x_lang: str | None = Header(default=None)):
    lang = x_lang or user.language
    clean, qa, counts = _prepare(data, user, db, lang)
    try:
        out = ai.generate_json(_prompt("CLARIFY", data, clean, qa, user), cfg=ai.user_config(db, user.id))
        qs = [str(q).strip()[:300] for q in out.get("questions", []) if str(q).strip()][:5]
    except (ai.AIError, AttributeError, TypeError):
        raise fail(503, "ai_unavailable", lang) from None
    return {"questions": qs, "ai": True, "redactions": counts}


@router.post("/summarize")
def summarize(data: AIIn, user: User = Depends(current_user), db: Session = Depends(get_session),
              x_lang: str | None = Header(default=None)):
    lang = x_lang or user.language
    clean, qa, counts = _prepare(data, user, db, lang)
    try:
        out = ai.generate_json(_prompt("SUMMARIZE", data, clean, qa, user), cfg=ai.user_config(db, user.id))
        summary = str(out.get("summary", "")).strip()[:3000]
        if not summary:
            raise ai.AIError("EmptySummary")
    except (ai.AIError, AttributeError, TypeError):
        raise fail(503, "ai_unavailable", lang) from None
    return {"summary": summary, "ai": True, "redactions": counts,
            "notice": fail(0, "ai_notice", pick_lang(lang)).detail["message"]}
