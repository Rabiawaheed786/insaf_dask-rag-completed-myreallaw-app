"""Coordinator ki daily aur weekly reports. Sirf ginti aur tracking number: bayan, summary, email nahi."""
from datetime import timedelta

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from .cases import require_coordinator
from .config import settings
from .db import get_session
from .models import Assignment, Case, CaseEvent, LawyerProfile, User, utcnow

router = APIRouter(prefix="/api/coord/reports", tags=["reports"])


def _open_unassigned(db: Session):
    return db.exec(select(Case).where(Case.status == "saved", Case.lawyer_status == "not_assigned")
                   .order_by(Case.id)).all()


@router.get("/daily")
def daily(_: User = Depends(require_coordinator), db: Session = Depends(get_session)):
    now = utcnow()
    offered = {a.request_id for a in db.exec(select(Assignment).where(Assignment.status == "offered")).all()}
    items = [{"tracking_no": c.tracking_no, "category": c.category, "city": c.city,
              "days_waiting": (now - c.created_at).days,
              "overdue": (now - c.created_at).days >= settings.overdue_days,
              "referral_consent": c.referral_consent, "offer_pending": c.id in offered,
              "child_review": c.child_review_status}
             for c in _open_unassigned(db)]
    return {"date": now.date().isoformat(), "unassigned_count": len(items),
            "overdue_count": sum(1 for i in items if i["overdue"]), "unassigned": items}


@router.get("/weekly")
def weekly(_: User = Depends(require_coordinator), db: Session = Depends(get_session)):
    now = utcnow()
    since = now - timedelta(days=7)
    pending = _open_unassigned(db)
    by_cat: dict[str, int] = {}
    for c in pending:
        by_cat[c.category] = by_cat.get(c.category, 0) + 1
    open_cases = db.exec(select(Case).where(Case.status == "saved")).all()
    refs: dict[str, int] = {}
    for c in open_cases:
        refs[c.referral_status] = refs.get(c.referral_status, 0) + 1

    def events(kind: str) -> int:
        return len(db.exec(select(CaseEvent).where(CaseEvent.event_type == kind, CaseEvent.at > since)).all())

    workload = []
    for p in db.exec(select(LawyerProfile).where(LawyerProfile.verification_status == "verified")).all():
        u = db.get(User, p.user_id)
        n = len(db.exec(select(Assignment).where(Assignment.lawyer_profile_id == p.id,
                                                 Assignment.status.in_(("offered", "accepted")))).all())
        workload.append({"lawyer_id": p.id, "display_name": u.display_name, "active_cases": n})
    return {"from": since.date().isoformat(), "to": now.date().isoformat(),
            "pending_requests": len(pending), "pending_by_category": by_cat,
            "new_this_week": len(db.exec(select(Case).where(Case.created_at > since)).all()),
            "accepted_this_week": events("lawyer_accepted"), "closed_this_week": events("closed"),
            "referrals_open_requests": refs, "lawyer_workload": workload}
