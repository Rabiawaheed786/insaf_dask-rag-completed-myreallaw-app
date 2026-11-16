import re

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.db import engine
from app.main import app
from app.models import Case, CaseEvent, User
from tests.conftest import signup

BODY = {"category": "property", "city": "Karachi", "province": "sindh",
        "statement": "Mere plot par kisi ne qabza kar liya hai aur wo wapas nahi de raha.",
        "summary": "Plot par qabza; wapsi ki madad chahiye."}


def post(c, key="key-12345678", body=None, lang=None):
    h = {"Idempotency-Key": key}
    if lang:
        h["X-Lang"] = lang
    return c.post("/api/requests", json=body or BODY, headers=h)


def test_tracking_number_comes_only_after_db_save(client):
    signup(client)
    r = post(client)
    assert r.status_code == 201
    tn = r.json()["tracking_no"]
    assert re.fullmatch(r"IS-\d{4}-[A-Z2-9]{6}", tn)
    with Session(engine) as db:  # response mil chuka, row maujood honi chahiye
        c = db.exec(select(Case).where(Case.tracking_no == tn)).one()
        assert c.statement == BODY["statement"]
        assert db.exec(select(CaseEvent).where(CaseEvent.request_id == c.id)).first().event_type == "saved"


def test_retry_with_same_key_makes_no_duplicate(client):
    signup(client)
    a = post(client)
    b = post(client)
    assert a.status_code == 201 and b.status_code == 200
    assert a.json()["tracking_no"] == b.json()["tracking_no"]
    c = post(client, key="another-key-1")
    assert c.json()["tracking_no"] != a.json()["tracking_no"]
    with Session(engine) as db:
        assert len(db.exec(select(Case)).all()) == 2


def test_request_survives_restart(client):
    signup(client)
    tn = post(client).json()["tracking_no"]
    engine.dispose()
    with TestClient(app) as fresh:
        fresh.post("/api/auth/login", json={"email": "farah@example.com", "password": "strongpass1"})
        assert [r["tracking_no"] for r in fresh.get("/api/requests").json()["requests"]] == [tn]


def test_other_user_cannot_see_requests(client):
    signup(client, "one@example.com")
    rid = post(client).json()["id"]
    other = TestClient(app)
    signup(other, "two@example.com")
    assert other.get("/api/requests").json()["requests"] == []
    assert other.get(f"/api/requests/{rid}").status_code == 404
    assert other.get(f"/api/requests/{rid}/summary.txt").status_code == 404
    assert TestClient(app).get(f"/api/requests/{rid}").status_code == 401
    assert TestClient(app).post("/api/requests", json=BODY,
                                headers={"Idempotency-Key": "key-12345678"}).status_code == 401


def test_same_key_from_two_users_stays_separate(client):
    signup(client, "one@example.com")
    a = post(client).json()
    other = TestClient(app)
    signup(other, "two@example.com")
    b = post(other).json()
    assert a["id"] != b["id"] and a["tracking_no"] != b["tracking_no"]


def test_validation(client):
    signup(client)
    assert client.post("/api/requests", json=BODY).status_code == 422  # key nahi
    assert post(client, body={**BODY, "category": "xyz"}).status_code == 422
    assert post(client, body={**BODY, "statement": "chhota"}).status_code == 422
    assert post(client, body={**BODY, "summary": "  "}).status_code == 422
    assert post(client, body={**BODY, "province": "mars"}).status_code == 422
    assert post(client, body={**BODY, "city": " "}).status_code == 422
    with Session(engine) as db:
        assert db.exec(select(Case)).first() is None  # ghalat input se kuch save nahi hua


def test_manual_submission_works_without_ai(client):
    signup(client)
    r = post(client)  # AI key nahi, AI ka code abhi hai hi nahi: manual summary se submit
    assert r.status_code == 201
    with Session(engine) as db:
        assert db.exec(select(Case)).one().ai_used is False


def test_no_lawyer_fallback_and_separate_statuses(client):
    signup(client)
    d = client.get(f"/api/requests/{post(client).json()['id']}").json()
    assert (d["status"], d["referral_status"], d["lawyer_status"]) == ("saved", "not_sent", "not_assigned")
    assert d["next_action"].startswith("Abhi wakeel assign nahi hua")
    contact = d["fallback_contacts"][0]
    assert contact["phone"] == "1099" and contact["source_url"].startswith("https://") and contact["verified_on"]
    en = client.get(f"/api/requests/{d['id']}", headers={"X-Lang": "en"}).json()
    assert en["next_action"].startswith("No lawyer has been assigned yet")
    assert client.get("/api/official-contacts").json()["contacts"][0]["phone"] == "1099"


def test_summary_download_owner_only_and_wording(client):
    signup(client)
    rid = post(client).json()["id"]
    r = client.get(f"/api/requests/{rid}/summary.txt")
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    assert BODY["statement"] in r.text and "User ka bayan" in r.text and "guarantee nahi" in r.text


def test_coordinator_queue_roles_and_no_private_text(client):
    signup(client, "user@example.com")
    post(client)
    assert client.get("/api/coord/queue").status_code == 403
    coord = TestClient(app)
    signup(coord, "coord@example.com")
    with Session(engine) as db:
        u = db.exec(select(User).where(User.email == "coord@example.com")).one()
        u.role = "coordinator"
        db.add(u)
        db.commit()
    q = coord.get("/api/coord/queue")
    assert q.status_code == 200 and len(q.json()["unassigned"]) == 1
    assert "Mere plot" not in q.text and "statement" not in q.text
    assert TestClient(app).get("/api/coord/queue").status_code == 401
