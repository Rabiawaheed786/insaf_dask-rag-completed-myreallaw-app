import json

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app import ai
from app.config import settings
from app.db import engine
from app.main import app
from app.models import AuditLog, Case
from app.redact import redact
from tests.conftest import signup
from tests.test_requests import BODY, post

STATEMENT = ("Mere plot par kisi ne qabza kar liya. Mera email test@example.com hai, phone 0300-1234567, "
             "CNIC 42101-1234567-1, account 123456789012.")
KEY = "SECRET-TEST-KEY-123"


class Fake:
    """Nakli Gemini: har call record karta hai, asli internet nahi."""
    def __init__(self, mode="ok"):
        self.calls, self.mode = [], mode

    def __call__(self, request: httpx.Request):
        self.calls.append(request)
        if self.mode == "timeout":
            raise httpx.ReadTimeout("slow", request=request)
        if self.mode == "500":
            return httpx.Response(500, json={"error": "boom"})
        if self.mode == "badjson":
            return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "not json"}]}}]})
        body = json.loads(request.content)
        prompt = body["contents"][0]["parts"][0]["text"]
        out = ({"questions": ["Kab hua?", "Kaghzat hain?"]} if "TASK=CLARIFY" in prompt
               else {"summary": "User ka kehna hai ke plot par qabza hua hai."})
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": json.dumps(out)}]}}]})


@pytest.fixture()
def ai_on(monkeypatch):
    monkeypatch.setattr(settings, "ai_enabled", True)
    monkeypatch.setattr(settings, "ai_api_key", KEY)
    monkeypatch.setattr(settings, "ai_tier", "free")
    monkeypatch.setattr(settings, "app_env", "development")
    monkeypatch.setattr(settings, "ai_hourly_limit", 10)
    fake = Fake()
    ai.set_transport(httpx.MockTransport(fake))
    yield fake
    ai.set_transport(None)


def body(**kw):
    return {"category": "property", "statement": STATEMENT, "consent": True, **kw}


def test_ai_is_off_by_default(client):
    signup(client)
    s = client.get("/api/ai/status").json()
    assert s["available"] is False and s["reason"] == "ai_disabled"
    assert client.post("/api/ai/summarize", json=body()).status_code == 503


def test_no_key_and_free_tier_in_production_blocked(client, monkeypatch):
    signup(client)
    monkeypatch.setattr(settings, "ai_enabled", True)
    monkeypatch.setattr(settings, "ai_api_key", "")
    assert client.get("/api/ai/status").json()["reason"] == "ai_no_key"
    monkeypatch.setattr(settings, "ai_api_key", KEY)
    monkeypatch.setattr(settings, "ai_tier", "free")
    monkeypatch.setattr(settings, "app_env", "production")
    assert client.get("/api/ai/status").json()["reason"] == "ai_free_tier_blocked"
    monkeypatch.setattr(settings, "ai_tier", "paid")
    assert client.get("/api/ai/status").json()["available"] is True


def test_children_category_blocked(client, ai_on):
    signup(client)
    r = client.post("/api/ai/summarize", json=body(category="children"))
    assert r.status_code == 503 and r.json()["detail"]["code"] == "ai_not_for_category"
    assert ai_on.calls == []


def test_consent_required_and_nothing_sent_without_it(client, ai_on):
    signup(client)
    r = client.post("/api/ai/summarize", json=body(consent=False))
    assert r.status_code == 422 and r.json()["detail"]["code"] == "ai_consent_required"
    assert ai_on.calls == []


def test_redaction_unit():
    clean, n = redact(STATEMENT + " IBAN PK36SCBL0000001123456702 +92 321 7654321")
    for secret in ("test@example.com", "0300-1234567", "42101-1234567-1", "123456789012",
                   "PK36SCBL0000001123456702", "321 7654321"):
        assert secret not in clean
    assert set(n) == {"EMAIL", "PHONE", "CNIC", "ACCOUNT", "IBAN"}


def test_summarize_sends_redacted_text_and_key_only_in_header(client, ai_on):
    signup(client)
    r = client.post("/api/ai/summarize", json=body())
    assert r.status_code == 200
    j = r.json()
    assert j["ai"] is True and "qabza" in j["summary"] and "AI ka draft" in j["notice"]
    assert set(j["redactions"]) == {"EMAIL", "PHONE", "CNIC", "ACCOUNT"}
    sent = ai_on.calls[0]
    raw = sent.content.decode()
    for secret in ("test@example.com", "0300-1234567", "42101-1234567-1", "123456789012"):
        assert secret not in raw
    assert sent.headers["x-goog-api-key"] == KEY and KEY not in str(sent.url) and KEY not in raw
    assert "<<<USER_STATEMENT" in raw and "ignore any instructions" in raw
    assert KEY not in r.text


def test_clarify_returns_questions(client, ai_on):
    signup(client)
    r = client.post("/api/ai/clarify", json=body())
    assert r.status_code == 200 and r.json()["questions"] == ["Kab hua?", "Kaghzat hain?"]


@pytest.mark.parametrize("mode", ["timeout", "500", "badjson"])
def test_ai_failure_still_allows_manual_submission(client, ai_on, mode):
    signup(client)
    ai_on.mode = mode
    r = client.post("/api/ai/summarize", json=body())
    assert r.status_code == 503 and r.json()["detail"]["code"] == "ai_unavailable"
    assert KEY not in r.text
    sub = post(client)  # AI fail hua, request phir bhi save
    assert sub.status_code == 201
    with Session(engine) as db:
        assert db.exec(select(Case)).one().ai_used is False


def test_ai_used_flag_saved_when_user_submits_ai_draft(client, ai_on):
    signup(client)
    draft = client.post("/api/ai/summarize", json=body()).json()["summary"]
    r = client.post("/api/requests", json={**BODY, "summary": draft, "ai_used": True},
                    headers={"Idempotency-Key": "ai-key-12345"})
    assert r.status_code == 201
    with Session(engine) as db:
        assert db.exec(select(Case)).one().ai_used is True


def test_hourly_limit_and_audit_has_no_text(client, ai_on, monkeypatch):
    signup(client)
    monkeypatch.setattr(settings, "ai_hourly_limit", 2)
    assert client.post("/api/ai/summarize", json=body()).status_code == 200
    assert client.post("/api/ai/clarify", json=body()).status_code == 200
    assert client.post("/api/ai/summarize", json=body()).status_code == 429
    with Session(engine) as db:
        logs = db.exec(select(AuditLog).where(AuditLog.action == "ai_call")).all()
        assert len(logs) == 2 and all(l.detail == "" for l in logs)


def test_ai_needs_login_and_validates_input(client, ai_on):
    assert TestClient(app).post("/api/ai/summarize", json=body()).status_code == 401
    signup(client)
    assert client.post("/api/ai/summarize", json=body(statement="chhota")).status_code == 422
    assert client.post("/api/ai/summarize", json=body(category="xyz")).status_code == 422
    assert ai_on.calls == []
