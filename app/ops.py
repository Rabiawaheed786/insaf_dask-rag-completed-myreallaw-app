"""Coordinator aur admin ke kaam: referral record karna, verified contacts, roles."""
from datetime import date

from fastapi import APIRouter, Depends, Header, Response
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, func, select

from .auth import current_user
from .cases import PROVINCES, _labels, require_coordinator
from .db import get_session
from .messages import fail, pick_lang
from .models import (Assignment, AuditLog, Case, CaseEvent, KnowledgeBase, OfficialContact, Referral, User, utcnow)
from .rbac import ADMIN_ROLES, SUPER_ADMIN, USER, require_super_admin

router = APIRouter(prefix="/api", tags=["coordinator-admin"])
STATUS_MAP = {"attempted": "pending", "delivered": "delivered", "failed": "failed"}


def require_admin(user: User = Depends(current_user), x_lang: str | None = Header(default=None)) -> User:
    if user.role not in ADMIN_ROLES:
        raise fail(403, "forbidden", x_lang or user.language)
    return user


class ReferralIn(BaseModel):
    target: str
    status: str
    ack_ref: str | None = None
    failed_reason: str | None = None


def _case_by_tracking(db: Session, tracking_no: str, lang) -> Case:
    c = db.exec(select(Case).where(Case.tracking_no == tracking_no.upper())).first()
    if not c:
        raise fail(404, "not_found", lang)
    return c


@router.get("/coord/requests/{tracking_no}")
def coord_view(tracking_no: str, coord: User = Depends(require_coordinator),
               db: Session = Depends(get_session), x_lang: str | None = Header(default=None)):
    lang = pick_lang(x_lang or coord.language)
    c = _case_by_tracking(db, tracking_no, lang)
    out = {"tracking_no": c.tracking_no, "category": c.category,
           "category_label": _labels(lang)[c.category], "city": c.city, "province": c.province,
           "status": c.status, "referral_status": c.referral_status,
           "lawyer_status": c.lawyer_status, "child_review": c.child_review_status,
           "referral_consent": c.referral_consent,
           "referrals": [{"target": r.target, "status": r.status, "ack_ref": r.ack_ref,
                          "failed_reason": r.failed_reason, "at": r.created_at.isoformat()}
                         for r in db.exec(select(Referral).where(Referral.request_id == c.id)
                                          .order_by(Referral.id)).all()]}
    act = db.exec(select(Assignment).where(Assignment.request_id == c.id,
                                           Assignment.status.in_(("offered", "accepted")))).first()
    out["assignment"] = {"id": act.id, "status": act.status, "expires_at": act.expires_at.isoformat()} if act else None
    if c.referral_consent:  # summary tabhi, jab user ne ijazat di; poora bayan kabhi nahi
        out["summary"] = c.summary
    db.add(AuditLog(actor_id=coord.id, action="coordinator_viewed", detail=c.tracking_no))
    db.commit()
    return out


@router.post("/coord/requests/{tracking_no}/referrals")
def record_referral(tracking_no: str, data: ReferralIn, response: Response,
                    coord: User = Depends(require_coordinator), db: Session = Depends(get_session),
                    idempotency_key: str | None = Header(default=None),
                    x_lang: str | None = Header(default=None)):
    lang = x_lang or coord.language
    if not idempotency_key or not (8 <= len(idempotency_key) <= 100):
        raise fail(422, "idempotency_required", lang)
    c = _case_by_tracking(db, tracking_no, lang)
    old = db.exec(select(Referral).where(Referral.request_id == c.id,
                                         Referral.idempotency_key == idempotency_key)).first()
    if old:  # retry: wahi referral, duplicate nahi
        return {"referral_id": old.id, "status": old.status, "case_referral_status": c.referral_status}
    target = data.target.strip()
    if not (1 <= len(target) <= 120) or data.status not in STATUS_MAP:
        raise fail(422, "referral_invalid", lang)
    if c.status == "closed":
        raise fail(409, "request_closed", lang)
    if c.child_review_status == "pending":
        raise fail(409, "child_review_pending", lang)
    if not c.referral_consent:  # user ki ijazat ke bagair koi referral record nahi hota
        raise fail(409, "referral_needs_consent", lang)
    ack = (data.ack_ref or "").strip()
    reason = (data.failed_reason or "").strip()
    if data.status == "delivered" and len(ack) < 3:
        raise fail(422, "referral_needs_ack", lang)
    if data.status == "failed" and not reason:
        raise fail(422, "referral_needs_reason", lang)
    r = Referral(request_id=c.id, target=target, status=data.status, ack_ref=ack[:120] or None,
                 failed_reason=reason[:300] or None, idempotency_key=idempotency_key,
                 created_by=coord.id)
    db.add(r)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        old = db.exec(select(Referral).where(Referral.request_id == c.id,
                                             Referral.idempotency_key == idempotency_key)).one()
        return {"referral_id": old.id, "status": old.status, "case_referral_status": c.referral_status}
    c.referral_status = STATUS_MAP[data.status]
    db.add(c)
    db.add(CaseEvent(request_id=c.id, event_type=f"referral_{data.status}"))
    db.add(AuditLog(actor_id=coord.id, action=f"referral_{data.status}", detail=c.tracking_no))
    db.commit()
    response.status_code = 201
    return {"referral_id": r.id, "status": r.status, "case_referral_status": c.referral_status}


class ContactIn(BaseModel):
    name: str
    phone: str
    scope: str = "national"
    source_url: str
    verified_on: str
    note_roman_urdu: str = ""
    note_en: str = ""
    emergency: bool = False


@router.post("/admin/contacts", status_code=201)
def add_contact(data: ContactIn, admin: User = Depends(require_admin),
                db: Session = Depends(get_session), x_lang: str | None = Header(default=None)):
    lang = x_lang or admin.language
    try:
        date.fromisoformat(data.verified_on)
        good_date = True
    except ValueError:
        good_date = False
    if (not data.name.strip() or not data.phone.strip() or not good_date
            or not data.source_url.startswith("https://")
            or data.scope not in ["national", *PROVINCES]):
        raise fail(422, "contact_invalid", lang)
    c = OfficialContact(name=data.name.strip(), phone=data.phone.strip(), scope=data.scope,
                        source_url=data.source_url, verified_on=data.verified_on, emergency=data.emergency,
                        note_roman_urdu=data.note_roman_urdu[:300], note_en=data.note_en[:300])
    db.add(c)
    db.add(AuditLog(actor_id=admin.id, action="contact_added", detail=c.phone))
    db.commit()
    db.refresh(c)
    return {"id": c.id, "name": c.name, "phone": c.phone, "scope": c.scope,
            "source_url": c.source_url, "verified_on": c.verified_on}


class RoleIn(BaseModel):
    email: str
    role: str


@router.put("/admin/users/role")
def set_role(data: RoleIn, admin: User = Depends(require_admin),
             db: Session = Depends(get_session), x_lang: str | None = Header(default=None)):
    lang = x_lang or admin.language
    # 'lawyer' abhi nahi: wakeel ko pehle verification ke raaste se guzarna hoga (Phase 5).
    if data.role not in ("user", "coordinator", "admin"):
        raise fail(422, "role_invalid", lang)
    u = db.exec(select(User).where(User.email == data.email.strip().lower())).first()
    if not u:
        raise fail(404, "user_not_found", lang)
    u.role = data.role
    db.add(u)
    db.add(AuditLog(actor_id=admin.id, action=f"role_set_{data.role}", detail=str(u.id)))
    db.commit()
    return {"email": u.email, "role": u.role}


class SuperRoleIn(BaseModel):
    role: str


@router.get("/admin/users")
def list_users(_: User = Depends(require_super_admin), db: Session = Depends(get_session)):
    """Super admin panel: system-wide ginti aur har user ka role/status."""
    rows = db.exec(select(User).order_by(User.id)).all()
    kbs = db.exec(select(func.count()).select_from(KnowledgeBase)).one()
    queries = db.exec(select(func.count()).select_from(AuditLog)
                      .where(AuditLog.action.in_(("kb_chat", "rag_ask")))).one()
    return {"stats": {"users": len(rows), "knowledge_bases": kbs, "queries": queries},
            "users": [{"id": u.id, "display_name": u.display_name, "email": u.email, "role": u.role,
                       "status": "locked" if u.locked_until and u.locked_until > utcnow() else "active",
                       "created_at": u.created_at.isoformat()} for u in rows]}


@router.patch("/admin/users/{user_id}/role")
def set_user_role(user_id: int, data: SuperRoleIn, admin: User = Depends(require_super_admin),
                  db: Session = Depends(get_session), x_lang: str | None = Header(default=None)):
    """Sirf user <-> super_admin. Apne aap ko demote karna band hai (panel se lockout na ho)."""
    lang = x_lang or admin.language
    if data.role not in (USER, SUPER_ADMIN):
        raise fail(422, "role_invalid", lang)
    u = db.get(User, user_id)
    if not u:
        raise fail(404, "user_not_found", lang)
    if u.id == admin.id and data.role != SUPER_ADMIN:
        raise fail(409, "cannot_demote_self", lang)
    u.role = data.role
    db.add(u)
    db.add(AuditLog(actor_id=admin.id, action=f"role_set_{data.role}", detail=str(u.id)))
    db.commit()
    return {"id": u.id, "email": u.email, "role": u.role}


@router.get("/admin/audit-logs")
def audit_logs(_: User = Depends(require_super_admin), db: Session = Depends(get_session), limit: int = 60):
    limit = max(1, min(limit, 200))
    rows = db.exec(select(AuditLog).order_by(AuditLog.id.desc()).limit(limit)).all()
    actors = {u.id: u.email for u in db.exec(select(User)).all()}
    return {"logs": [{"id": a.id, "actor": actors.get(a.actor_id, "system"), "action": a.action,
                      "at": a.at.isoformat()} for a in rows]}


class ChildReviewIn(BaseModel):
    decision: str
    note: str


@router.post("/admin/requests/{tracking_no}/child-review")
def child_review(tracking_no: str, data: ChildReviewIn, admin: User = Depends(require_admin),
                 db: Session = Depends(get_session), x_lang: str | None = Header(default=None)):
    """Bachon ke masle ka review. Admin yahan darj karta hai ke tarbiyat yafta reviewer ne dekh liya (note zaroori)."""
    lang = x_lang or admin.language
    c = _case_by_tracking(db, tracking_no, lang)
    if c.category != "children" or data.decision not in ("cleared", "pending") or len(data.note.strip()) < 10:
        raise fail(422, "review_invalid", lang)
    c.child_review_status, c.child_review_note, c.child_review_by = data.decision, data.note.strip()[:300], admin.id
    db.add(c)
    db.add(CaseEvent(request_id=c.id, event_type=f"child_review_{data.decision}"))
    db.add(AuditLog(actor_id=admin.id, action=f"child_review_{data.decision}", detail=c.tracking_no))
    db.commit()
    return {"tracking_no": c.tracking_no, "child_review": c.child_review_status}
