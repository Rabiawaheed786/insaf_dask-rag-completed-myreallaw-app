from datetime import timedelta

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.db import engine
from app.main import app
from app.models import Assignment, AuditLog, Case, LawyerProfile, User, utcnow
from tests.conftest import signup
from tests.test_phase3 import case_for, make_role, staff
from tests.test_requests import post

VERIFY = {"identity_checked": True, "registration_checked": True,
          "source_note": "Bar Council register checked online, video call done"}


def lawyer_applied(email="lawyer@example.com", licence="PB-12345"):
    c = TestClient(app)
    signup(c, email)
    r = c.post("/api/lawyer/apply", json={"bar_council": "Punjab Bar Council", "licence_no": licence, "city": "Lahore"})
    return c, r.json()["id"]


def admin_client():
    return staff("admin@example.com", "admin")


def verified_lawyer(admin, email="lawyer@example.com", licence="PB-12345"):
    c, pid = lawyer_applied(email, licence)
    assert admin.post(f"/api/admin/lawyers/{pid}/verify", json=VERIFY).status_code == 200
    return c, pid


def offer(coord, tn, pid, days=3):
    return coord.post(f"/api/coord/requests/{tn}/assign", json={"lawyer_id": pid, "expires_in_days": days})


def setup_offer(client):
    """user + consent wali request + verified lawyer + offer. Wapas: user, case, lawyer client, pid, coord, offer_id"""
    signup(client, "user@example.com")
    d = case_for(client, consent=True)
    coord, admin = staff(), admin_client()
    lc, pid = verified_lawyer(admin)
    aid = offer(coord, d["tracking_no"], pid).json()["assignment_id"]
    return d, lc, pid, coord, aid, admin


def test_signup_alone_gives_no_lawyer_access(client):
    lc, pid = lawyer_applied()
    assert lc.get("/api/lawyer/me").json()["status"] == "pending"
    assert lc.get("/api/lawyer/offers").status_code == 403
    assert lc.get("/api/lawyer/cases").status_code == 403
    assert lc.post("/api/lawyer/apply", json={"bar_council": "X Bar", "licence_no": "ZZ-1", "city": "A"}).json()["id"] == pid  # dobara arzi: wahi profile


def test_duplicate_licence_and_validation(client):
    lawyer_applied()
    other = TestClient(app)
    signup(other, "second@example.com")
    r = other.post("/api/lawyer/apply", json={"bar_council": "Punjab Bar Council", "licence_no": "pb-12345", "city": "Lahore"})
    assert r.status_code == 409
    assert other.post("/api/lawyer/apply", json={"bar_council": "x", "licence_no": "1", "city": ""}).status_code == 422
    assert TestClient(app).post("/api/lawyer/apply", json={}).status_code in (401, 422)


def test_verification_needs_admin_both_checks_and_note(client):
    lc, pid = lawyer_applied()
    coord, admin = staff(), admin_client()
    assert coord.post(f"/api/admin/lawyers/{pid}/verify", json=VERIFY).status_code == 403
    assert lc.post(f"/api/admin/lawyers/{pid}/verify", json=VERIFY).status_code == 403
    for bad in ({**VERIFY, "identity_checked": False}, {**VERIFY, "registration_checked": False}, {**VERIFY, "source_note": "short"}):
        assert admin.post(f"/api/admin/lawyers/{pid}/verify", json=bad).status_code == 422
    assert lc.get("/api/lawyer/offers").status_code == 403
    assert admin.post(f"/api/admin/lawyers/{pid}/verify", json=VERIFY).status_code == 200
    assert lc.get("/api/lawyer/offers").status_code == 200


def test_rejected_lawyer_has_no_access_and_reason_is_private(client):
    lc, pid = lawyer_applied()
    admin = admin_client()
    assert admin.post(f"/api/admin/lawyers/{pid}/reject", json={"reason": "Licence record not found"}).status_code == 200
    assert lc.get("/api/lawyer/offers").status_code == 403
    assert "Licence record" not in lc.get("/api/lawyer/me").text
    assert "Licence record" in admin.get("/api/admin/lawyers?status=rejected").text


def test_assign_needs_consent_verified_lawyer_and_open_request(client):
    signup(client, "user@example.com")
    no_consent = case_for(client)
    coord, admin = staff(), admin_client()
    _, pending_pid = lawyer_applied("pending@example.com", "SB-111")
    _, pid = verified_lawyer(admin)
    assert offer(coord, no_consent["tracking_no"], pid).status_code == 409  # ijazat nahi
    yes = post(client, key="second-key-123").json()
    client.put(f"/api/requests/{yes['id']}/consent", json={"referral": True})
    assert offer(coord, yes["tracking_no"], pending_pid).status_code == 409  # wakeel verified nahi
    assert offer(coord, yes["tracking_no"], 999).status_code == 404
    assert client.post(f"/api/requests/{yes['id']}/close").status_code == 200
    assert offer(coord, yes["tracking_no"], pid).status_code == 409  # request band
    assert client.post(f"/api/coord/requests/{yes['tracking_no']}/assign", json={"lawyer_id": pid}).status_code == 403


def test_offer_shows_no_private_text_and_user_status_unchanged(client):
    d, lc, pid, coord, aid, _ = setup_offer(client)
    offers = lc.get("/api/lawyer/offers").json()["offers"]
    assert len(offers) == 1 and offers[0]["tracking_no"] == d["tracking_no"]
    assert "Mere plot" not in lc.get("/api/lawyer/offers").text and "summary" not in lc.get("/api/lawyer/offers").text
    assert lc.get(f"/api/lawyer/cases/{d['tracking_no']}").status_code == 404  # accept se pehle nahi
    assert client.get(f"/api/requests/{d['id']}").json()["lawyer_status"] == "not_assigned"
    assert coord.get("/api/coord/queue").json()["unassigned"][0]["offer_pending"] is True


def test_accept_gives_access_only_to_that_lawyer_and_user_sees_it(client):
    d, lc, pid, coord, aid, admin = setup_offer(client)
    other, _ = verified_lawyer(admin, "other@example.com", "SB-999")
    assert other.post(f"/api/lawyer/offers/{aid}/accept").status_code == 404  # doosre wakeel ka offer nahi
    assert lc.post(f"/api/lawyer/offers/{aid}/accept").status_code == 200
    got = lc.get(f"/api/lawyer/cases/{d['tracking_no']}").json()
    assert "qabza" in got["statement"] and got["summary"]
    assert other.get(f"/api/lawyer/cases/{d['tracking_no']}").status_code == 404
    assert [c["tracking_no"] for c in lc.get("/api/lawyer/cases").json()["cases"]] == [d["tracking_no"]]
    assert other.get("/api/lawyer/cases").json()["cases"] == []
    u = client.get(f"/api/requests/{d['id']}").json()
    assert u["lawyer_status"] == "accepted" and u["assigned_lawyer"]["city"] == "Lahore"
    assert coord.get("/api/coord/queue").json()["unassigned"] == []
    assert "lawyer_accepted" in [e["event"] for e in u["timeline"]]
    with Session(engine) as db:
        logs = db.exec(select(AuditLog).where(AuditLog.action == "lawyer_viewed")).all()
        assert len(logs) == 1 and logs[0].detail == d["tracking_no"]


def test_decline_returns_request_to_queue_and_blocks_access(client):
    d, lc, pid, coord, aid, admin = setup_offer(client)
    assert lc.post(f"/api/lawyer/offers/{aid}/decline").status_code == 200
    assert lc.post(f"/api/lawyer/offers/{aid}/accept").status_code == 409
    assert lc.get(f"/api/lawyer/cases/{d['tracking_no']}").status_code == 404
    assert coord.get("/api/coord/queue").json()["unassigned"][0]["offer_pending"] is False
    _, pid2 = verified_lawyer(admin, "second@example.com", "SB-222")
    assert offer(coord, d["tracking_no"], pid2).status_code == 201


def test_expired_offer_cannot_be_accepted(client):
    d, lc, pid, coord, aid, _ = setup_offer(client)
    with Session(engine) as db:
        a = db.get(Assignment, aid)
        a.expires_at = utcnow() - timedelta(hours=1)
        db.add(a)
        db.commit()
    assert lc.post(f"/api/lawyer/offers/{aid}/accept").status_code == 409
    assert lc.get("/api/lawyer/offers").json()["offers"] == []
    with Session(engine) as db:
        assert db.get(Assignment, aid).status == "expired"
    assert "lawyer_offer_expired" in [e["event"] for e in client.get(f"/api/requests/{d['id']}").json()["timeline"]]
    assert coord.get("/api/coord/queue").json()["unassigned"][0]["tracking_no"] == d["tracking_no"]


def test_only_one_active_offer_then_revoke_and_reassign(client):
    d, lc, pid, coord, aid, admin = setup_offer(client)
    lc.post(f"/api/lawyer/offers/{aid}/accept")
    _, pid2 = verified_lawyer(admin, "second@example.com", "SB-222")
    assert offer(coord, d["tracking_no"], pid2).status_code == 409
    assert coord.post(f"/api/coord/assignments/{aid}/revoke").status_code == 200
    assert lc.get(f"/api/lawyer/cases/{d['tracking_no']}").status_code == 404  # access foran band
    assert client.get(f"/api/requests/{d['id']}").json()["lawyer_status"] == "not_assigned"
    assert coord.post(f"/api/coord/assignments/{aid}/revoke").status_code == 409
    assert offer(coord, d["tracking_no"], pid2).status_code == 201


def test_consent_withdrawal_and_close_revoke_access(client):
    d, lc, pid, coord, aid, admin = setup_offer(client)
    lc.post(f"/api/lawyer/offers/{aid}/accept")
    assert lc.get(f"/api/lawyer/cases/{d['tracking_no']}").status_code == 200
    client.put(f"/api/requests/{d['id']}/consent", json={"referral": False})
    assert lc.get(f"/api/lawyer/cases/{d['tracking_no']}").status_code == 404
    assert client.get(f"/api/requests/{d['id']}").json()["lawyer_status"] == "not_assigned"
    # band karne par bhi
    d2 = post(client, key="third-key-1234").json()
    client.put(f"/api/requests/{d2['id']}/consent", json={"referral": True})
    aid2 = offer(coord, d2["tracking_no"], pid).json()["assignment_id"]
    lc.post(f"/api/lawyer/offers/{aid2}/accept")
    client.post(f"/api/requests/{d2['id']}/close")
    assert lc.get(f"/api/lawyer/cases/{d2['tracking_no']}").status_code == 404
    assert lc.get("/api/lawyer/cases").json()["cases"] == []


def test_suspend_removes_access_immediately_even_with_old_session(client):
    d, lc, pid, coord, aid, admin = setup_offer(client)
    lc.post(f"/api/lawyer/offers/{aid}/accept")
    assert admin.post(f"/api/admin/lawyers/{pid}/suspend", json={"reason": "Complaint received"}).status_code == 200
    assert lc.get(f"/api/lawyer/cases/{d['tracking_no']}").status_code == 403
    assert lc.get("/api/lawyer/offers").status_code == 403
    u = client.get(f"/api/requests/{d['id']}").json()
    assert u["lawyer_status"] == "not_assigned"
    assert coord.get("/api/coord/queue").json()["unassigned"][0]["tracking_no"] == d["tracking_no"]
    assert admin.post(f"/api/admin/lawyers/{pid}/suspend", json={"reason": "x"}).status_code == 422
    assert admin.post(f"/api/admin/lawyers/{pid}/verify", json=VERIFY).status_code == 200  # dobara verify
    assert lc.get("/api/lawyer/offers").status_code == 200


def test_role_boundaries_and_coord_list_hides_email(client):
    d, lc, pid, coord, aid, admin = setup_offer(client)
    assert lc.get("/api/coord/queue").status_code == 403
    assert lc.get("/api/coord/lawyers").status_code == 403
    assert client.get("/api/lawyer/offers").status_code == 403
    assert client.get("/api/admin/lawyers").status_code == 403
    r = coord.get("/api/coord/lawyers")
    assert r.status_code == 200 and r.json()["lawyers"][0]["active_cases"] == 1
    assert "@" not in r.text


def test_assignment_survives_restart(client):
    d, lc, pid, coord, aid, _ = setup_offer(client)
    lc.post(f"/api/lawyer/offers/{aid}/accept")
    engine.dispose()
    with TestClient(app) as fresh:
        fresh.post("/api/auth/login", json={"email": "lawyer@example.com", "password": "strongpass1"})
        assert fresh.get(f"/api/lawyer/cases/{d['tracking_no']}").status_code == 200
