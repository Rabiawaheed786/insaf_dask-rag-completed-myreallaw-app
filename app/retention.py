"""Mitana: band hui requests ka text, chat aur files, aur khud account mitana. Tracking number, category, shehar baqi
rehte hain (ginti ke liye); koi bayan, summary, message ya file nahi."""
from datetime import datetime, timedelta
from pathlib import Path

from sqlmodel import Session, select

from .config import settings
from .models import (Attachment, AuditLog, AuthSession, Case, CaseEvent, ChatMessage, Referral, utcnow)

GONE = "[deleted]"


def anonymize_case(db: Session, c: Case, reason: str):
    from .lawyers import revoke_active
    revoke_active(db, c, reason)  # wakeel ka access aur booked slot bhi ja
    c.statement, c.summary, c.safe_time = GONE, GONE, None
    c.child_review_note = None
    db.add(c)
    for m in db.exec(select(ChatMessage).where(ChatMessage.request_id == c.id)).all():
        db.delete(m)
    for r in db.exec(select(Referral).where(Referral.request_id == c.id)).all():
        r.failed_reason = None
        db.add(r)
    for a in db.exec(select(Attachment).where(Attachment.request_id == c.id, Attachment.deleted_at.is_(None))).all():
        a.deleted_at = utcnow()
        db.add(a)
        (Path(settings.upload_dir) / a.stored_name).unlink(missing_ok=True)


def purge_expired(db: Session, now: datetime | None = None) -> dict:
    now = now or utcnow()
    old_sessions = db.exec(select(AuthSession).where(AuthSession.expires_at < now)).all()
    for s in old_sessions:
        db.delete(s)
    cutoff = now - timedelta(days=settings.retention_days)
    ids = {e.request_id for e in db.exec(select(CaseEvent).where(CaseEvent.event_type == "closed",
                                                                   CaseEvent.at < cutoff)).all()}
    n = 0
    for cid in ids:
        c = db.get(Case, cid)
        if c and c.status == "closed" and c.statement != GONE:
            anonymize_case(db, c, "retention")
            db.add(AuditLog(actor_id=None, action="retention_purged", detail=c.tracking_no))
            n += 1
    db.commit()
    return {"sessions_deleted": len(old_sessions), "cases_purged": n}
