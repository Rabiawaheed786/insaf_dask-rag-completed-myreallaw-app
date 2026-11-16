from datetime import timedelta

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.cli import make_admin
from app.db import engine
from app.main import app
from app.models import AuditLog, Case, Referral, User, utcnow
from tests.conftest import signup
from tests.test_requests import BODY, post


def make_role(email, role):
    with Session(engine) as db:
        u = db.exec(select(User).where(User.email == email)).one()
        u.role = role
        db.add(u)
        db.commit()


def staff(email="coord@example.com", role="coordinator"):
    c = TestClient(app)
    signup(c, email)
    make_role(email, role)
    return c


def case_for(client, consent=False):
    d = post(client).json()
    if consent:
        client.put(f"/api/requests/{d['id']}/consent", json={"referral": True})
    return d


def ref(coord, tn, key="ref-key-12345", **kw):
    body = {"target": "Free Legal Centre", "status": "attempted", **kw}
    return coord.post(f"/api/coord/requests/{tn}/referrals", json=body, headers={"Idempotency-Key": key})


def test_consent_user_only_and_default_off(client):
    signup(client, "one@example.com")
    d = case_for(client)
    assert d["referral_consent"] is False
    assert client.put(f"/api/requests/{d['id']}/consent", json={"referral": True}).json()["referral_consent"] is True
    assert client.put(f"/api/requests/{d['id']}/consent", json={"referral": False}).json()["referral_consent"] is False
    other = TestClient(app)
    signup(other, "two@example.com")
    assert other.put(f"/api/requests/{d['id']}/consent", json={"referral": True}).status_code == 404


def test_no_referral_without_consent(client):
    signup(client, "one@example.com")
    d = case_for(client)
    coord = staff()
    assert ref(coord, d["tracking_no"]).status_code == 409
    with Session(engine) as db:
        assert db.exec(select(Referral)).first() is None
        assert db.exec(select(Case)).one().referral_status == "not_sent"


def test_delivered_needs_ack_and_failed_needs_reason(client):
    signup(client, "one@example.com")
    d = case_for(client, consent=True)
    coord, tn = staff(), d["tracking_no"]
    assert ref(coord, tn, "k-delivered-1", status="delivered").status_code == 422
    assert ref(coord, tn, "k-failed-0001", status="failed").status_code == 422
    assert ref(coord, tn, "k-bad-status1", status="sent").status_code == 422
    assert client.get(f"/api/requests/{d['id']}").json()["referral_status"] == "not_sent"
    assert ref(coord, tn, "k-attempt-001").status_code == 201
    assert client.get(f"/api/requests/{d['id']}").json()["referral_status"] == "pending"
    assert ref(coord, tn, "k-delivered-2", status="delivered", ack_ref="CENTRE-REF-77").status_code == 201
    got = client.get(f"/api/requests/{d['id']}").json()
    assert got["referral_status"] == "delivered" and got["lawyer_status"] == "not_assigned"


def test_referral_retry_makes_no_duplicate(client):
    signup(client, "one@example.com")
    d = case_for(client, consent=True)
    coord = staff()
    a = ref(coord, d["tracking_no"], "same-key-1234")
    b = ref(coord, d["tracking_no"], "same-key-1234")
    assert a.status_code == 201 and b.status_code == 200
    assert a.json()["referral_id"] == b.json()["referral_id"]
    with Session(engine) as db:
        assert len(db.exec(select(Referral)).all()) == 1


def test_failed_referral_visible_to_user_but_reason_private(client):
    signup(client, "one@example.com")
    d = case_for(client, consent=True)
    coord = staff()
    ref(coord, d["tracking_no"], "k-failed-0002", status="failed", failed_reason="Fax line band, internal note")
    got = client.get(f"/api/requests/{d['id']}").json()
    assert got["referral_status"] == "failed" and "kamyab nahi hui" in got["next_action"]
    assert "internal note" not in client.get(f"/api/requests/{d['id']}").text
    assert "internal note" in coord.get(f"/api/coord/requests/{d['tracking_no']}").text


def test_only_staff_can_record_referrals_and_view(client):
    signup(client, "one@example.com")
    d = case_for(client, consent=True)
    assert ref(client, d["tracking_no"]).status_code == 403
    assert client.get(f"/api/coord/requests/{d['tracking_no']}").status_code == 403
    assert ref(TestClient(app), d["tracking_no"]).status_code == 401


def test_coordinator_sees_summary_only_with_consent_and_is_audited(client):
    signup(client, "one@example.com")
    no = case_for(client)
    coord = staff()
    v = coord.get(f"/api/coord/requests/{no['tracking_no']}").json()
    assert "summary" not in v and "statement" not in v
    yes = post(client, key="second-key-123").json()
    client.put(f"/api/requests/{yes['id']}/consent", json={"referral": True})
    v2 = coord.get(f"/api/coord/requests/{yes['tracking_no']}").json()
    assert v2["summary"] == BODY["summary"] and "statement" not in v2
    with Session(engine) as db:
        assert len(db.exec(select(AuditLog).where(AuditLog.action == "coordinator_viewed")).all()) == 2


def test_overdue_queue_and_alternatives(client):
    signup(client, "one@example.com")
    d = case_for(client)
    assert client.get(f"/api/requests/{d['id']}").json()["alternatives_suggested"] is False
    with Session(engine) as db:
        c = db.exec(select(Case)).one()
        c.created_at = utcnow() - timedelta(days=8)
        db.add(c)
        db.commit()
    coord = staff()
    q = coord.get("/api/coord/queue").json()
    assert q["overdue_count"] == 1 and q["unassigned"][0]["overdue"] is True
    got = client.get(f"/api/requests/{d['id']}").json()
    assert got["alternatives_suggested"] is True and "Intezar na karein" in got["next_action"]
    assert got["fallback_contacts"][0]["phone"] == "1099"


def test_close_removes_from_queue_and_blocks_referral(client):
    signup(client, "one@example.com")
    d = case_for(client, consent=True)
    coord = staff()
    other = TestClient(app)
    signup(other, "two@example.com")
    assert other.post(f"/api/requests/{d['id']}/close").status_code == 404
    assert client.post(f"/api/requests/{d['id']}/close").json()["status"] == "closed"
    assert client.post(f"/api/requests/{d['id']}/close").status_code == 200  # dobara bhi theek
    assert coord.get("/api/coord/queue").json()["unassigned"] == []
    assert ref(coord, d["tracking_no"]).status_code == 409
    assert client.put(f"/api/requests/{d['id']}/consent", json={"referral": False}).status_code == 409


def test_admin_contacts_need_https_source_and_date(client):
    signup(client, "one@example.com")
    good = {"name": "Sindh Helpline", "phone": "0800-12345", "scope": "sindh",
            "source_url": "https://example.gov.pk/helpline", "verified_on": "2026-10-20"}
    assert client.post("/api/admin/contacts", json=good).status_code == 403
    make_role("one@example.com", "admin")
    assert client.post("/api/admin/contacts", json={**good, "source_url": "http://x.pk"}).status_code == 422
    assert client.post("/api/admin/contacts", json={**good, "verified_on": "kal"}).status_code == 422
    assert client.post("/api/admin/contacts", json={**good, "scope": "mars"}).status_code == 422
    assert client.post("/api/admin/contacts", json=good).status_code == 201
    phones = lambda p: [c["phone"] for c in client.get(f"/api/official-contacts?province={p}").json()["contacts"]]
    assert "0800-12345" in phones("sindh") and "0800-12345" not in phones("punjab")
    assert "1099" in phones("punjab")


def test_admin_roles_and_cli(client):
    signup(client, "boss@example.com")
    signup(TestClient(app), "worker@example.com")
    assert make_admin("boss@example.com") is True and make_admin("nobody@example.com") is False
    assert client.put("/api/admin/users/role", json={"email": "worker@example.com", "role": "lawyer"}).status_code == 422
    assert client.put("/api/admin/users/role", json={"email": "ghost@example.com", "role": "coordinator"}).status_code == 404
    assert client.put("/api/admin/users/role", json={"email": "worker@example.com", "role": "coordinator"}).status_code == 200
    w = TestClient(app)
    w.post("/api/auth/login", json={"email": "worker@example.com", "password": "strongpass1"})
    assert w.get("/api/coord/queue").status_code == 200


def test_consent_and_referrals_survive_restart(client):
    signup(client, "one@example.com")
    d = case_for(client, consent=True)
    ref(staff(), d["tracking_no"], "k-restart-001", status="delivered", ack_ref="REF-12345")
    engine.dispose()
    with TestClient(app) as fresh:
        fresh.post("/api/auth/login", json={"email": "one@example.com", "password": "strongpass1"})
        got = fresh.get(f"/api/requests/{d['id']}").json()
        assert got["referral_consent"] is True and got["referral_status"] == "delivered"
        assert [r["status"] for r in got["referrals"]] == ["delivered"]
