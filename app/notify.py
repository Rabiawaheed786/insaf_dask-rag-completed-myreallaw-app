"""In-app reminders, notifications aur scheduler ke jobs.
Duplicate se bachao: har reminder ka (user, kind, period_key) unique hai, aur 'kab due hai' har baar
waqt se nikalta hai (koi yaad-dasht nahi), is liye restart ke baad bhi ek hi dafa banta hai."""
import json
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from .auth import current_user
from .db import get_session
from .messages import fail, pick_lang
from .models import (Case, CaseEvent, ChatMessage, FollowupSettings, Notification, User, utcnow)
from .ops import require_admin

router = APIRouter(prefix="/api", tags=["notifications"])
PREFS = ("daily", "weekly", "important_only", "off")
IMPORTANT = {"lawyer_accepted", "lawyer_unassigned", "referral_delivered", "referral_failed", "slot_cancelled"}
TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


# ---------- zabaan ----------
def tr(lang: str, ur: str, en: str) -> str:
    return en if lang == "en" else ur


EVENT_BODY = {
    "lawyer_accepted": ("Wakeel ne aap ki request qubool kar li hai.", "A lawyer has accepted your request."),
    "lawyer_unassigned": ("Wakeel ab is request par nahi hai. Request coordinator ki queue mein hai.",
                          "The lawyer is no longer on this request. It is back in the coordinator queue."),
    "referral_delivered": ("Aap ki request ka referral centre tak pahunch gaya (centre ne tasdeeq ki).",
                           "Your referral reached the centre (the centre confirmed)."),
    "referral_failed": ("Referral abhi kamyab nahi hui; coordinator dobara koshish kar sakta hai.",
                        "The referral was not successful yet; the coordinator may try again."),
    "slot_cancelled": ("Wakeel ne aap ka booked waqt mansookh kar diya. Naya waqt chunein.",
                       "The lawyer cancelled your booked time. Please choose a new time."),
}
NOTE = ("Reminder ka matlab wakeel se roz jawab ki guarantee nahi.",
        "A reminder is not a guarantee that a lawyer will reply every day.")


def render(n: Notification, lang: str) -> dict:
    d = json.loads(n.data or "{}")
    if n.kind == "status_update":
        ur, en = EVENT_BODY.get(d.get("event"), ("Aap ki request mein update hai.", "There is an update on your request."))
        body = tr(lang, ur, en) + f" ({d.get('tracking_no', '')})"
        preview = tr(lang, "Aap ki request mein update hai.", "There is an update on your request.")
    elif n.kind in ("daily_reminder", "weekly_summary"):
        preview = tr(lang, "Insaf Dastak ka reminder.", "A reminder from Insaf Dastak.") if n.kind == "daily_reminder" \
            else tr(lang, "Insaf Dastak ka haftawar khulasa.", "Your weekly summary from Insaf Dastak.")
        o, p, a = d.get("open", 0), d.get("pending_action", 0), d.get("activity", 0)
        if n.kind == "daily_reminder":
            body = tr(lang, f"Aap ki {o} request khuli hai.", f"You have {o} open request(s).")
            act_ur = " Abhi naya jawab nahi aaya." if a == 0 else f" {a} naya update hai."
            act_en = " No new reply yet." if a == 0 else f" {a} new update(s)."
        else:
            body = tr(lang, f"Is haftay: {o} request khuli, {a} activity.", f"This week: {o} open request(s), {a} activity.")
            act_ur = act_en = ""
        body += tr(lang, act_ur, act_en)
        if p:
            body += tr(lang, " Agla kaam aap ka hai: referral ki ijazat dein, taake coordinator wakeel dhoondh sake.",
                       " Your next step: give referral consent so the coordinator can look for a lawyer.")
        elif n.kind == "weekly_summary":
            body += tr(lang, " Abhi koi kaam aap ke zimme nahi.", " Nothing is waiting on you right now.")
        body += " " + tr(lang, *NOTE)
    elif n.kind == "slot_booked":
        preview = tr(lang, "Aap ki availability mein update hai.", "There is an update on your availability.")
        body = tr(lang, f"Ek slot book hua hai ({d.get('start', '')}).", f"A slot was booked ({d.get('start', '')}).")
    else:  # slot_released
        preview = tr(lang, "Aap ki availability mein update hai.", "There is an update on your availability.")
        body = tr(lang, f"Ek booked slot khali ho gaya ({d.get('start', '')}).", f"A booked slot was released ({d.get('start', '')}).")
    return {"id": n.id, "kind": n.kind, "preview": preview, "body": body,
            "at": n.created_at.isoformat(), "read": n.read_at is not None}


# ---------- jobs ----------
def sync_status_notifications(db: Session) -> int:
    done = select(Notification.event_id).where(Notification.event_id.is_not(None))
    evs = db.exec(select(CaseEvent).where(CaseEvent.event_type.in_(IMPORTANT), CaseEvent.id.not_in(done))).all()
    made = 0
    for e in evs:
        c = db.get(Case, e.request_id)
        db.add(Notification(user_id=c.user_id, kind="status_update", request_id=c.id, event_id=e.id,
                            data=json.dumps({"event": e.event_type, "tracking_no": c.tracking_no}), created_at=e.at))
        try:
            db.commit()
            made += 1
        except IntegrityError:  # kisi aur ne bana di
            db.rollback()
    return made


def _local(now_utc: datetime, tzname: str) -> datetime:
    try:
        tz = ZoneInfo(tzname)
    except ZoneInfoNotFoundError:
        tz = ZoneInfo("Asia/Karachi")
    return now_utc.replace(tzinfo=timezone.utc).astimezone(tz)


def _due(pref: str, safe_time: str, local: datetime):
    hh, mm = (int(x) for x in safe_time.split(":"))
    reached = (local.hour, local.minute) >= (hh, mm)
    if pref == "daily" and reached:
        return "daily_reminder", "d:" + local.date().isoformat()
    if pref == "weekly" and (local.weekday() > 0 or reached):  # haftay ka pehla mauqa: Peer ko safe_time par
        iso = local.isocalendar()
        return "weekly_summary", f"w:{iso.year}-W{iso.week:02d}"
    return None


def run_reminders(db: Session, now: datetime | None = None) -> int:
    now = now or utcnow()
    made = 0
    rows = db.exec(select(FollowupSettings, User).join(User, User.id == FollowupSettings.user_id)
                   .where(FollowupSettings.pref.in_(("daily", "weekly")))).all()
    for fs, u in rows:
        due = _due(fs.pref, fs.safe_time, _local(now, u.timezone))
        if not due:
            continue
        kind, key = due
        open_cases = db.exec(select(Case).where(Case.user_id == u.id, Case.status == "saved")).all()
        if not open_cases:
            continue  # khuli request nahi: koi faltu reminder nahi
        since = now - timedelta(days=1 if kind == "daily_reminder" else 7)
        ids = [c.id for c in open_cases]
        events = db.exec(select(CaseEvent).where(CaseEvent.request_id.in_(ids), CaseEvent.event_type.in_(IMPORTANT),
                                                 CaseEvent.at > since)).all()
        replies = db.exec(select(ChatMessage).where(ChatMessage.request_id.in_(ids), ChatMessage.sender_role == "lawyer",
                                                    ChatMessage.created_at > since)).all()
        data = {"open": len(open_cases), "pending_action": sum(1 for c in open_cases if not c.referral_consent),
                "activity": len(events) + len(replies)}
        db.add(Notification(user_id=u.id, kind=kind, period_key=key, data=json.dumps(data), created_at=now))
        try:
            db.commit()
            made += 1
        except IntegrityError:  # is period ki reminder pehle se hai
            db.rollback()
    return made


def run_all(db: Session, now: datetime | None = None) -> dict:
    from .lawyers import expire_stale
    before = len(db.exec(select(CaseEvent).where(CaseEvent.event_type == "lawyer_offer_expired")).all())
    expire_stale(db)
    after = len(db.exec(select(CaseEvent).where(CaseEvent.event_type == "lawyer_offer_expired")).all())
    from .retention import purge_expired
    purged = purge_expired(db, now)
    return {"offers_expired": after - before, "status_notifications": sync_status_notifications(db),
            "reminders": run_reminders(db, now), **purged}


# ---------- user: follow-up ----------
class FollowupIn(BaseModel):
    pref: str | None = None
    safe_time: str | None = None
    channel: str | None = None
    timezone: str | None = None


def _fs(db: Session, user: User) -> FollowupSettings:
    fs = db.exec(select(FollowupSettings).where(FollowupSettings.user_id == user.id)).first()
    if not fs:
        fs = FollowupSettings(user_id=user.id)
        db.add(fs)
        db.commit()
        db.refresh(fs)
    return fs


def _fs_view(fs: FollowupSettings, user: User) -> dict:
    return {"pref": fs.pref, "safe_time": fs.safe_time, "channel": fs.channel, "timezone": user.timezone,
            "available_channels": ["in_app"], "note": tr(user.language, *NOTE)}


@router.get("/me/followup")
def get_followup(user: User = Depends(current_user), db: Session = Depends(get_session)):
    return _fs_view(_fs(db, user), user)


@router.put("/me/followup")
def put_followup(data: FollowupIn, user: User = Depends(current_user), db: Session = Depends(get_session),
                 x_lang: str | None = Header(default=None)):
    lang = x_lang or user.language
    fs = _fs(db, user)
    if data.pref is not None and data.pref not in PREFS:
        raise fail(422, "followup_invalid", lang)
    if data.safe_time is not None and not TIME_RE.match(data.safe_time):
        raise fail(422, "followup_invalid", lang)
    if data.channel is not None and data.channel != "in_app":
        raise fail(422, "channel_unavailable", lang)  # email/SMS/WhatsApp: provider aur consent ke bagair nahi
    if data.timezone is not None:
        try:
            ZoneInfo(data.timezone)
        except (ZoneInfoNotFoundError, ValueError, OSError):
            raise fail(422, "tz_invalid", lang) from None
        user.timezone = data.timezone
        db.add(user)
    fs.pref = data.pref or fs.pref
    fs.safe_time = data.safe_time or fs.safe_time
    db.add(fs)
    db.commit()
    return _fs_view(fs, user)


# ---------- user: notifications ----------
@router.get("/notifications")
def my_notifications(user: User = Depends(current_user), db: Session = Depends(get_session),
                     x_lang: str | None = Header(default=None)):
    sync_status_notifications(db)  # dashboard par important update hamesha, scheduler ke bagair bhi
    lang = pick_lang(x_lang or user.language)
    rows = db.exec(select(Notification).where(Notification.user_id == user.id)
                   .order_by(Notification.id.desc()).limit(50)).all()
    return {"notifications": [render(n, lang) for n in rows], "unread": sum(1 for n in rows if n.read_at is None)}


@router.post("/notifications/read-all")
def read_all(user: User = Depends(current_user), db: Session = Depends(get_session)):
    for n in db.exec(select(Notification).where(Notification.user_id == user.id, Notification.read_at.is_(None))).all():
        n.read_at = utcnow()
        db.add(n)
    db.commit()
    return {"ok": True}


@router.post("/notifications/{nid}/read")
def read_one(nid: int, user: User = Depends(current_user), db: Session = Depends(get_session),
             x_lang: str | None = Header(default=None)):
    n = db.get(Notification, nid)
    if not n or n.user_id != user.id:
        raise fail(404, "not_found", x_lang or user.language)
    n.read_at = n.read_at or utcnow()
    db.add(n)
    db.commit()
    return render(n, pick_lang(x_lang or user.language))


@router.post("/admin/jobs/run")
def run_jobs_now(_: User = Depends(require_admin), db: Session = Depends(get_session)):
    return run_all(db)
