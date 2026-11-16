"""Wakeel: arzi, verification, offer, accept/decline, access. Access har request par taza check hota hai."""
from datetime import timedelta

from fastapi import APIRouter, Depends, Header, Response
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from .auth import current_user
from .cases import _labels, require_coordinator
from .db import get_session
from .messages import fail, pick_lang
from .models import (Assignment, AuditLog, AvailabilitySlot, Case, CaseEvent, LawyerProfile, User, utcnow)
from .ops import require_admin

router = APIRouter(prefix="/api", tags=["lawyers"])
ACTIVE = ("offered", "accepted")


# ---------- madadgar ----------
def expire_stale(db: Session):
    rows = db.exec(select(Assignment).where(Assignment.status == "offered",
                                            Assignment.expires_at < utcnow())).all()
    for a in rows:
        a.status = "expired"
        db.add(a)
        db.add(CaseEvent(request_id=a.request_id, event_type="lawyer_offer_expired"))
    if rows:
        db.commit()


def revoke_active(db: Session, case: Case, reason: str, actor_id: int | None = None):
    """Request ke saare active offers/wakeel ka access band. Commit caller karta hai."""
    rows = db.exec(select(Assignment).where(Assignment.request_id == case.id,
                                            Assignment.status.in_(ACTIVE))).all()
    for a in rows:
        a.status, a.revoked_at, a.revoke_reason = "revoked", utcnow(), reason
        db.add(a)
        db.add(CaseEvent(request_id=case.id, event_type="lawyer_unassigned"))
        db.add(AuditLog(actor_id=actor_id, action="assignment_revoked", detail=f"{case.tracking_no}:{reason}"))
    if rows and case.lawyer_status == "accepted":
        case.lawyer_status = "not_assigned"
        db.add(case)
    if rows:  # is request ke booked slots wapas khali: wakeel hat gaya
        for s in db.exec(select(AvailabilitySlot).where(AvailabilitySlot.booked_request_id == case.id,
                                                        AvailabilitySlot.status == "booked")).all():
            s.status, s.booked_request_id, s.booked_at = "open", None, None
            db.add(s)


def require_lawyer(user: User = Depends(current_user), db: Session = Depends(get_session),
                   x_lang: str | None = Header(default=None)) -> LawyerProfile:
    p = db.exec(select(LawyerProfile).where(LawyerProfile.user_id == user.id)).first()
    # role puraani ho sakti hai (jaise suspend ke baad), is liye profile ka status har baar dekha jata hai
    if user.role != "lawyer" or not p or p.verification_status != "verified":
        raise fail(403, "not_a_lawyer", x_lang or user.language)
    return p


def _profile_view(p: LawyerProfile) -> dict:
    return {"id": p.id, "bar_council": p.bar_council, "licence_no": p.licence_no, "city": p.city,
            "status": p.verification_status}


# ---------- wakeel ki arzi ----------
class ApplyIn(BaseModel):
    bar_council: str
    licence_no: str
    city: str


@router.post("/lawyer/apply")
def apply(data: ApplyIn, response: Response, user: User = Depends(current_user),
          db: Session = Depends(get_session), x_lang: str | None = Header(default=None)):
    lang = x_lang or user.language
    if user.role not in ("user", "lawyer"):
        raise fail(403, "role_not_allowed", lang)
    old = db.exec(select(LawyerProfile).where(LawyerProfile.user_id == user.id)).first()
    if old:  # dobara arzi: wahi profile, nayi nahi
        return _profile_view(old)
    bc, lic, city = data.bar_council.strip(), data.licence_no.strip().upper(), data.city.strip()
    if not (3 <= len(bc) <= 120 and 3 <= len(lic) <= 60 and 1 <= len(city) <= 80):
        raise fail(422, "lawyer_invalid", lang)
    p = LawyerProfile(user_id=user.id, bar_council=bc, licence_no=lic, city=city)
    db.add(p)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise fail(409, "licence_taken", lang) from None
    db.add(AuditLog(actor_id=user.id, action="lawyer_applied"))
    db.commit()
    db.refresh(p)
    response.status_code = 201
    return _profile_view(p)


@router.get("/lawyer/me")
def lawyer_me(user: User = Depends(current_user), db: Session = Depends(get_session),
              x_lang: str | None = Header(default=None)):
    p = db.exec(select(LawyerProfile).where(LawyerProfile.user_id == user.id)).first()
    if not p:
        raise fail(404, "lawyer_not_found", x_lang or user.language)
    return _profile_view(p)  # source_note aur wajah yahan nahi


# ---------- admin: verification ----------
@router.get("/admin/lawyers")
def admin_lawyers(status: str | None = None, _: User = Depends(require_admin),
                  db: Session = Depends(get_session)):
    q = select(LawyerProfile).order_by(LawyerProfile.id)
    if status:
        q = q.where(LawyerProfile.verification_status == status)
    out = []
    for p in db.exec(q).all():
        u = db.get(User, p.user_id)
        out.append({**_profile_view(p), "display_name": u.display_name, "email": u.email,
                    "identity_checked": p.identity_checked, "registration_checked": p.registration_checked,
                    "source_note": p.source_note, "decision_reason": p.decision_reason})
    return {"lawyers": out}


class VerifyIn(BaseModel):
    identity_checked: bool
    registration_checked: bool
    source_note: str


class ReasonIn(BaseModel):
    reason: str


def _profile_or_404(db, pid, lang) -> LawyerProfile:
    p = db.get(LawyerProfile, pid)
    if not p:
        raise fail(404, "lawyer_not_found", lang)
    return p


@router.post("/admin/lawyers/{pid}/verify")
def verify(pid: int, data: VerifyIn, admin: User = Depends(require_admin),
           db: Session = Depends(get_session), x_lang: str | None = Header(default=None)):
    lang = x_lang or admin.language
    p = _profile_or_404(db, pid, lang)
    if not (data.identity_checked and data.registration_checked and len(data.source_note.strip()) >= 10):
        raise fail(422, "verification_incomplete", lang)
    p.verification_status, p.identity_checked, p.registration_checked = "verified", True, True
    p.source_note, p.decision_reason = data.source_note.strip()[:300], None
    p.decided_by, p.decided_at = admin.id, utcnow()
    u = db.get(User, p.user_id)
    u.role = "lawyer"
    db.add(p)
    db.add(u)
    db.add(AuditLog(actor_id=admin.id, action="lawyer_verified", detail=str(p.id)))
    db.commit()
    return _profile_view(p)


@router.post("/admin/lawyers/{pid}/reject")
def reject(pid: int, data: ReasonIn, admin: User = Depends(require_admin),
           db: Session = Depends(get_session), x_lang: str | None = Header(default=None)):
    lang = x_lang or admin.language
    p = _profile_or_404(db, pid, lang)
    if len(data.reason.strip()) < 3:
        raise fail(422, "reason_required", lang)
    p.verification_status, p.decision_reason = "rejected", data.reason.strip()[:300]
    p.decided_by, p.decided_at = admin.id, utcnow()
    db.add(p)
    db.add(AuditLog(actor_id=admin.id, action="lawyer_rejected", detail=str(p.id)))
    db.commit()
    return _profile_view(p)


@router.post("/admin/lawyers/{pid}/suspend")
def suspend(pid: int, data: ReasonIn, admin: User = Depends(require_admin),
            db: Session = Depends(get_session), x_lang: str | None = Header(default=None)):
    lang = x_lang or admin.language
    p = _profile_or_404(db, pid, lang)
    if len(data.reason.strip()) < 3:
        raise fail(422, "reason_required", lang)
    p.verification_status, p.decision_reason = "suspended", data.reason.strip()[:300]
    p.decided_by, p.decided_at = admin.id, utcnow()
    u = db.get(User, p.user_id)
    if u.role == "lawyer":
        u.role = "user"
        db.add(u)
    db.add(p)
    # is wakeel ke saare active cases foran wapas, access band
    for a in db.exec(select(Assignment).where(Assignment.lawyer_profile_id == p.id,
                                              Assignment.status.in_(ACTIVE))).all():
        revoke_active(db, db.get(Case, a.request_id), "lawyer_suspended", admin.id)
    db.add(AuditLog(actor_id=admin.id, action="lawyer_suspended", detail=str(p.id)))
    db.commit()
    return _profile_view(p)


# ---------- coordinator: offer ----------
@router.get("/coord/lawyers")
def coord_lawyers(_: User = Depends(require_coordinator), db: Session = Depends(get_session)):
    out = []
    for p in db.exec(select(LawyerProfile).where(LawyerProfile.verification_status == "verified")).all():
        u = db.get(User, p.user_id)
        n = len(db.exec(select(Assignment).where(Assignment.lawyer_profile_id == p.id,
                                                 Assignment.status.in_(ACTIVE))).all())
        out.append({"lawyer_id": p.id, "display_name": u.display_name, "city": p.city,
                    "bar_council": p.bar_council, "active_cases": n})  # email nahi
    return {"lawyers": out}


class AssignIn(BaseModel):
    lawyer_id: int
    expires_in_days: int = 3


@router.post("/coord/requests/{tracking_no}/assign", status_code=201)
def assign(tracking_no: str, data: AssignIn, coord: User = Depends(require_coordinator),
           db: Session = Depends(get_session), x_lang: str | None = Header(default=None)):
    lang = x_lang or coord.language
    expire_stale(db)
    c = db.exec(select(Case).where(Case.tracking_no == tracking_no.upper())).first()
    if not c:
        raise fail(404, "not_found", lang)
    p = db.get(LawyerProfile, data.lawyer_id)
    if not p:
        raise fail(404, "lawyer_not_found", lang)
    if p.verification_status != "verified":
        raise fail(409, "lawyer_not_verified", lang)
    if c.status == "closed":
        raise fail(409, "request_closed", lang)
    if c.child_review_status == "pending":  # bachon ka masla: pehle reviewer, phir wakeel
        raise fail(409, "child_review_pending", lang)
    if not c.referral_consent:  # user ki ijazat ke bina wakeel ko kuch nahi jata
        raise fail(409, "referral_needs_consent", lang)
    if db.exec(select(Assignment).where(Assignment.request_id == c.id, Assignment.status.in_(ACTIVE))).first():
        raise fail(409, "assignment_exists", lang)
    days = min(max(data.expires_in_days, 1), 14)
    a = Assignment(request_id=c.id, lawyer_profile_id=p.id, offered_by=coord.id,
                   expires_at=utcnow() + timedelta(days=days))
    db.add(a)
    db.add(CaseEvent(request_id=c.id, event_type="lawyer_offered"))
    db.add(AuditLog(actor_id=coord.id, action="assignment_offered", detail=c.tracking_no))
    db.commit()
    db.refresh(a)
    return {"assignment_id": a.id, "status": a.status, "expires_at": a.expires_at.isoformat()}


@router.post("/coord/assignments/{aid}/revoke")
def revoke(aid: int, coord: User = Depends(require_coordinator), db: Session = Depends(get_session),
           x_lang: str | None = Header(default=None)):
    lang = x_lang or coord.language
    a = db.get(Assignment, aid)
    if not a:
        raise fail(404, "not_found", lang)
    if a.status not in ACTIVE:
        raise fail(409, "not_pending", lang)
    revoke_active(db, db.get(Case, a.request_id), "coordinator_revoked", coord.id)
    db.commit()
    return {"assignment_id": a.id, "status": "revoked"}


# ---------- wakeel: offers aur cases ----------
@router.get("/lawyer/offers")
def my_offers(p: LawyerProfile = Depends(require_lawyer), db: Session = Depends(get_session),
              user: User = Depends(current_user), x_lang: str | None = Header(default=None)):
    expire_stale(db)
    lang = pick_lang(x_lang or user.language)
    out = []
    for a in db.exec(select(Assignment).where(Assignment.lawyer_profile_id == p.id,
                                              Assignment.status == "offered")).all():
        c = db.get(Case, a.request_id)  # qabool karne se pehle sirf mukhtasar tafseel, bayan nahi
        out.append({"offer_id": a.id, "tracking_no": c.tracking_no, "category_label": _labels(lang)[c.category],
                    "city": c.city, "province": c.province, "expires_at": a.expires_at.isoformat()})
    return {"offers": out}


def _my_offer(db, p, aid, lang) -> Assignment:
    expire_stale(db)
    a = db.get(Assignment, aid)
    if not a or a.lawyer_profile_id != p.id:
        raise fail(404, "not_found", lang)
    return a


@router.post("/lawyer/offers/{aid}/accept")
def accept(aid: int, p: LawyerProfile = Depends(require_lawyer), db: Session = Depends(get_session),
           user: User = Depends(current_user), x_lang: str | None = Header(default=None)):
    lang = x_lang or user.language
    a = _my_offer(db, p, aid, lang)
    if a.status == "expired":
        raise fail(409, "offer_expired", lang)
    c = db.get(Case, a.request_id)
    if a.status != "offered" or c.status == "closed" or not c.referral_consent:
        raise fail(409, "not_pending", lang)
    a.status, a.responded_at = "accepted", utcnow()
    c.lawyer_status = "accepted"
    db.add(a)
    db.add(c)
    db.add(CaseEvent(request_id=c.id, event_type="lawyer_accepted"))
    db.add(AuditLog(actor_id=user.id, action="assignment_accepted", detail=c.tracking_no))
    db.commit()
    return {"assignment_id": a.id, "status": "accepted", "tracking_no": c.tracking_no}


@router.post("/lawyer/offers/{aid}/decline")
def decline(aid: int, p: LawyerProfile = Depends(require_lawyer), db: Session = Depends(get_session),
            user: User = Depends(current_user), x_lang: str | None = Header(default=None)):
    lang = x_lang or user.language
    a = _my_offer(db, p, aid, lang)
    if a.status != "offered":
        raise fail(409, "not_pending", lang)
    a.status, a.responded_at = "declined", utcnow()
    db.add(a)
    db.add(CaseEvent(request_id=a.request_id, event_type="lawyer_declined"))
    db.add(AuditLog(actor_id=user.id, action="assignment_declined", detail=str(a.id)))
    db.commit()
    return {"assignment_id": a.id, "status": "declined"}


def _accepted_case(db, p, tracking_no, lang) -> Case:
    c = db.exec(select(Case).where(Case.tracking_no == tracking_no.upper())).first()
    ok = c and db.exec(select(Assignment).where(Assignment.request_id == c.id,
                                                Assignment.lawyer_profile_id == p.id,
                                                Assignment.status == "accepted")).first()
    if not ok or c.status == "closed" or not c.referral_consent:
        raise fail(404, "not_found", lang)  # na-manzoor, ya peeche hata diya gaya: pata hi na chale
    return c


@router.get("/lawyer/cases")
def my_cases(p: LawyerProfile = Depends(require_lawyer), db: Session = Depends(get_session),
             user: User = Depends(current_user), x_lang: str | None = Header(default=None)):
    lang = pick_lang(x_lang or user.language)
    rows = db.exec(select(Assignment).where(Assignment.lawyer_profile_id == p.id,
                                            Assignment.status == "accepted")).all()
    out = []
    for a in rows:
        c = db.get(Case, a.request_id)
        if c.status != "closed" and c.referral_consent:
            out.append({"tracking_no": c.tracking_no, "category_label": _labels(lang)[c.category], "city": c.city})
    return {"cases": out}


@router.get("/lawyer/cases/{tracking_no}")
def my_case(tracking_no: str, p: LawyerProfile = Depends(require_lawyer), db: Session = Depends(get_session),
            user: User = Depends(current_user), x_lang: str | None = Header(default=None)):
    lang = pick_lang(x_lang or user.language)
    c = _accepted_case(db, p, tracking_no, lang)
    db.add(AuditLog(actor_id=user.id, action="lawyer_viewed", detail=c.tracking_no))
    db.commit()
    return {"tracking_no": c.tracking_no, "category_label": _labels(lang)[c.category], "city": c.city,
            "province": c.province, "created_at": c.created_at.isoformat(), "safe_time": c.safe_time,
            "statement": c.statement, "summary": c.summary}
