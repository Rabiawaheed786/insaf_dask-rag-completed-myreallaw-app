"""Admin-managed BYOK: key encryption, masked response, role guard aur dynamic routing."""
import json

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app import ai
from app.config import settings
from app.crypto import decrypt_secret
from app.db import engine
from app.main import app
from app.models import AIProviderSettings, AuditLog, User
from app.services import llm
from tests.conftest import signup


def make_role(email, role):
    with Session(engine) as db:
        u = db.exec(select(User).where(User.email == email)).one()
        u.role = role
        db.add(u)
        db.commit()


def staff(role="coordinator"):
    email = f"{role}@example.com"
    c = TestClient(app)
    signup(c, email)
    make_role(email, role)
    return c


def save(c, provider="deepseek", model="deepseek-chat", key="sk-test-12345678"):
    return c.put("/api/admin/ai-config",
                 json={"provider_name": provider, "model_name": model, "api_key": key})


def test_admin_saves_encrypted_key_and_only_masked_key_returns(client):
    admin = staff("admin")
    r = save(admin, "openai", "gpt-4o-mini", "sk-proj-super-secret-1234")
    assert r.status_code == 200
    body = r.json()
    assert body["provider_name"] == "openai" and body["configured"] is True
    assert body["masked_key"] == "sk-...1234"
    assert "super-secret" not in json.dumps(body)

    with Session(engine) as db:
        row = db.get(AIProviderSettings, 1)
        assert row.encrypted_api_key and row.encrypted_api_key != "sk-proj-super-secret-1234"
        assert decrypt_secret(row.encrypted_api_key) == "sk-proj-super-secret-1234"
        log = db.exec(select(AuditLog).where(AuditLog.action == "ai_config_saved")).first()
        assert log is not None and "super-secret" not in (log.detail or "")

    got = admin.get("/api/admin/ai-config").json()
    assert got["masked_key"] == "sk-...1234" and "super-secret" not in json.dumps(got)


def test_saving_without_new_key_keeps_old_key(client):
    admin = staff("admin")
    save(admin, "gemini", "gemini-2.0-flash", "gemini-secret-9999")
    r = save(admin, "gemini", "gemini-2.0-flash", "")
    assert r.status_code == 200 and r.json()["masked_key"].endswith("9999")
    with Session(engine) as db:
        assert decrypt_secret(db.get(AIProviderSettings, 1).encrypted_api_key) == "gemini-secret-9999"


def test_provider_change_needs_new_key(client):
    admin = staff("admin")
    save(admin, "gemini", "", "gemini-secret-9999")
    r = save(admin, "deepseek", "", "")
    assert r.status_code == 422 and r.json()["detail"]["code"] == "ai_key_required"


def test_bad_provider_model_and_short_key_rejected(client):
    admin = staff("admin")
    assert save(admin, "mistral", "", "longenoughkey").json()["detail"]["code"] == "ai_provider_invalid"
    assert save(admin, "openai", "bad model!", "longenoughkey").json()["detail"]["code"] == "ai_model_invalid"
    assert save(admin, "openai", "", "short").json()["detail"]["code"] == "ai_key_invalid"


def test_only_staff_can_read_or_change_ai_config(client):
    signup(client, "plain@example.com")
    assert client.get("/api/admin/ai-config").status_code == 403
    assert save(client).status_code == 403
    assert staff("coordinator").get("/api/admin/ai-config").status_code == 200


class Capture:
    def __init__(self, payload=None):
        self.calls, self.payload = [], payload or {"summary": "ok"}

    def __call__(self, request):
        self.calls.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(self.payload)}}]})


@pytest.mark.parametrize("provider,base", [
    ("openai", "https://api.openai.com/v1/chat/completions"),
    ("deepseek", "https://api.deepseek.com/v1/chat/completions"),
    ("gemini", "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"),
])
def test_dynamic_base_url_and_bearer_auth(client, provider, base):
    admin = staff("admin")
    key = f"{provider}-secret-key-42"
    assert save(admin, provider, "", key).status_code == 200
    cap = Capture()
    llm.set_transport(httpx.MockTransport(cap))
    try:
        assert llm.chat_json("sys", "user") == {"summary": "ok"}
    finally:
        llm.set_transport(None)
    req = cap.calls[0]
    assert str(req.url) == base
    assert req.headers["authorization"] == f"Bearer {key}"
    body = json.loads(req.content)
    assert body["model"] == llm.DEFAULT_MODELS[provider]
    assert ("response_format" in body) == (provider != "gemini")


def test_ai_service_prefers_db_config_over_env(client, monkeypatch):
    admin = staff("admin")
    save(admin, "deepseek", "deepseek-chat", "db-secret-key-77")
    monkeypatch.setattr(settings, "ai_enabled", False)
    monkeypatch.setattr(settings, "ai_api_key", "")
    assert ai.availability() is None  # DB config hi kaafi hai
    cap = Capture({"summary": "from db"})
    ai.set_transport(httpx.MockTransport(cap))
    try:
        assert ai.generate_json("prompt") == {"summary": "from db"}
    finally:
        ai.set_transport(None)
    assert str(cap.calls[0].url) == "https://api.deepseek.com/v1/chat/completions"


def test_no_db_config_keeps_legacy_env_fallback(client, monkeypatch):
    monkeypatch.setattr(settings, "ai_enabled", True)
    monkeypatch.setattr(settings, "ai_api_key", "legacy-key-123")
    cfg = llm.get_runtime_config()
    assert cfg is not None and cfg.source == "environment" and cfg.provider_name == "gemini"
    with Session(engine) as db:
        assert db.exec(select(AIProviderSettings)).first() is None
