import secrets
from datetime import date

from fastapi import APIRouter, Depends, Header, Response
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from .auth import current_user
from .config import settings
from .db import get_session
from .messages import fail, pick_lang
from .models import (Assignment, AuditLog, AvailabilitySlot, Case, CaseEvent, LawyerProfile, OfficialContact,
                     Referral, User, utcnow)

router = APIRouter(prefix="/api", tags=["requests"])

CATEGORIES = {
    "property": ("Jaidad aur zameen", "Property and land"),
    "inheritance": ("Wirasat", "Inheritance"),
    "tenancy": ("Ghar aur kiraya", "Home and rent"),
    "prison": ("Jail ya hawalaat mein band log", "People in custody or prison"),
    "police": ("Police aur sarkari idaray", "Police and government offices"),
    "women": ("Khawateen ke masle", "Women's issues"),
    "children": ("Bachon ke huqooq", "Children's rights"),
    "elders": ("Buzurgon ke masle", "Elders' issues"),
    "labour": ("Mazdoori aur naukri", "Labour and employment"),
    "fraud_debt": ("Karza, dhoka, fraud", "Debt, cheating and fraud"),
    "cyber_scam": ("Scam aur cyber masle", "Scams and cyber issues"),
    "other": ("Doosra masla", "Other problem"),
}
PROVINCES = ["punjab", "sindh", "kpk", "balochistan", "islamabad", "gilgit_baltistan", "ajk"]
ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # confusing harf (0, O, 1, I) nahi


class CaseIn(BaseModel):
    category: str
    city: str
    province: str | None = None
    statement: str
    summary: str
    safe_time: str | None = None
    ai_used: bool = False  # summary AI draft se shuru hui (user ne approve ki)


def _new_tracking() -> str:
    return f"IS-{utcnow().year}-" + "".join(secrets.choice(ALPHABET) for _ in range(6))


def _labels(lang: str) -> dict:
    i = 1 if lang == "en" else 0
    return {k: v[i] for k, v in CATEGORIES.items()}


def _view(c: Case, db: Session, lang: str, full: bool = False) -> dict:
    out = {"id": c.id, "tracking_no": c.tracking_no, "category": c.category,
           "category_label": _labels(lang)[c.category], "city": c.city, "province": c.province,
           "status": c.status, "referral_status": c.referral_status,
           "lawyer_status": c.lawyer_status, "child_review": c.child_review_status,
           "created_at": c.created_at.isoformat()}
    if full:
        events = db.exec(select(CaseEvent).where(CaseEvent.request_id == c.id)
                         .order_by(CaseEvent.id)).all()
        out.update(statement=c.statement, summary=c.summary, safe_time=c.safe_time,
                   timeline=[{"event": e.event_type, "at": e.at.isoformat()} for e in events])
        out["referral_consent"] = c.referral_consent
        out["referrals"] = [{"target": r.target, "status": r.status, "at": r.created_at.isoformat()}
                            for r in db.exec(select(Referral).where(Referral.request_id == c.id)
                                             .order_by(Referral.id)).all()]
        slot = db.exec(select(AvailabilitySlot).where(AvailabilitySlot.booked_request_id == c.id,
                                                      AvailabilitySlot.status == "booked",
                                                      AvailabilitySlot.start > utcnow())).first()
        if slot:
            out["consultation"] = {"start": slot.start.isoformat() + "+00:00"}
        days = (utcnow() - c.created_at).days
        if c.status == "closed":
            out["next_action"] = msg("next_closed", lang)
        elif c.child_review_status == "pending":
            out["next_action"] = msg("next_child_review", lang)
            out["alternatives_suggested"] = False
            out["fallback_contacts"] = contacts_for(db, c.province, lang)
        elif c.lawyer_status == "accepted":
            out["next_action"] = msg("next_accepted", lang)
            acc = db.exec(select(Assignment).where(Assignment.request_id == c.id,
                                                   Assignment.status == "accepted")).first()
            lp = db.get(LawyerProfile, acc.lawyer_profile_id) if acc else None
            lu = db.get(User, lp.user_id) if lp else None
            if lu:
                out["assigned_lawyer"] = {"display_name": lu.display_name, "city": lp.city}
        else:
            overdue = days >= settings.overdue_days
            out["next_action"] = msg("next_alternatives" if overdue else "next_not_assigned", lang)
            out["alternatives_suggested"] = overdue
            out["fallback_contacts"] = contacts_for(db, c.province, lang)
        if c.referral_status == "failed" and c.status != "closed":
            out["next_action"] += " " + msg("referral_failed_note", lang)
    return out


def msg(code: str, lang: str) -> str:
    return fail(0, code, lang).detail["message"]


def contacts_for(db: Session, province: str | None, lang: str) -> list[dict]:
    rows = db.exec(select(OfficialContact)).all()
    rows = [r for r in rows if r.scope == "national" or r.scope == province]
    return [{"name": r.name, "phone": r.phone,
             "note": r.note_en if lang == "en" else r.note_roman_urdu,
             "source_url": r.source_url, "verified_on": r.verified_on, "emergency": r.emergency} for r in rows]


def _own_case(db: Session, user: User, case_id: int, lang) -> Case:
    c = db.get(Case, case_id)
    if not c or c.user_id != user.id:  # doosre ki request ka pata hi na chale
        raise fail(404, "not_found", lang)
    return c


@router.get("/categories")
def categories(x_lang: str | None = Header(default=None)):
    lang = pick_lang(x_lang)
    return {"categories": [{"key": k, "label": v} for k, v in _labels(lang).items()],
            "provinces": PROVINCES}


@router.get("/official-contacts")
def official_contacts(province: str | None = None, db: Session = Depends(get_session),
                      x_lang: str | None = Header(default=None)):
    return {"contacts": contacts_for(db, province, pick_lang(x_lang))}


@router.post("/requests")
def create_request(data: CaseIn, response: Response, user: User = Depends(current_user),
                   db: Session = Depends(get_session),
                   idempotency_key: str | None = Header(default=None),
                   x_lang: str | None = Header(default=None)):
    lang = x_lang or user.language
    if not idempotency_key or not (8 <= len(idempotency_key) <= 100):
        raise fail(422, "idempotency_required", lang)
    # Retry: wahi key dobara aaye to wahi request wapas, nayi nahi.
    existing = db.exec(select(Case).where(Case.user_id == user.id,
                                          Case.idempotency_key == idempotency_key)).first()
    if existing:
        response.status_code = 200
        return _view(existing, db, pick_lang(lang), full=True)
    if data.category not in CATEGORIES:
        raise fail(422, "category_invalid", lang)
    if data.province and data.province not in PROVINCES:
        raise fail(422, "province_invalid", lang)
    city, statement, summary = data.city.strip(), data.statement.strip(), data.summary.strip()
    if not city:
        raise fail(422, "city_required", lang)
    if len(statement) < 20:
        raise fail(422, "statement_short", lang)
    if not summary:
        raise fail(422, "summary_required", lang)
    if len(city) > 80 or len(statement) > 5000 or len(summary) > 3000:
        raise fail(422, "field_too_long", lang)
    for _ in range(5):  # tracking number takraye to dobara
        case = Case(tracking_no=_new_tracking(), user_id=user.id, category=data.category,
                    city=city, province=data.province, statement=statement, summary=summary,
                    safe_time=(data.safe_time or "")[:40] or None,
                    ai_used=data.ai_used, idempotency_key=idempotency_key,
                    child_review_status="pending" if data.category == "children" else "not_needed")
        db.add(case)
        try:
            db.commit()
            break
        except IntegrityError:
            db.rollback()
            again = db.exec(select(Case).where(Case.user_id == user.id,
                                               Case.idempotency_key == idempotency_key)).first()
            if again:  # do ek saath retry: doosra jeet gaya
                response.status_code = 200
                return _view(again, db, pick_lang(lang), full=True)
    else:
        raise fail(503, "field_too_long", lang)
    db.refresh(case)
    db.add(CaseEvent(request_id=case.id, event_type="saved"))
    db.commit()
    # Tracking number sirf commit ke BAAD wapas jata hai.
    response.status_code = 201
    return _view(case, db, pick_lang(lang), full=True)


@router.get("/requests")
def my_requests(user: User = Depends(current_user), db: Session = Depends(get_session),
                x_lang: str | None = Header(default=None)):
    rows = db.exec(select(Case).where(Case.user_id == user.id).order_by(Case.id.desc())).all()
    return {"requests": [_view(c, db, pick_lang(x_lang or user.language)) for c in rows]}


@router.get("/requests/{case_id}")
def one_request(case_id: int, user: User = Depends(current_user),
                db: Session = Depends(get_session), x_lang: str | None = Header(default=None)):
    lang = pick_lang(x_lang or user.language)
    return _view(_own_case(db, user, case_id, lang), db, lang, full=True)


@router.get("/requests/{case_id}/summary.txt")
def summary_download(case_id: int, user: User = Depends(current_user),
                     db: Session = Depends(get_session), x_lang: str | None = Header(default=None)):
    lang = pick_lang(x_lang or user.language)
    c = _own_case(db, user, case_id, lang)
    en = lang == "en"
    text = "\n".join([
        f"Insaf Dastak | {'Request summary' if en else 'Request ka summary'}",
        f"Tracking: {c.tracking_no}",
        f"{'Category' if en else 'Category'}: {_labels(lang)[c.category]}",
        f"{'City' if en else 'Shehar'}: {c.city}",
        f"{'Saved on' if en else 'Save hui'}: {c.created_at:%Y-%m-%d %H:%M} UTC",
        "",
        "User's statement (as written by the user):" if en else "User ka bayan (jaisa user ne likha):",
        c.statement,
        "",
        "Summary approved by the user:" if en else "User ka approve kiya hua summary:",
        c.summary,
        "",
        ("Note: this is the user's own statement. It does not decide that anyone is guilty or innocent, "
         "and it does not guarantee any outcome." if en else
         "Note: yeh user ka apna bayan hai. Is se kisi ka mujrim ya be-gunah hona tay nahi hota, "
         "aur kisi nateeje ki guarantee nahi."),
    ])
    return PlainTextResponse(text, headers={
        "Content-Disposition": f'attachment; filename="{c.tracking_no}.txt"'})


class ConsentIn(BaseModel):
    referral: bool


@router.put("/requests/{case_id}/consent")
def set_consent(case_id: int, data: ConsentIn, user: User = Depends(current_user),
                db: Session = Depends(get_session), x_lang: str | None = Header(default=None)):
    lang = pick_lang(x_lang or user.language)
    c = _own_case(db, user, case_id, lang)
    if c.status == "closed":
        raise fail(409, "request_closed", lang)
    if c.referral_consent != data.referral:
        c.referral_consent = data.referral
        if not data.referral:  # ijazat wapas: wakeel ka access foran band
            from .lawyers import revoke_active
            revoke_active(db, c, "consent_withdrawn")
        db.add(c)
        db.add(CaseEvent(request_id=c.id,
                         event_type="referral_consent_given" if data.referral else "referral_consent_withdrawn"))
        db.commit()
    return _view(c, db, lang, full=True)


@router.post("/requests/{case_id}/close")
def close_request(case_id: int, user: User = Depends(current_user),
                  db: Session = Depends(get_session), x_lang: str | None = Header(default=None)):
    lang = pick_lang(x_lang or user.language)
    c = _own_case(db, user, case_id, lang)
    if c.status != "closed":
        from .lawyers import revoke_active
        revoke_active(db, c, "request_closed")
        c.status = "closed"
        db.add(c)
        db.add(CaseEvent(request_id=c.id, event_type="closed"))
        db.add(AuditLog(actor_id=user.id, action="request_closed", detail=c.tracking_no))
        db.commit()
    return _view(c, db, lang, full=True)


def require_coordinator(user: User = Depends(current_user),
                        x_lang: str | None = Header(default=None)) -> User:
    if user.role not in ("coordinator", "admin", "super_admin"):
        raise fail(403, "forbidden", x_lang or user.language)
    return user


@router.get("/coord/queue")
def coordinator_queue(_: User = Depends(require_coordinator), db: Session = Depends(get_session)):
    """Unassigned queue. Sirf tracking, category, shehar aur intezar ke din; bayan nahi."""
    rows = db.exec(select(Case).where(Case.lawyer_status == "not_assigned",
                                      Case.status == "saved").order_by(Case.id)).all()
    now = utcnow()
    offered = {a.request_id for a in db.exec(select(Assignment).where(Assignment.status == "offered")).all()}
    items = [{"tracking_no": c.tracking_no, "offer_pending": c.id in offered, "category": c.category, "city": c.city,
              "days_waiting": (now - c.created_at).days,
              "overdue": (now - c.created_at).days >= settings.overdue_days,
              "referral_status": c.referral_status, "referral_consent": c.referral_consent,
              "child_review": c.child_review_status}
             for c in rows]
    return {"unassigned": items, "overdue_count": sum(1 for i in items if i["overdue"])}


def seed_official_contacts(db: Session):
    """Sirf wohi contacts jo official source se verify hue. Launch se pehle dobara check zaroori."""
    if db.exec(select(OfficialContact)).first():
        return
    db.add(OfficialContact(
        name="Ministry of Human Rights: toll-free helpline", phone="1099",
        note_roman_urdu="Insani huqooq ki khilaf-warzi par muft qanooni mashwara.",
        note_en="Free legal advice on human rights violations.", scope="national",
        source_url="https://mohr.gov.pk/ProjectDetail/YTY3Yjk0ZTItYTVkNS00ZGY2LWE3MGMtMGEwZDkxYjY1YWVm",
        verified_on="2026-10-23"))
    db.commit()
