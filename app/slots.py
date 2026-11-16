"""Wakeel ki availability aur user ki booking. Slot sirf wakeel ka diya hua; booking sirf us ke accepted case ke user ki."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel
from sqlalchemy import update
from sqlmodel import Session, select

from .auth import current_user
from .chat import access
from .config import settings
from .db import get_session
from .lawyers import require_lawyer
from .messages import fail
from .models import (Assignment, AuditLog, AvailabilitySlot, Case, CaseEvent, LawyerProfile, Notification, User, utcnow)
import json

router = APIRouter(prefix="/api", tags=["availability"])


def _tz(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        return ZoneInfo("Asia/Karachi")


def _view(s: AvailabilitySlot, tzname: str) -> dict:
    st, en = s.start.replace(tzinfo=timezone.utc), s.end.replace(tzinfo=timezone.utc)
    return {"id": s.id, "start": st.isoformat(), "end": en.isoformat(),
            "start_local": st.astimezone(_tz(tzname)).isoformat(), "end_local": en.astimezone(_tz(tzname)).isoformat(),
            "status": s.status}


def _parse(value: str, tzname: str, lang) -> datetime:
    try:
        dt = datetime.fromisoformat(value)
    except (ValueError, TypeError):
        raise fail(422, "slot_invalid", lang) from None
    if dt.tzinfo is None:  # bina timezone ka waqt user ke apne timezone mein maana jata hai
        dt = dt.replace(tzinfo=_tz(tzname))
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


class SlotIn(BaseModel):
    start: str
    end: str
    repeat: str = "none"  # none | daily | weekly
    repeat_count: int = 1


@router.post("/lawyer/availability", status_code=201)
def publish(data: SlotIn, p: LawyerProfile = Depends(require_lawyer), user: User = Depends(current_user),
            db: Session = Depends(get_session), x_lang: str | None = Header(default=None)):
    lang = x_lang or user.language
    start, end = _parse(data.start, user.timezone, lang), _parse(data.end, user.timezone, lang)
    limit = {"none": 1, "daily": 14, "weekly": 8}.get(data.repeat)
    if limit is None or not (1 <= data.repeat_count <= limit):
        raise fail(422, "repeat_invalid", lang)
    step = {"none": timedelta(0), "daily": timedelta(days=1), "weekly": timedelta(weeks=1)}[data.repeat]
    now = utcnow()
    minutes = (end - start).total_seconds() / 60
    if (start <= now or not settings.slot_min_minutes <= minutes <= settings.slot_max_minutes
            or start + step * (data.repeat_count - 1) > now + timedelta(days=settings.slot_max_days_ahead)):
        raise fail(422, "slot_invalid", lang)
    wanted = [(start + step * i, end + step * i) for i in range(data.repeat_count)]
    mine = db.exec(select(AvailabilitySlot).where(AvailabilitySlot.lawyer_profile_id == p.id,
                                                  AvailabilitySlot.status.in_(("open", "booked")))).all()
    for s, e in wanted:  # sab ya kuch nahi: ek bhi takraye to koi slot nahi banta
        if any(s < m.end and e > m.start for m in mine):
            raise fail(409, "slot_overlap", lang)
    made = [AvailabilitySlot(lawyer_profile_id=p.id, start=s, end=e) for s, e in wanted]
    db.add_all(made)
    db.commit()
    for m in made:
        db.refresh(m)
    return {"slots": [_view(m, user.timezone) for m in made]}


@router.get("/lawyer/availability")
def my_slots(p: LawyerProfile = Depends(require_lawyer), user: User = Depends(current_user),
             db: Session = Depends(get_session)):
    rows = db.exec(select(AvailabilitySlot).where(AvailabilitySlot.lawyer_profile_id == p.id,
                                                  AvailabilitySlot.end > utcnow(),
                                                  AvailabilitySlot.status != "cancelled")
                   .order_by(AvailabilitySlot.start)).all()
    out = []
    for s in rows:
        v = _view(s, user.timezone)
        if s.status == "booked":
            v["booked_tracking_no"] = db.get(Case, s.booked_request_id).tracking_no
        out.append(v)
    return {"slots": out}


@router.delete("/lawyer/availability/{sid}")
def cancel_slot(sid: int, p: LawyerProfile = Depends(require_lawyer), user: User = Depends(current_user),
                db: Session = Depends(get_session), x_lang: str | None = Header(default=None)):
    lang = x_lang or user.language
    s = db.get(AvailabilitySlot, sid)
    if not s or s.lawyer_profile_id != p.id:
        raise fail(404, "not_found", lang)
    if s.status == "cancelled":
        raise fail(409, "not_pending", lang)
    if s.status == "booked" and s.booked_request_id:  # user ko important update (scheduler/dashboard se)
        db.add(CaseEvent(request_id=s.booked_request_id, event_type="slot_cancelled"))
    s.status, s.booked_request_id = "cancelled", None
    db.add(s)
    db.commit()
    return {"id": s.id, "status": "cancelled"}


# ---------- user: slot dekhna aur book karna ----------
def _owner_case(db, user, tracking_no, lang) -> Case:
    c, role = access(db, user, tracking_no, lang)
    if role != "user":
        raise fail(403, "forbidden", lang)
    return c


def _accepted_profile(db, c: Case) -> LawyerProfile | None:
    a = db.exec(select(Assignment).where(Assignment.request_id == c.id, Assignment.status == "accepted")).first()
    return db.get(LawyerProfile, a.lawyer_profile_id) if a else None


@router.get("/cases/{tracking_no}/slots")
def case_slots(tracking_no: str, user: User = Depends(current_user), db: Session = Depends(get_session),
               x_lang: str | None = Header(default=None)):
    c = _owner_case(db, user, tracking_no, x_lang or user.language)
    p = _accepted_profile(db, c)
    now = utcnow()
    open_slots, mine = [], None
    if p and c.status != "closed":
        for s in db.exec(select(AvailabilitySlot).where(AvailabilitySlot.lawyer_profile_id == p.id,
                                                        AvailabilitySlot.start > now).order_by(AvailabilitySlot.start)).all():
            if s.status == "open":
                open_slots.append(_view(s, user.timezone))
            elif s.status == "booked" and s.booked_request_id == c.id:
                mine = _view(s, user.timezone)
    return {"open_slots": open_slots, "my_booking": mine}


def _notify_lawyer(db, p: LawyerProfile, kind: str, s: AvailabilitySlot, c: Case):
    db.add(Notification(user_id=p.user_id, kind=kind, request_id=c.id,
                        data=json.dumps({"start": s.start.replace(tzinfo=timezone.utc).isoformat()})))


@router.post("/cases/{tracking_no}/slots/{sid}/book")
def book(tracking_no: str, sid: int, user: User = Depends(current_user), db: Session = Depends(get_session),
         x_lang: str | None = Header(default=None)):
    lang = x_lang or user.language
    c = _owner_case(db, user, tracking_no, lang)
    p = _accepted_profile(db, c)
    s = db.get(AvailabilitySlot, sid)
    now = utcnow()
    if c.status == "closed":
        raise fail(409, "request_closed", lang)
    if not p or not s or s.lawyer_profile_id != p.id or s.start <= now:
        raise fail(404, "not_found", lang)
    if db.exec(select(AvailabilitySlot).where(AvailabilitySlot.booked_request_id == c.id,
                                              AvailabilitySlot.status == "booked", AvailabilitySlot.start > now)).first():
        raise fail(409, "already_booked", lang)
    # ek hi qadam mein "agar abhi khali hai to book": do log ek saath koshish karein to sirf ek jeetta hai
    res = db.exec(update(AvailabilitySlot).where(AvailabilitySlot.id == sid, AvailabilitySlot.status == "open")
                  .values(status="booked", booked_request_id=c.id, booked_at=now))
    if res.rowcount != 1:
        db.rollback()
        raise fail(409, "slot_taken", lang)
    db.refresh(s)
    db.add(CaseEvent(request_id=c.id, event_type="consult_booked"))
    _notify_lawyer(db, p, "slot_booked", s, c)
    db.add(AuditLog(actor_id=user.id, action="slot_booked", detail=f"{c.tracking_no}:{sid}"))
    db.commit()
    return _view(s, user.timezone) | {"status": "booked"}


@router.delete("/cases/{tracking_no}/slots/{sid}/book")
def unbook(tracking_no: str, sid: int, user: User = Depends(current_user), db: Session = Depends(get_session),
           x_lang: str | None = Header(default=None)):
    lang = x_lang or user.language
    c = _owner_case(db, user, tracking_no, lang)
    s = db.get(AvailabilitySlot, sid)
    if not s or s.booked_request_id != c.id or s.status != "booked":
        raise fail(404, "not_found", lang)
    p = db.get(LawyerProfile, s.lawyer_profile_id)
    s.status, s.booked_request_id, s.booked_at = "open", None, None
    db.add(s)
    db.add(CaseEvent(request_id=c.id, event_type="consult_cancelled"))
    _notify_lawyer(db, p, "slot_released", s, c)
    db.commit()
    return {"id": s.id, "status": "open"}
