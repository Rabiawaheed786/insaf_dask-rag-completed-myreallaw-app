import os
from pathlib import Path

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.config import settings
from app.db import engine
from app.main import app
from app.models import Attachment, AuditLog, ChatMessage
from tests.conftest import signup
from tests.test_phase5 import offer, setup_offer, verified_lawyer

PDF = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF\n"
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 50


def accepted(client):
    d, lc, pid, coord, aid, admin = setup_offer(client)
    lc.post(f"/api/lawyer/offers/{aid}/accept")
    return d, lc, pid, coord, aid, admin


def say(c, tn, text="Salam", key="msg-key-0001"):
    return c.post(f"/api/cases/{tn}/messages", json={"body": text}, headers={"Idempotency-Key": key})


def put(c, tn, data=PDF, name="plot.pdf"):
    return c.post(f"/api/cases/{tn}/attachments", files={"file": (name, data, "application/octet-stream")})


def test_chat_not_open_until_lawyer_accepts(client):
    d, lc, pid, coord, aid, _ = setup_offer(client)
    tn = d["tracking_no"]
    assert say(client, tn).status_code == 409
    got = client.get(f"/api/cases/{tn}/messages").json()
    assert got == {"messages": [], "chat_open": False}
    assert lc.get(f"/api/cases/{tn}/messages").status_code == 404  # offer abhi accept nahi hua
    lc.post(f"/api/lawyer/offers/{aid}/accept")
    assert client.get(f"/api/cases/{tn}/messages").json()["chat_open"] is True


def test_user_and_lawyer_chat_and_strangers_see_nothing(client):
    d, lc, pid, coord, aid, admin = accepted(client)
    tn = d["tracking_no"]
    assert say(client, tn, "Mera plot par qabza hai", "k-user-0001").status_code == 201
    assert say(lc, tn, "Kaghzat bhej dein", "k-lawyer-001").status_code == 201
    for c in (client, lc):
        thread = c.get(f"/api/cases/{tn}/messages").json()["messages"]
        assert [m["from"] for m in thread] == ["user", "lawyer"]
    assert [m["mine"] for m in lc.get(f"/api/cases/{tn}/messages").json()["messages"]] == [False, True]
    other_user = TestClient(app)
    signup(other_user, "stranger@example.com")
    other_lawyer, _ = verified_lawyer(admin, "other@example.com", "SB-999")
    for c in (other_user, other_lawyer, coord, admin):
        assert c.get(f"/api/cases/{tn}/messages").status_code == 404
        assert say(c, tn, "hello", "k-stranger-1").status_code == 404
    assert TestClient(app).get(f"/api/cases/{tn}/messages").status_code == 401


def test_message_validation_and_retry(client):
    d, lc, *_ = accepted(client)
    tn = d["tracking_no"]
    assert client.post(f"/api/cases/{tn}/messages", json={"body": "hi"}).status_code == 422  # key nahi
    assert say(client, tn, "   ").status_code == 422
    assert say(client, tn, "x" * 2001, "k-long-00001").status_code == 422
    a, b = say(client, tn, "ek baar", "k-same-00001"), say(client, tn, "ek baar", "k-same-00001")
    assert a.status_code == 201 and b.status_code == 200 and a.json()["id"] == b.json()["id"]
    with Session(engine) as db:
        assert len(db.exec(select(ChatMessage)).all()) == 1


def test_chat_rate_limit(client, monkeypatch):
    d, lc, *_ = accepted(client)
    monkeypatch.setattr(settings, "chat_hourly_limit", 2)
    tn = d["tracking_no"]
    assert say(client, tn, "1", "k-rate-00001").status_code == 201
    assert say(client, tn, "2", "k-rate-00002").status_code == 201
    assert say(client, tn, "3", "k-rate-00003").status_code == 429
    assert say(lc, tn, "wakeel alag hadd", "k-rate-00004").status_code == 201


def test_lawyer_loses_chat_when_access_removed_but_user_keeps_history(client):
    d, lc, pid, coord, aid, _ = accepted(client)
    tn = d["tracking_no"]
    say(client, tn, "pehla", "k-hist-00001")
    coord.post(f"/api/coord/assignments/{aid}/revoke")
    assert lc.get(f"/api/cases/{tn}/messages").status_code == 404
    assert say(lc, tn, "ab bhi?", "k-hist-00002").status_code == 404
    assert len(client.get(f"/api/cases/{tn}/messages").json()["messages"]) == 1
    assert say(client, tn, "wakeel nahi", "k-hist-00003").status_code == 409
    client.post(f"/api/requests/{d['id']}/close")
    assert say(client, tn, "band", "k-hist-00004").status_code == 409


def test_upload_stores_private_random_name_and_download_roundtrip(client):
    d, lc, *_ = accepted(client)
    tn = d["tracking_no"]
    r = put(client, tn, PDF, "../../Plot Papers<1>.pdf")
    assert r.status_code == 201
    j = r.json()
    assert j["name"] == "Plot Papers1.pdf" and j["mime"] == "application/pdf" and j["uploaded_by"] == "user"
    with Session(engine) as db:
        a = db.exec(select(Attachment)).one()
        assert a.stored_name != "Plot Papers1" and len(a.stored_name) == 32 and "." not in a.stored_name
        assert (Path(settings.upload_dir) / a.stored_name).read_bytes() == PDF
        stored = a.stored_name
    for c in (client, lc):  # user aur accepted wakeel dono
        dl = c.get(f"/api/cases/{tn}/attachments/{j['id']}")
        assert dl.status_code == 200 and dl.content == PDF
        assert "attachment" in dl.headers["content-disposition"]
        assert dl.headers["x-content-type-options"] == "nosniff" and dl.headers["content-type"] == "application/pdf"
    # web par seedha kabhi nahi
    for url in (f"/uploads/{stored}", f"/static/{stored}", f"/{stored}", "/uploads/"):
        assert client.get(url).status_code in (404, 405)
    with Session(engine) as db:
        logs = db.exec(select(AuditLog).where(AuditLog.action == "file_downloaded")).all()
        assert len(logs) == 2 and all("plot" not in l.detail.lower() for l in logs)


def test_upload_validation(client, monkeypatch):
    d, *_ = accepted(client)
    tn = d["tracking_no"]
    assert put(client, tn, b"just text pretending", "fake.pdf").status_code == 422
    assert put(client, tn, b"MZ\x90\x00program", "virus.pdf").status_code == 422
    assert put(client, tn, b"", "empty.pdf").status_code == 422
    assert put(client, tn, PNG, "scan.png").status_code == 201
    monkeypatch.setattr(settings, "max_upload_mb", 1)
    assert put(client, tn, PDF + b"0" * (1024 * 1024), "big.pdf").status_code == 413
    monkeypatch.setattr(settings, "max_files_per_case", 1)
    assert put(client, tn, PDF, "second.pdf").status_code == 409
    with Session(engine) as db:
        assert len(db.exec(select(Attachment)).all()) == 1  # ghalat files kuch save nahi hui
    assert len(os.listdir(settings.upload_dir)) == 1  # disk par bhi sirf wahi ek file


def test_attachment_access_rules(client):
    d, lc, pid, coord, aid, admin = accepted(client)
    tn = d["tracking_no"]
    mine = put(client, tn).json()["id"]
    theirs = put(lc, tn, PNG, "draft.png").json()["id"]
    other = TestClient(app)
    signup(other, "stranger@example.com")
    for c in (other, coord, admin, TestClient(app)):
        assert c.get(f"/api/cases/{tn}/attachments").status_code in (401, 404)
        assert c.get(f"/api/cases/{tn}/attachments/{mine}").status_code in (401, 404)
        assert put(c, tn).status_code in (401, 404)
    assert lc.delete(f"/api/cases/{tn}/attachments/{mine}").status_code == 403  # wakeel user ki file nahi hata sakta
    assert client.delete(f"/api/cases/{tn}/attachments/{theirs}").status_code == 200  # user hata sakta hai
    assert client.get(f"/api/cases/{tn}/attachments/{theirs}").status_code == 404
    assert [a["id"] for a in client.get(f"/api/cases/{tn}/attachments").json()["attachments"]] == [mine]
    with Session(engine) as db:
        gone = db.get(Attachment, theirs)
        assert gone.deleted_at is not None and not (Path(settings.upload_dir) / gone.stored_name).exists()
    coord.post(f"/api/coord/assignments/{aid}/revoke")
    assert lc.get(f"/api/cases/{tn}/attachments/{mine}").status_code == 404
    assert put(lc, tn).status_code == 404
    assert client.get(f"/api/cases/{tn}/attachments/{mine}").status_code == 200  # malik ko hamesha


def test_files_stay_with_their_own_case(client):
    d, lc, pid, coord, aid, admin = accepted(client)
    from tests.test_requests import post
    d2 = post(client, key="second-case-0001").json()
    client.put(f"/api/requests/{d2['id']}/consent", json={"referral": True})
    fid = put(client, d2["tracking_no"]).json()["id"]
    assert lc.get(f"/api/cases/{d['tracking_no']}/attachments/{fid}").status_code == 404  # case A se case B ki file nahi
    assert lc.get(f"/api/cases/{d2['tracking_no']}/attachments").status_code == 404  # B par accepted nahi


def test_chat_and_files_survive_restart(client):
    d, lc, *_ = accepted(client)
    tn = d["tracking_no"]
    say(client, tn, "restart se pehle", "k-restart-001")
    fid = put(client, tn).json()["id"]
    engine.dispose()
    with TestClient(app) as fresh:
        fresh.post("/api/auth/login", json={"email": "lawyer@example.com", "password": "strongpass1"})
        assert fresh.get(f"/api/cases/{tn}/messages").json()["messages"][0]["body"] == "restart se pehle"
        assert fresh.get(f"/api/cases/{tn}/attachments/{fid}").content == PDF
