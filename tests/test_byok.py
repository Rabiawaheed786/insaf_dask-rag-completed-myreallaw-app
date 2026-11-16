"""Per-user Gemini key (BYOK): masked storage aur RAG mein user key ki tarjeeh."""
import json

import httpx
import pytest
from sqlmodel import Session, select

from app import ai, rag
from app.config import settings
from app.db import engine
from app.models import AuditLog, User
from tests.conftest import signup
from tests.test_rag import make_pdf

KEY = "AIzaTESTKEY1234567890"
DOC = "A landlord cannot evict a tenant without a court order. The tenant must receive written notice."


@pytest.fixture(autouse=True)
def reset(monkeypatch):
    rag.set_ocr(None)
    ai.set_transport(None)
    monkeypatch.setattr(settings, "rag_embedder", "local")
    monkeypatch.setattr(settings, "ai_enabled", False)
    monkeypatch.setattr(settings, "ai_api_key", "")
    yield
    rag.set_ocr(None)
    ai.set_transport(None)


def test_key_is_login_protected_masked_encrypted_and_clearable(client):
    assert client.get("/api/me/gemini-key").status_code == 401
    signup(client)

    r = client.put("/api/me/gemini-key", json={"api_key": KEY})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["configured"] is True and body["masked"] == "AIza•••••••" and body["updated_at"]
    assert KEY not in r.text and client.get("/api/me/gemini-key").text.find(KEY) == -1

    with Session(engine) as db:
        user = db.exec(select(User)).first()
        assert user.encrypted_gemini_key and KEY not in user.encrypted_gemini_key
        assert db.exec(select(AuditLog).where(AuditLog.action == "gemini_key_saved")).one().detail == ""

    assert client.put("/api/me/gemini-key", json={"api_key": "sk-not-gemini"}).status_code == 422
    assert client.put("/api/me/gemini-key", json={"api_key": " "}).json()["configured"] is False
    assert client.get("/api/me/gemini-key").json()["masked"] == ""


class KeyFake:
    def __init__(self):
        self.keys = []
        self.chat_calls = 0

    def __call__(self, request: httpx.Request):
        self.keys.append(request.headers.get("x-goog-api-key") or request.headers.get("authorization"))
        if ":batchEmbedContents" in str(request.url):
            reqs = json.loads(request.content)["requests"]
            return httpx.Response(200, json={"embeddings": [
                {"values": rag._local_vec(r["content"]["parts"][0]["text"]).tolist()} for r in reqs]})
        self.chat_calls += 1
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(
            {"answer": "A court order is required [1].", "used": [1]})}}]})


def test_user_key_powers_upload_chat_and_widget_without_server_key(client, monkeypatch):
    monkeypatch.setattr(settings, "rag_embedder", "gemini")
    monkeypatch.setattr(settings, "rag_min_score", 0.0)  # hash vectors: cosine threshold se neeche reh sakta hai
    signup(client)
    assert client.put("/api/me/gemini-key", json={"api_key": KEY}).status_code == 200
    assert client.get("/api/ai/status").json()["available"] is True

    fake = KeyFake()
    ai.set_transport(httpx.MockTransport(fake))
    kb = client.post("/api/kb", json={"title": "Tenancy"}).json()
    up = client.post(f"/api/kb/{kb['id']}/upload", data={"consent": "true"},
                     files={"file": ("doc.pdf", make_pdf([(DOC, None)]), "application/pdf")})
    assert up.status_code == 201, up.text

    j = client.post(f"/api/kb/{kb['id']}/chat",
                    json={"question": "Can a landlord evict without a court order?", "consent": True}).json()
    assert j["llm_used"] is True and j["answer"].endswith("[1].")
    w = client.post(f"/api/widget/{kb['id']}/chat",
                    json={"question": "Can a landlord evict without a court order?"},
                    headers={"X-Kb-Token": kb["embed_token"]})
    assert w.status_code == 200 and w.json()["llm_used"] is True

    assert fake.chat_calls >= 2  # KB chat + widget chat
    assert all(k == KEY or k == f"Bearer {KEY}" for k in fake.keys)
