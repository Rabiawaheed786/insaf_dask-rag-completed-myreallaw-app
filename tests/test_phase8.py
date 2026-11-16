import json
import os
import zipfile
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app import cli
from app.backup import BackupError, create_backup, restore_backup
from app.config import settings
from app.db import engine
from app.main import app
from app.models import (Attachment, AuditLog, AuthSession, Case, CaseEvent, ChatMessage, Notification, Referral, User,
                        utcnow)
from app.retention import purge_expired
from tests.conftest import signup
from tests.test_phase3 import make_role, staff
from tests.test_phase5 import admin_client, offer, setup_offer, verified_lawyer
from tests.test_phase6 import PDF, accepted, put, say
from tests.test_requests import BODY, post

PW = "strongpass1"


def login(email, password=PW):
    c = TestClient(app)
    r = c.post("/api/auth/login", json={"email": email, "password": password})
    return c, r


# ---------------- foran madad ----------------
def test_emergency_is_public_and_shows_only_admin_added_verified_contacts(client):
    r = TestClient(app).get("/api/emergency")
    assert r.status_code == 200 and "intezar na karein" in r.json()["message"] and r.json()["contacts"] == []
    assert "do not wait" in TestClient(app).get("/api/emergency", headers={"X-Lang": "en"}).json()["message"]
    admin = admin_client()
    good = {"name": "Local Police Emergency", "phone": "TEST-000", "scope": "national", "emergency": True,
            "source_url": "https://example.gov.pk/emergency", "verified_on": "2026-11-01"}
    assert admin.post("/api/admin/contacts", json=good).status_code == 201
    assert admin.post("/api/admin/contacts", json={**good, "phone": "TEST-111", "emergency": False}).status_code == 201
    contacts = TestClient(app).get("/api/emergency").json()["contacts"]
    assert [c["phone"] for c in contacts] == ["TEST-000"] and contacts[0]["source_url"].startswith("https://")
    assert admin.post("/api/admin/contacts", json={**good, "source_url": "http://x"}).status_code == 422


# ---------------- bachon ke cases ----------------
def test_child_requests_wait_for_qualified_review_before_anything_is_sent(client):
    signup(client, "parent@example.com")
    d = post(client, body={**BODY, "category": "children"}, key="child-key-0001").json()
    tn = d["tracking_no"]
    client.put(f"/api/requests/{d['id']}/consent", json={"referral": True})
    got = client.get(f"/api/requests/{d['id']}").json()
    assert got["child_review"] == "pending" and "tarbiyat yafta reviewer" in got["next_action"]
    assert "guardian" in got["next_action"] and got["fallback_contacts"]
    coord, admin = staff(), admin_client()
    _, pid = verified_lawyer(admin)
    assert offer(coord, tn, pid).status_code == 409
    r = coord.post(f"/api/coord/requests/{tn}/referrals", json={"target": "Centre", "status": "attempted"},
                   headers={"Idempotency-Key": "child-ref-0001"})
    assert r.status_code == 409
    with Session(engine) as db:  # kuch bheja hi nahi gaya
        assert db.exec(select(Referral)).first() is None and db.exec(select(CaseEvent).where(
            CaseEvent.event_type == "lawyer_offered")).first() is None
    assert coord.get("/api/coord/queue").json()["unassigned"][0]["child_review"] == "pending"
    assert coord.post(f"/api/admin/requests/{tn}/child-review", json={"decision": "cleared", "note": "x" * 12}).status_code == 403
    assert admin.post(f"/api/admin/requests/{tn}/child-review", json={"decision": "cleared", "note": "short"}).status_code == 422
    assert admin.post(f"/api/admin/requests/{tn}/child-review", json={"decision": "cleared", "note": "Reviewed by child protection officer"}).status_code == 200
    assert offer(coord, tn, pid).status_code == 201  # ab hi


def test_review_endpoint_only_for_child_requests(client):
    signup(client, "user@example.com")
    d = post(client).json()
    admin = admin_client()
    r = admin.post(f"/api/admin/requests/{d['tracking_no']}/child-review", json={"decision": "cleared", "note": "n" * 12})
    assert r.status_code == 422


# ---------------- CSRF, headers, hadd ----------------
def test_cross_site_writes_are_blocked_even_with_valid_cookie(client):
    signup(client)
    body = {"language": "en"}
    assert client.put("/api/auth/me/language", json=body, headers={"Origin": "https://evil.example"}).status_code == 403
    assert client.put("/api/auth/me/language", json=body, headers={"Origin": "null"}).status_code == 403
    assert client.put("/api/auth/me/language", json=body, headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert client.put("/api/auth/me/language", json=body, headers={"Origin": "http://testserver"}).status_code == 200
    assert client.put("/api/auth/me/language", json=body).status_code == 200  # curl jaisa client
    assert client.get("/api/auth/me", headers={"Origin": "https://evil.example"}).status_code == 200  # parhna theek
    r = client.post("/api/auth/logout", headers={"Origin": "https://evil.example"})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "csrf_blocked"
    assert client.get("/api/auth/me").status_code == 200  # logout hua hi nahi


def test_trusted_origin_setting_allows_proxy_domain(client, monkeypatch):
    signup(client)
    h = {"Origin": "https://insafdastak.example"}
    assert client.put("/api/auth/me/language", json={"language": "en"}, headers=h).status_code == 403
    monkeypatch.setattr(settings, "trusted_origins", "https://insafdastak.example")
    assert client.put("/api/auth/me/language", json={"language": "en"}, headers=h).status_code == 200


def test_security_headers_csp_and_hsts(client, monkeypatch):
    for url in ("/api/health", "/"):
        h = client.get(url).headers
        assert "default-src 'self'" in h["content-security-policy"] and "frame-ancestors 'none'" in h["content-security-policy"]
        assert h["x-frame-options"] == "DENY" and h["x-content-type-options"] == "nosniff"
        assert "camera=()" in h["permissions-policy"] and "strict-transport-security" not in h
    assert "content-security-policy" not in client.get("/docs").headers  # Swagger CDN se chalta hai
    monkeypatch.setattr(settings, "cookie_secure", True)
    assert "max-age" in client.get("/api/health").headers["strict-transport-security"]


def test_per_ip_rate_limits_on_login_and_signup(client, monkeypatch):
    monkeypatch.setattr(settings, "login_per_minute_ip", 3)
    monkeypatch.setattr(settings, "signup_per_hour_ip", 2)
    c = TestClient(app)
    codes = [c.post("/api/auth/login", json={"email": f"x{i}@example.com", "password": "whatever1"}).status_code for i in range(4)]
    assert codes == [401, 401, 401, 429]
    assert [signup(c, f"s{i}@example.com").status_code for i in range(3)] == [201, 201, 429]


# ---------------- password ----------------
def test_change_password_logs_out_other_sessions(client):
    signup(client, "user@example.com")
    other, _ = login("user@example.com")
    assert client.post("/api/auth/change-password", json={"old_password": "nope-nope", "new_password": "newpass123"}).status_code == 401
    assert client.post("/api/auth/change-password", json={"old_password": PW, "new_password": "short"}).status_code == 422
    assert client.post("/api/auth/change-password", json={"old_password": PW, "new_password": "newpass123"}).status_code == 200
    assert client.get("/api/auth/me").status_code == 200  # abhi wali session barkarar
    assert other.get("/api/auth/me").status_code == 401  # doosri jagah se logout
    assert login("user@example.com", PW)[1].status_code == 401
    assert login("user@example.com", "newpass123")[1].status_code == 200


def test_cli_reset_password_revoke_sessions_and_make_admin(client):
    signup(client, "user@example.com")
    assert cli.reset_password("ghost@example.com") is None
    temp = cli.reset_password("user@example.com")
    assert temp and len(temp) >= 10
    assert client.get("/api/auth/me").status_code == 401  # purani session band
    assert login("user@example.com", PW)[1].status_code == 401
    c, r = login("user@example.com", temp)
    assert r.status_code == 200
    assert cli.revoke_sessions("user@example.com") == 1 and c.get("/api/auth/me").status_code == 401
    assert cli.revoke_sessions("ghost@example.com") == -1
    c2, _ = login("user@example.com", temp)
    assert cli.revoke_sessions(None) >= 1 and c2.get("/api/auth/me").status_code == 401
    assert cli.main(["make-admin", "user@example.com"]) == 0 and cli.main(["make-admin", "ghost@example.com"]) == 1
    with Session(engine) as db:
        assert db.exec(select(AuditLog).where(AuditLog.action == "password_reset_by_admin_cli")).first()


# ---------------- backup aur restore ----------------
def test_backup_restore_round_trip_with_files_and_login(client, tmp_path):
    d, lc, pid, coord, aid, admin = accepted(client)
    tn = d["tracking_no"]
    say(client, tn, "restore se pehle ka message", "k-bk-0000001")
    fid = put(client, tn).json()["id"]
    zip_path = create_backup(tmp_path / "bk")
    manifest = json.loads(zipfile.ZipFile(zip_path).read("manifest.json"))
    assert manifest["counts"]["requests"] == 1 and manifest["counts"]["attachments"] == 1
    assert sum(1 for n in manifest["files"] if n.startswith("uploads/")) == 1
    # sab kuch tabah: database aur files ghayab
    engine.dispose()
    Path(settings.database_url[len("sqlite:///"):]).unlink()
    for f in Path(settings.upload_dir).iterdir():
        f.unlink()
    counts = restore_backup(zip_path)
    assert counts["requests"] == 1
    with TestClient(app) as fresh:
        fresh.post("/api/auth/login", json={"email": "user@example.com", "password": PW})
        assert fresh.get(f"/api/cases/{tn}/messages").json()["messages"][0]["body"] == "restore se pehle ka message"
        assert fresh.get(f"/api/cases/{tn}/attachments/{fid}").content == PDF
        assert fresh.get(f"/api/requests/{d['id']}").json()["lawyer_status"] == "accepted"
    assert login("lawyer@example.com")[1].status_code == 200


def test_backup_restore_rejects_tampered_or_bad_files(client, tmp_path):
    signup(client)
    good = create_backup(tmp_path)
    # database badal di, manifest wahi
    bad = tmp_path / "tampered.zip"
    with zipfile.ZipFile(good) as zin, zipfile.ZipFile(bad, "w") as zout:
        for n in zin.namelist():
            zout.writestr(n, b"corrupted" if n == "database.db" else zin.read(n))
    with pytest.raises(BackupError, match="Hash"):
        restore_backup(bad)
    # manifest mein raaste ki chaal
    evil = tmp_path / "evil.zip"
    with zipfile.ZipFile(evil, "w") as z:
        z.writestr("manifest.json", json.dumps({"files": {"../evil": "00", "database.db": "00"}}))
        z.writestr("../evil", b"x")
        z.writestr("database.db", b"x")
    with pytest.raises(BackupError):
        restore_backup(evil)
    notzip = tmp_path / "x.zip"
    notzip.write_bytes(b"not a zip")
    with pytest.raises(BackupError):
        restore_backup(notzip)
    assert not Path("../evil").exists() and not (tmp_path / "evil").exists()
    with Session(engine) as db:  # ghalat restore ne maujooda database ko nahi chheda
        assert db.exec(select(User)).first() is not None


def test_restore_keeps_a_safety_copy_and_backup_prunes_old(client, tmp_path):
    signup(client)
    paths = [create_backup(tmp_path / "bk", keep=2) for _ in range(3)]
    assert len(list((tmp_path / "bk").glob("insaf-backup-*.zip"))) == 2 and not paths[0].exists()
    engine.dispose()
    restore_backup(paths[2])
    assert Path(settings.database_url[len("sqlite:///"):] + ".pre-restore").exists()
    assert cli.main(["restore", str(paths[2])]) == 2  # --yes ke bagair kuch nahi


# ---------------- retention aur apna data ----------------
def test_retention_erases_text_chat_and_files_of_old_closed_requests_only(client):
    d, lc, pid, coord, aid, admin = accepted(client)
    tn = d["tracking_no"]
    say(client, tn, "purana message", "k-ret-0000001")
    fid = put(client, tn).json()["id"]
    d_open = post(client, key="open-case-0001").json()
    client.post(f"/api/requests/{d['id']}/close")
    with Session(engine) as db:
        stored = db.exec(select(Attachment)).one().stored_name
        e = db.exec(select(CaseEvent).where(CaseEvent.event_type == "closed")).one()
        e.at = utcnow() - timedelta(days=settings.retention_days + 5)
        db.add(e)
        db.add(AuthSession(token_hash="stale", user_id=1, expires_at=utcnow() - timedelta(days=1)))
        db.commit()
        assert purge_expired(db) == {"sessions_deleted": 1, "cases_purged": 1}
        c = db.exec(select(Case).where(Case.tracking_no == tn)).one()
        assert c.statement == "[deleted]" and c.summary == "[deleted]" and c.tracking_no == tn
        assert db.exec(select(ChatMessage)).first() is None
        assert db.get(Attachment, fid).deleted_at is not None
        assert not (Path(settings.upload_dir) / stored).exists()
        other = db.exec(select(Case).where(Case.id == d_open["id"])).one()
        assert other.statement == BODY["statement"]  # khuli request ko haath nahi
        assert purge_expired(db) == {"sessions_deleted": 0, "cases_purged": 0}  # dobara kuch nahi
    assert client.get(f"/api/requests/{d['id']}").json()["statement"] == "[deleted]"


def test_user_can_export_only_own_data(client):
    signup(client, "one@example.com")
    post(client)
    other = TestClient(app)
    signup(other, "two@example.com")
    post(other, body={**BODY, "statement": "Doosre user ka alag bayan jo kisi aur ko nahi dikhna chahiye."}, key="other-key-0001")
    r = client.get("/api/me/export")
    assert r.status_code == 200
    j = r.json()
    assert len(j["requests"]) == 1 and j["requests"][0]["statement"] == BODY["statement"]
    assert "Doosre user" not in r.text and "password" not in r.text and "two@example.com" not in r.text
    assert TestClient(app).get("/api/me/export").status_code == 401


def test_account_deletion_erases_content_and_blocks_login(client):
    d, lc, pid, coord, aid, admin = accepted(client)
    tn = d["tracking_no"]
    say(client, tn, "mera message", "k-del-0000001")
    put(client, tn)
    bystander = TestClient(app)
    signup(bystander, "bystander@example.com")
    keep = post(bystander, key="keep-case-0001").json()
    assert client.request("DELETE", "/api/me", json={"password": "wrong-pass"}).status_code == 401
    assert lc.request("DELETE", "/api/me", json={"password": PW}).status_code == 409  # wakeel khud nahi
    assert client.request("DELETE", "/api/me", json={"password": PW}).status_code == 200
    assert client.get("/api/auth/me").status_code == 401
    assert login("user@example.com")[1].status_code == 401
    with Session(engine) as db:
        u = db.get(User, 1)
        assert u.email == "deleted-1@deleted.invalid" and u.display_name == ""
        c = db.exec(select(Case).where(Case.tracking_no == tn)).one()
        assert c.statement == "[deleted]" and c.status == "closed"
        assert db.exec(select(ChatMessage)).first() is None
        assert all(a.deleted_at for a in db.exec(select(Attachment)).all())
        assert db.exec(select(Notification).where(Notification.user_id == 1)).first() is None
        assert "user@example.com" not in " ".join(a.detail for a in db.exec(select(AuditLog)).all())
    assert lc.get(f"/api/lawyer/cases/{tn}").status_code == 404  # wakeel ka access bhi gaya
    assert bystander.get(f"/api/requests/{keep['id']}").json()["statement"] == BODY["statement"]
