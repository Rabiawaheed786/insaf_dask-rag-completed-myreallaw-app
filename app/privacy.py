"""Foran madad, apna data export, apni Gemini key aur apna account mitana."""
import json
import re
import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, Header, Response
from pydantic import BaseModel
from sqlmodel import Session, select

from .auth import COOKIE, current_user, public_user
from .cases import _labels, _view, contacts_for
from .config import settings
from .crypto import decrypt_secret, encrypt_secret
from .db import get_session
from .messages import fail, pick_lang
from .models import (Attachment, AuditLog, AuthSession, Case, ChatMessage, FollowupSettings, LawyerProfile,
                     Notification, OfficialContact, User, utcnow)
from .notify import render
from .retention import anonymize_case
from .security import hash_password, new_token, verify_password
from .services import llm

router = APIRouter(prefix="/api", tags=["privacy-safety"])
GEMINI_KEY_RE = re.compile(r"^AIza[0-9A-Za-z_-]{16,200}$")


@router.get("/emergency")
def emergency(x_lang: str | None = Header(default=None)):
    """Bina login ke. App ke jawab ka intezar nahi: pehle foran madad."""
    lang = pick_lang(x_lang)
    msg = ("Agar aap ko foran khatra hai to is app ke jawab ka intezar na karein: apne ilaqe ki police ya emergency "
           "service ko foran call karein, ya kisi qareebi bharosemand shakhs ke paas pahunchein."
           if lang != "en" else
           "If you are in immediate danger, do not wait for this app: call your local police or emergency service "
           "right now, or go to someone nearby you trust.")
    from .db import engine
    with Session(engine) as db:
        rows = db.exec(select(OfficialContact).where(OfficialContact.emergency == True)).all()  # noqa: E712
        contacts = [{"name": r.name, "phone": r.phone, "note": r.note_en if lang == "en" else r.note_roman_urdu,
                     "source_url": r.source_url, "verified_on": r.verified_on} for r in rows]
    return {"message": msg, "contacts": contacts}


@router.get("/me/export")
def export_mine(user: User = Depends(current_user), db: Session = Depends(get_session),
                x_lang: str | None = Header(default=None)):
    lang = pick_lang(x_lang or user.language)
    reqs = []
    for c in db.exec(select(Case).where(Case.user_id == user.id).order_by(Case.id)).all():
        v = _view(c, db, lang, full=True)
        v["messages"] = [{"from": m.sender_role, "body": m.body, "at": m.created_at.isoformat()}
                         for m in db.exec(select(ChatMessage).where(ChatMessage.request_id == c.id).order_by(ChatMessage.id)).all()]
        v["attachments"] = [{"name": a.display_name, "size": a.size, "uploaded_by": a.uploader_role}
                            for a in db.exec(select(Attachment).where(Attachment.request_id == c.id,
                                                                      Attachment.deleted_at.is_(None))).all()]
        reqs.append(v)
    fs = db.exec(select(FollowupSettings).where(FollowupSettings.user_id == user.id)).first()
    notes = db.exec(select(Notification).where(Notification.user_id == user.id).order_by(Notification.id)).all()
    return {"user": public_user(user), "followup": {"pref": fs.pref, "safe_time": fs.safe_time} if fs else None,
            "requests": reqs, "notifications": [render(n, lang) for n in notes]}


class DeleteIn(BaseModel):
    password: str


def _gemini_key_out(user: User) -> dict:
    key = decrypt_secret(user.encrypted_gemini_key)
    return {"configured": bool(key), "masked": llm.mask_user_key(key),
            "updated_at": user.gemini_key_updated_at.isoformat() if user.gemini_key_updated_at else None}


@router.get("/me/gemini-key")
def get_gemini_key(user: User = Depends(current_user)):
    """Sirf masked key wapas jati hai; asli key kabhi response mein nahi."""
    return _gemini_key_out(user)


class GeminiKeyIn(BaseModel):
    api_key: str = ""


@router.put("/me/gemini-key")
def save_gemini_key(data: GeminiKeyIn, user: User = Depends(current_user), db: Session = Depends(get_session),
                    x_lang: str | None = Header(default=None)):
    """Apni Gemini key save ya (khali bhej kar) hatana. Key encrypted save hoti hai aur audit mein nahi jati."""
    lang = x_lang or user.language
    key = data.api_key.strip()
    if key:
        if not GEMINI_KEY_RE.match(key):
            raise fail(422, "gemini_key_invalid", lang)
        user.encrypted_gemini_key = encrypt_secret(key)
        user.gemini_key_updated_at = utcnow()
        action = "gemini_key_saved"
    else:
        user.encrypted_gemini_key = ""
        user.gemini_key_updated_at = None
        action = "gemini_key_removed"
    db.add(user)
    db.add(AuditLog(actor_id=user.id, action=action))
    db.commit()
    db.refresh(user)
    return _gemini_key_out(user)


@router.delete("/me")
def delete_me(data: DeleteIn, response: Response, user: User = Depends(current_user),
              db: Session = Depends(get_session), x_lang: str | None = Header(default=None)):
    lang = x_lang or user.language
    if user.role != "user":  # wakeel/coordinator/admin: admin ke zariye (unke kaam ka hisab hota hai)
        raise fail(409, "delete_not_allowed", lang)
    if not verify_password(data.password, user.password_hash):
        raise fail(401, "password_wrong", lang)
    for c in db.exec(select(Case).where(Case.user_id == user.id)).all():
        anonymize_case(db, c, "account_deleted")
        c.status = "closed"
        db.add(c)
    for model in (Notification, FollowupSettings, AuthSession):
        for row in db.exec(select(model).where(model.user_id == user.id)).all():
            db.delete(row)
    for p in db.exec(select(LawyerProfile).where(LawyerProfile.user_id == user.id)).all():
        db.delete(p)
    uid = user.id
    shutil.rmtree(Path(settings.upload_dir) / str(uid), ignore_errors=True)  # apne folder ki files bhi
    user.email, user.display_name, user.password_hash = f"deleted-{uid}@deleted.invalid", "", hash_password(new_token())
    user.encrypted_gemini_key, user.gemini_key_updated_at = "", None
    db.add(user)
    db.add(AuditLog(actor_id=None, action="account_deleted", detail=str(uid)))
    db.commit()
    response.delete_cookie(COOKIE, path="/")
    return {"deleted": True}
