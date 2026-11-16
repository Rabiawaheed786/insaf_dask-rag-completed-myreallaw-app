"""Poore safar ke tests (PRD ki verification list). Har test ek mukammal kahani hai, alag alag cheezein nahi."""
import httpx
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app import ai
from app.backup import create_backup, restore_backup
from app.config import settings
from app.db import engine
from app.main import app
from app.models import Case
from app.notify import run_reminders
from tests.conftest import signup
from tests.test_phase3 import staff
from tests.test_phase4 import KEY, Fake, body as ai_body
from tests.test_phase5 import admin_client, lawyer_applied, VERIFY
from tests.test_phase6 import PDF, put, say
from tests.test_phase7 import day_at, follow
from tests.test_requests import BODY, post
from tests.test_phase8 import PW, login


@pytest.fixture()
def ai_failing(monkeypatch):
    monkeypatch.setattr(settings, "ai_enabled", True)
    monkeypatch.setattr(settings, "ai_api_key", KEY)
    monkeypatch.setattr(settings, "ai_tier", "free")
    monkeypatch.setattr(settings, "app_env", "development")
    ai.set_transport(httpx.MockTransport(Fake("500")))
    yield
    ai.set_transport(None)


def restart():
    engine.dispose()  # server band: sab connection khatam; naya server wahi database kholta hai


def test_full_journey_survives_restarts_and_backup(client, ai_failing, tmp_path):
    # 1. User: AI chalne se inkar kare tab bhi request submit ho aur save ho
    signup(client, "user@example.com")
    assert client.post("/api/ai/summarize", json=ai_body()).status_code == 503
    sub = post(client)
    assert sub.status_code == 201
    d = sub.json()
    tn = d["tracking_no"]
    # 2. Koi wakeel nahi: saaf likha ho, verified contact ho, coordinator ki queue mein ho
    assert d["lawyer_status"] == "not_assigned" and d["next_action"].startswith("Abhi wakeel assign nahi hua")
    assert d["fallback_contacts"][0]["phone"] == "1099"
    coord, admin = staff(), admin_client()
    assert coord.get("/api/coord/queue").json()["unassigned"][0]["tracking_no"] == tn
    # 3. Wakeel ki arzi: verification se pehle kuch nahi
    lc = TestClient(app)
    signup(lc, "lawyer@example.com")
    pid = lc.post("/api/lawyer/apply", json={"bar_council": "Punjab Bar Council", "licence_no": "PB-777", "city": "Lahore"}).json()["id"]
    assert lc.get("/api/lawyer/offers").status_code == 403
    admin.post(f"/api/admin/lawyers/{pid}/verify", json=VERIFY)
    # 4. User ki ijazat ke bina offer nahi; ijazat ke baad offer
    assert coord.post(f"/api/coord/requests/{tn}/assign", json={"lawyer_id": pid}).status_code == 409
    client.put(f"/api/requests/{d['id']}/consent", json={"referral": True})
    aid = coord.post(f"/api/coord/requests/{tn}/assign", json={"lawyer_id": pid}).json()["assignment_id"]
    restart()  # --- server restart #1
    lc, _ = login("lawyer@example.com")
    client, _ = login("user@example.com")
    assert lc.post(f"/api/lawyer/offers/{aid}/accept").status_code == 200
    # 5. Chat aur file
    assert say(client, tn, "Salam wakeel sahab", "e2e-msg-00001").status_code == 201
    assert say(lc, tn, "Kaghzat bhej dein", "e2e-msg-00002").status_code == 201
    fid = put(client, tn).json()["id"]
    assert lc.get(f"/api/cases/{tn}/attachments/{fid}").content == PDF
    # 6. Reminder: ek din mein ek, restart ke baad bhi
    follow(client, pref="daily", safe_time="00:00")
    from datetime import timedelta
    from app.models import utcnow
    now = utcnow() + timedelta(hours=1)
    with Session(engine) as db:
        assert run_reminders(db, now) == 1
    restart()  # --- restart #2
    with Session(engine) as db:
        assert run_reminders(db, now) == 0
    # 7. Wakeel ka slot aur booking
    lc, _ = login("lawyer@example.com")
    client, _ = login("user@example.com")
    sid = lc.post("/api/lawyer/availability", json=dict(zip(("start", "end"), day_at(2)))).json()["slots"][0]["id"]
    assert client.post(f"/api/cases/{tn}/slots/{sid}/book").status_code == 200
    # 8. Backup, tabahi, restore
    bk = create_backup(tmp_path / "bk")
    engine.dispose()
    from pathlib import Path
    Path(settings.database_url[len("sqlite:///"):]).unlink()
    for f in Path(settings.upload_dir).iterdir():
        f.unlink()
    restore_backup(bk)
    lc, _ = login("lawyer@example.com")
    client, _ = login("user@example.com")
    assert [m["body"] for m in client.get(f"/api/cases/{tn}/messages").json()["messages"]] == ["Salam wakeel sahab", "Kaghzat bhej dein"]
    assert lc.get(f"/api/cases/{tn}/attachments/{fid}").content == PDF
    assert client.get(f"/api/cases/{tn}/slots").json()["my_booking"]["id"] == sid
    # 9. Request band: wakeel ka access foran khatam, user ka data baqi
    client.post(f"/api/requests/{d['id']}/close")
    assert lc.get(f"/api/lawyer/cases/{tn}").status_code == 404 and lc.get(f"/api/cases/{tn}/messages").status_code == 404
    assert client.get("/api/me/export").json()["requests"][0]["statement"] == BODY["statement"]
    with Session(engine) as db:
        assert db.exec(select(Case)).one().tracking_no == tn


def test_stranger_sees_nothing_anywhere(client):
    """Doosra user, doosra wakeel, coordinator, admin aur anjaan: har raaste par band darwaza."""
    signup(client, "owner@example.com")
    d = post(client).json()
    tn, rid = d["tracking_no"], d["id"]
    client.put(f"/api/requests/{rid}/consent", json={"referral": True})
    # owner ke paas sab kuch hai (messages ke liye accepted wakeel chahiye, is liye files aur summary)
    put(client, tn)
    admin = admin_client()
    other_lawyer, _ = lawyer_applied("other@example.com", "SB-555")
    admin.post("/api/admin/lawyers/1/verify", json=VERIFY)
    stranger = TestClient(app)
    signup(stranger, "stranger@example.com")
    clients = {"stranger": stranger, "other_lawyer": other_lawyer, "coordinator": staff("c@example.com"), "anonymous": TestClient(app)}
    paths = [("GET", f"/api/requests/{rid}"), ("GET", f"/api/requests/{rid}/summary.txt"),
             ("PUT", f"/api/requests/{rid}/consent"), ("POST", f"/api/requests/{rid}/close"),
             ("GET", f"/api/cases/{tn}/messages"), ("GET", f"/api/cases/{tn}/attachments"),
             ("GET", f"/api/cases/{tn}/attachments/1"), ("DELETE", f"/api/cases/{tn}/attachments/1"),
             ("GET", f"/api/cases/{tn}/slots"), ("GET", f"/api/lawyer/cases/{tn}")]
    for who, c in clients.items():
        for method, url in paths:
            r = c.request(method, url, json={"referral": False} if method == "PUT" else None)
            assert r.status_code in (401, 403, 404), (who, method, url, r.status_code)
            assert BODY["statement"] not in r.text and BODY["summary"] not in r.text, (who, url)
    # list wale endpoints khali
    assert stranger.get("/api/requests").json()["requests"] == []
    assert stranger.get("/api/notifications").json()["notifications"] == []
    assert stranger.get("/api/me/export").json()["requests"] == []
    # owner ka data ab bhi poora
    assert client.get(f"/api/requests/{rid}").json()["statement"] == BODY["statement"]
    assert len(client.get(f"/api/cases/{tn}/attachments").json()["attachments"]) == 1


def test_private_files_are_never_reachable_without_the_api(client):
    signup(client, "owner@example.com")
    d = post(client).json()
    put(client, d["tracking_no"])
    from pathlib import Path
    stored = [p.name for p in Path(settings.upload_dir).iterdir()]
    assert len(stored) == 1
    anon = TestClient(app)
    for url in (f"/uploads/{stored[0]}", f"/static/{stored[0]}", f"/{stored[0]}", f"/api/cases/{d['tracking_no']}/attachments/1",
                "/uploads", "/static/../uploads", "/.env", "/insaf_dastak.db"):
        r = anon.get(url)
        assert r.status_code in (401, 404, 405) and PDF not in r.content, url
