from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.db import engine
from app.main import app
from app.models import AuthSession, User
from tests.conftest import signup


def test_health_and_index(client):
    assert client.get("/api/health").json() == {"status": "ok"}
    r = client.get("/")
    assert r.status_code == 200 and "Insaf Dastak" in r.text


def test_signup_login_me(client):
    r = signup(client)
    assert r.status_code == 201
    assert "password" not in r.text
    assert client.get("/api/auth/me").json()["email"] == "farah@example.com"
    client.post("/api/auth/logout")
    assert client.get("/api/auth/me").status_code == 401
    r = client.post("/api/auth/login", json={"email": "FARAH@example.com", "password": "strongpass1"})
    assert r.status_code == 200


USER_KEYS = {"id", "email", "display_name", "role", "language", "timezone"}


def test_signup_login_me_return_the_same_user_keys(client):
    created = signup(client)
    assert created.status_code == 201
    body = created.json()
    assert set(body) == USER_KEYS and isinstance(body["id"], int)
    client.post("/api/auth/logout")
    logged = client.post("/api/auth/login", json={"email": "farah@example.com", "password": "strongpass1"})
    assert logged.status_code == 200 and set(logged.json()) == USER_KEYS and logged.json()["id"] == body["id"]
    me = client.get("/api/auth/me")
    assert me.status_code == 200 and set(me.json()) == USER_KEYS and me.json()["id"] == body["id"]


def test_signup_with_an_existing_account_returns_a_clean_conflict(client):
    assert signup(client).status_code == 201
    dup = signup(client)
    assert dup.status_code == 409
    detail = dup.json()["detail"]
    assert detail["code"] == "email_taken" and detail["message"]


def test_password_and_token_never_stored_plain(client):
    r = signup(client)
    token = client.cookies.get("insaf_session")
    assert "HttpOnly" in r.headers["set-cookie"] and "SameSite=lax" in r.headers["set-cookie"]
    with Session(engine) as db:
        u = db.exec(select(User)).first()
        assert u.password_hash.startswith("$argon2") and "strongpass1" not in u.password_hash
        assert all(s.token_hash != token for s in db.exec(select(AuthSession)).all())


def test_data_survives_restart(client):
    signup(client)
    engine.dispose()  # connection band, jaise server band hua
    with TestClient(app) as fresh:  # naya "server", wahi database
        r = fresh.post("/api/auth/login", json={"email": "farah@example.com", "password": "strongpass1"})
        assert r.status_code == 200


def test_two_users_are_separate(client):
    signup(client, "one@example.com")
    other = TestClient(app)
    signup(other, "two@example.com")
    assert client.get("/api/auth/me").json()["email"] == "one@example.com"
    assert other.get("/api/auth/me").json()["email"] == "two@example.com"
    assert TestClient(app).get("/api/auth/me").status_code == 401


def test_duplicate_and_validation(client):
    signup(client)
    assert signup(client).status_code == 409
    assert signup(client, "bad").status_code == 422
    assert signup(client, "x@example.com", "short").status_code == 422


def test_login_errors_do_not_reveal_email(client):
    signup(client)
    a = client.post("/api/auth/login", json={"email": "farah@example.com", "password": "wrong-pass"})
    b = client.post("/api/auth/login", json={"email": "nobody@example.com", "password": "wrong-pass"})
    assert a.status_code == b.status_code == 401
    assert a.json() == b.json()


def test_lockout_after_failed_attempts(client):
    signup(client)
    client.post("/api/auth/logout")
    for _ in range(3):
        client.post("/api/auth/login", json={"email": "farah@example.com", "password": "wrong-pass"})
    r = client.post("/api/auth/login", json={"email": "farah@example.com", "password": "strongpass1"})
    assert r.status_code == 429


def test_language_switch_and_messages(client):
    signup(client)
    assert client.put("/api/auth/me/language", json={"language": "en"}).json()["language"] == "en"
    assert client.put("/api/auth/me/language", json={"language": "fr"}).status_code == 422
    client.post("/api/auth/logout")
    en = client.get("/api/auth/me", headers={"X-Lang": "en"}).json()["detail"]["message"]
    ur = client.get("/api/auth/me", headers={"X-Lang": "roman_urdu"}).json()["detail"]["message"]
    assert en == "Please log in first." and ur == "Pehle login karein."
