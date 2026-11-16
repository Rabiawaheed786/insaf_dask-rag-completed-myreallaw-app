"""Knowledge Base flow: profile update, strict isolation, upload, chunk edit, scoped chat, widget."""
import json

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app import ai, rag
from app.config import settings
from app.db import engine
from app.main import app
from app.models import KnowledgeChunk
from tests.conftest import signup
from tests.test_rag import KEY, FakeAI, ai_on, make_pdf
from tests.test_rag import TENANCY

DOC = "A landlord cannot evict a tenant without a court order. The tenant must receive written notice in advance."


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


def other_client(email):
    c = TestClient(app)
    assert signup(c, email).status_code == 201
    return c


def new_kb(c, title="Legal Doc", prompt=""):
    r = c.post("/api/kb", json={"title": title, "system_prompt": prompt})
    assert r.status_code == 201, r.text
    return r.json()


def upload(c, kb_id, text=DOC):
    return c.post(f"/api/kb/{kb_id}/upload", data={"consent": "true"},
                  files={"file": ("doc.pdf", make_pdf([(text, None)]), "application/pdf")})


# ---------------- profile ----------------
def test_profile_update_is_login_protected_and_validated(client):
    assert client.put("/api/auth/me", json={"display_name": "X"}).status_code == 401
    signup(client)
    r = client.put("/api/auth/me", json={"display_name": "Farah Khan", "email": "farah.new@example.com"})
    assert r.status_code == 200 and r.json()["display_name"] == "Farah Khan" and r.json()["email"] == "farah.new@example.com"
    assert client.put("/api/auth/me", json={"email": "bad"}).status_code == 422
    assert client.put("/api/auth/me", json={"display_name": "x" * 81}).status_code == 422
    other_client("taken@example.com")
    assert client.put("/api/auth/me", json={"email": "taken@example.com"}).status_code == 409
    assert client.get("/api/auth/me").json()["display_name"] == "Farah Khan"


# ---------------- CRUD + isolation ----------------
def test_kb_crud_and_owner_isolation(client):
    signup(client)
    kb = new_kb(client, "Legal Doc", "Answer in simple words.")
    assert kb["chunks"] == 0 and kb["embed_token"]
    assert client.get("/api/kb").json()["knowledge_bases"][0]["title"] == "Legal Doc"

    other = other_client("other@example.com")
    assert other.get("/api/kb").json()["knowledge_bases"] == []
    for method, path, body in (("get", f"/api/kb/{kb['id']}", None), ("put", f"/api/kb/{kb['id']}", {"title": "Hack"}),
                               ("delete", f"/api/kb/{kb['id']}", None), ("get", f"/api/kb/{kb['id']}/chunks", None),
                               ("post", f"/api/kb/{kb['id']}/chat", {"question": "landlord evict tenant"})):
        r = getattr(other, method)(path, json=body) if body is not None else getattr(other, method)(path)
        assert r.status_code == 404, (method, path, r.text)

    r = client.put(f"/api/kb/{kb['id']}", json={"system_prompt": "Only use my documents."})
    assert r.status_code == 200 and r.json()["system_prompt"] == "Only use my documents."
    assert client.post("/api/kb", json={"title": ""}).status_code == 422
    assert client.put(f"/api/kb/{kb['id']}", json={"system_prompt": "x" * 4001}).status_code == 422
    assert client.delete(f"/api/kb/{kb['id']}").json()["deleted"] is True
    assert client.get("/api/kb").json()["knowledge_bases"] == []


# ---------------- upload + chunks ----------------
def test_upload_tags_vectors_with_user_and_kb_and_edit_keeps_chunk_id(client):
    signup(client)
    kb = new_kb(client)
    r = upload(client, kb["id"])
    assert r.status_code == 201 and r.json()["chunks"] >= 1, r.text
    chunks = client.get(f"/api/kb/{kb['id']}/chunks").json()["chunks"]
    assert chunks and "court order" in chunks[0]["text"]
    with Session(engine) as db:
        rows = db.exec(select(KnowledgeChunk)).all()
        assert rows and all(c.user_id == client.get("/api/auth/me").json()["id"] and c.kb_id == kb["id"] for c in rows)
        old_id, old_vec = rows[0].id, rows[0].embedding

    target = chunks[0]["chunk_id"]
    r = client.put(f"/api/kb/{kb['id']}/chunks/{target}",
                   json={"text": "The tenant must get written notice before any eviction."})
    assert r.status_code == 200 and r.json()["chunk_id"] == target
    edited = [c for c in client.get(f"/api/kb/{kb['id']}/chunks").json()["chunks"] if c["chunk_id"] == target][0]
    assert edited["text"].startswith("The tenant must get written notice")
    with Session(engine) as db:
        row = db.get(KnowledgeChunk, old_id)
        assert row.text.startswith("The tenant must get written notice") and row.embedding != old_vec
    assert client.put(f"/api/kb/{kb['id']}/chunks/{target}", json={"text": " "}).status_code == 422
    assert client.delete(f"/api/kb/{kb['id']}/chunks/{target}").json()["deleted"] is True
    assert all(c["chunk_id"] != target for c in client.get(f"/api/kb/{kb['id']}/chunks").json()["chunks"])


def test_upload_rejects_non_pdf(client):
    signup(client)
    kb = new_kb(client)
    r = client.post(f"/api/kb/{kb['id']}/upload", files={"file": ("x.pdf", b"not a pdf", "application/pdf")})
    assert r.status_code == 422


# ---------------- chat ----------------
def test_chat_searches_only_selected_kb(client):
    signup(client)
    tenancy = new_kb(client, "Tenancy")
    other = new_kb(client, "Other")
    assert upload(client, tenancy["id"], DOC).status_code == 201
    assert upload(client, other["id"], "The security deposit must be returned when the tenant vacates.").status_code == 201
    j = client.post(f"/api/kb/{tenancy['id']}/chat", json={"question": "Can a landlord evict without a court order?"}).json()
    assert j["found"] is True and j["sources"] and j["sources"][0]["snippet"].startswith("A landlord cannot evict")
    assert all(s["chunk_id"] for s in j["sources"])
    empty = new_kb(client, "Empty")
    assert client.post(f"/api/kb/{empty['id']}/chat", json={"question": "anything here at all"}).json()["found"] is False
    assert client.post(f"/api/kb/{tenancy['id']}/chat", json={"question": "ab"}).status_code == 422


def test_chat_passes_saved_system_prompt_to_llm(client, monkeypatch):
    signup(client)
    kb = new_kb(client, "Tenancy", "Answer only in simple words and cite the chunk.")
    assert upload(client, kb["id"], DOC).status_code == 201
    fake = ai_on(monkeypatch, FakeAI(answer=lambda p: {"answer": "A court order is required [1].", "used": [1]}))
    j = client.post(f"/api/kb/{kb['id']}/chat",
                    json={"question": "Can a landlord evict without a court order?", "consent": True}).json()
    assert j["llm_used"] is True and j["answer"].endswith("[1].") and [s["n"] for s in j["sources"]] == [1]
    body = json.loads(fake.calls[-1].content)
    system = body["systemInstruction"]["parts"][0]["text"]
    assert "Answer only in simple words and cite the chunk." in system and "ONLY the numbered SOURCES" in system


# ---------------- widget ----------------
def test_widget_requires_token_and_is_cors_enabled(client):
    signup(client)
    kb = new_kb(client)
    assert upload(client, kb["id"], DOC).status_code == 201
    payload = {"question": "Can a landlord evict without a court order?"}
    bad = client.post(f"/api/widget/{kb['id']}/chat", json=payload, headers={"X-Kb-Token": "wrong"})
    assert bad.status_code == 404
    good = client.post(f"/api/widget/{kb['id']}/chat", json=payload, headers={"X-Kb-Token": kb["embed_token"]})
    assert good.status_code == 200 and good.json()["found"] is True
    assert good.headers["access-control-allow-origin"] == "*"
    pre = client.options(f"/api/widget/{kb['id']}/chat")
    assert pre.status_code == 204 and pre.headers["access-control-allow-methods"].startswith("POST")
