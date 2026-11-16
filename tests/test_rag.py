"""RAG pipeline ke tests (diagram: PDF -> text/OCR -> normalize -> embed -> VectorDB -> similarity -> LLM)."""
import json
import re

import httpx
import numpy as np
import pymupdf
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app import ai, cli, rag
from app.config import settings
from app.db import engine
from app.main import app
from app.models import AuditLog, LegalChunk, LegalDocument
from tests.conftest import signup
from tests.test_phase5 import admin_client

KEY = "RAG-TEST-KEY-123"
TENANCY = ["A landlord cannot evict a tenant without a court order. The tenant must receive written notice. "
           "Rent disputes are heard by the Rent Controller.", "The security deposit must be returned when the tenant vacates the property."]
INHERIT = ["Inheritance of property is divided among legal heirs according to personal law. A succession certificate may be "
           "obtained from the civil court. Sons and daughters inherit shares of the estate."]
CYBER = ["Online fraud and hacking should be reported to the cybercrime agency. Keep screenshots, transaction numbers and "
         "messages as evidence."]
URDU = ["Najaiz qabza hone par police aur adalat se rujoo karein. Malkiyat ke kaghzat aur registry saath rakhein."]


def make_pdf(pages: list[tuple[str, str | None]]) -> bytes:
    """pages: [(text, image_text|None)]. image_text wala safha: matn ki tasveer (PNG) pdf mein lagi hoti hai."""
    doc = pymupdf.open()
    for text, img_text in pages:
        page = doc.new_page()
        if text:
            page.insert_textbox(pymupdf.Rect(50, 50, 550, 400), text, fontsize=11)
        if img_text:
            tmp = pymupdf.open()
            tp = tmp.new_page(width=480, height=120)
            tp.insert_text((10, 70), img_text, fontsize=26)
            png = tp.get_pixmap(dpi=150).tobytes("png")
            page.insert_image(pymupdf.Rect(50, 450, 530, 570), stream=png)
    return doc.tobytes()


def upload(admin, pdf, title="Test Guide", **kw):
    data = {"title": title, "source_url": "https://example.gov.pk/guide", "verified_on": "2026-11-01", "attested": "true", **kw}
    return admin.post("/api/admin/legal-docs", data=data, files={"file": ("guide.pdf", pdf, "application/pdf")})


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


@pytest.fixture()
def corpus(client):
    """admin + user; 4 verified documents."""
    admin = admin_client()
    for title, pages in (("Tenancy Guide", TENANCY), ("Inheritance Guide", INHERIT), ("Cyber Crime Guide", CYBER), ("Qabza Guide", URDU)):
        assert upload(admin, make_pdf([(p, None) for p in pages]), title).status_code == 201
    user = TestClient(app)
    signup(user, "reader@example.com")
    return admin, user


def ask(user, q, **kw):
    return user.post("/api/legal/ask", json={"question": q, **kw})


# ---------------- 1. extraction: text + is_image + OCR ----------------
def test_extraction_detects_image_pages_and_runs_ocr_only_there():
    calls = []
    rag.set_ocr(lambda b: (calls.append(len(b)), "Python programming")[1])
    pages, status = rag.extract_pdf(make_pdf([("Python is programming language", "x"), ("Page two text only", None)]))
    assert [(p.page, p.is_image) for p in pages] == [(1, True), (2, False)]
    assert "Python is programming language" in pages[0].text and pages[0].image_text == "Python programming"
    assert pages[1].image_text == "" and len(calls) == 1 and status == "ok"


def test_missing_ocr_never_breaks_extraction(monkeypatch):
    monkeypatch.setattr(rag, "ocr_available", lambda: False)
    pages, status = rag.extract_pdf(make_pdf([("Some text here", "image words")]))
    assert pages[0].is_image and pages[0].image_text == "" and "Some text" in pages[0].text and status == "unavailable"
    assert rag.extract_pdf(make_pdf([("No images at all", None)]))[1] == "not_needed"
    for bad in (b"not a pdf", b""):
        with pytest.raises(rag.RagError):
            rag.extract_pdf(bad)


@pytest.mark.skipif(not rag.ocr_available(), reason="Tesseract install nahi")
def test_real_tesseract_reads_text_inside_an_image():
    pages, status = rag.extract_pdf(make_pdf([("Heading of the page", "Unlawful assembly is prohibited")]))
    assert status == "ok" and "unlawful" in pages[0].image_text.lower() and "assembly" in pages[0].image_text.lower()


# ---------------- 2. normalize: duplication nahi ----------------
def test_local_normalization_removes_image_text_already_in_page_text():
    text = "Python is programming language\n  Second   line  "
    t, i = rag.normalize_local(text, "Python is programming language\nPython programming\n\nSecond line")
    assert t == "Python is programming language\nSecond line" and i == "Python programming"


class FakeAI:
    def __init__(self, norm=None, answer=None, fail=False):
        self.norm, self.answer, self.fail, self.calls = norm, answer, fail, []

    def __call__(self, request: httpx.Request):
        self.calls.append(request)
        body = json.loads(request.content)
        if ":batchEmbedContents" in str(request.url):
            reqs = body["requests"]
            return httpx.Response(200, json={"embeddings": [{"values": rag._local_vec(r["content"]["parts"][0]["text"]).tolist()} for r in reqs]})
        if self.fail:
            return httpx.Response(500, json={})
        prompt = body["contents"][0]["parts"][0]["text"]
        out = self.norm(prompt) if "DATA01" in prompt else self.answer(prompt)
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": json.dumps(out)}]}}]})


def ai_on(monkeypatch, fake):
    monkeypatch.setattr(settings, "ai_enabled", True)
    monkeypatch.setattr(settings, "ai_api_key", KEY)
    monkeypatch.setattr(settings, "ai_tier", "free")
    monkeypatch.setattr(settings, "app_env", "development")
    ai.set_transport(httpx.MockTransport(fake))
    return fake


def test_llm_normalization_is_used_when_faithful_and_rejected_when_it_invents(monkeypatch):
    ai_on(monkeypatch, FakeAI(norm=lambda p: {"text": "Python is programming language", "text_in_image": "Python programming"}))
    assert rag.normalize_llm("Python is programming language", "Python is programming language\nPython programming") == \
        ("Python is programming language", "Python programming")
    ai_on(monkeypatch, FakeAI(norm=lambda p: {"text": "Python is programming language", "text_in_image": "Section 302 imposes death penalty"}))
    assert rag.normalize_llm("Python is programming language", "Python programming") is None  # naya qanooni matn ghusa
    ai_on(monkeypatch, FakeAI(fail=True))
    assert rag.normalize_llm("a b c", "d e f") is None  # LLM nakam: None (local istemal hoga)
    monkeypatch.setattr(settings, "ai_enabled", False)
    assert rag.normalize_llm("a", "b") is None


def test_ingest_falls_back_to_local_when_llm_invents_text(client, monkeypatch):
    ai_on(monkeypatch, FakeAI(norm=lambda p: {"text": "Fake invented law section 999", "text_in_image": ""}))
    rag.set_ocr(lambda b: "Python programming")
    admin = admin_client()
    r = upload(admin, make_pdf([("Python is programming language", "x")]))
    assert r.status_code == 201 and r.json()["normalized_by_llm"] == 0 and r.json()["normalized_locally"] == 1
    with Session(engine) as db:
        assert not any("invented" in c.text for c in db.exec(select(LegalChunk)).all())


# ---------------- 3. chunking ----------------
def test_chunking_overlap_boundaries_and_edge_cases():
    words = " ".join(f"word{i}" for i in range(400))
    chunks = rag.chunk_text(words, size=300, overlap=60)
    assert len(chunks) > 5 and all(len(c) <= 300 for c in chunks)
    assert all(not c.startswith(" ") and not c.endswith(" ") for c in chunks)
    assert chunks[0].split()[-1] in chunks[1]  # overlap: pichla lafz agle tukray mein bhi
    assert " ".join(dict.fromkeys(" ".join(chunks).split())) == words  # kuch gum nahi
    assert rag.chunk_text("short") == ["short"] and rag.chunk_text("   ") == []


# ---------------- 4. embedding ----------------
def test_local_embedding_is_deterministic_normalized_and_meaningful():
    a, b, c = rag.embed(["landlord cannot evict tenant", "landlord cannot evict a tenant without notice", "recipe for chicken biryani"])
    assert np.allclose(rag.embed(["landlord cannot evict tenant"])[0], a) and abs(np.linalg.norm(a) - 1) < 1e-5
    assert float(a @ b) > 0.5 > float(a @ c) and float(a @ c) < 0.15
    assert rag.embed([]).shape == (0, rag.DIM)


# ---------------- 5/6. vector store + similarity ----------------
def test_similarity_search_ranks_the_right_document_first(corpus):
    with Session(engine) as db:
        for q, title in (("can my landlord evict me without a court order", "Tenancy Guide"),
                         ("how do daughters inherit property shares", "Inheritance Guide"),
                         ("where to report online fraud with screenshots", "Cyber Crime Guide"),
                         ("mere plot par najaiz qabza hai kya karun", "Qabza Guide")):
            hits = rag.search(db, q)
            assert hits[0].doc.title == title and hits[0].score >= rag.min_score(), (q, [(h.doc.title, round(h.score, 2)) for h in hits])
        assert all(h.score < rag.min_score() for h in rag.search(db, "recipe for chicken biryani with rice"))


def test_only_verified_documents_and_deleted_documents_are_searched(corpus):
    admin, user = corpus
    with Session(engine) as db:
        d = db.exec(select(LegalDocument).where(LegalDocument.title == "Tenancy Guide")).one()
        d.status = "suspended"
        db.add(d)
        db.commit()
        assert all(h.doc.title != "Tenancy Guide" for h in rag.search(db, "landlord evict tenant court order"))
        d.status = "verified"
        db.add(d)
        db.commit()
        did = d.id
    assert admin.delete(f"/api/admin/legal-docs/{did}").status_code == 200
    with Session(engine) as db:
        assert all(h.doc.title != "Tenancy Guide" for h in rag.search(db, "landlord evict tenant court order"))
        assert not db.exec(select(LegalChunk).where(LegalChunk.document_id == did)).all()


# ---------------- 7. user ka sawal: API ----------------
def test_ask_without_llm_returns_closest_passages_with_sources(corpus):
    admin, user = corpus
    r = ask(user, "Can my landlord evict me without a court order?")
    j = r.json()
    assert r.status_code == 200 and j["found"] is True and j["llm_used"] is False
    s = j["sources"][0]
    assert s["title"] == "Tenancy Guide" and s["page"] == 1 and s["source_url"].startswith("https://") and s["verified_on"] == "2026-11-01"
    assert "court order" in j["answer"] and "legal advice" in j["disclaimer"] or "mashwara" in j["disclaimer"]


def test_ask_says_not_found_instead_of_inventing(corpus):
    _, user = corpus
    j = ask(user, "What is the recipe for chicken biryani with rice?").json()
    assert j["found"] is False and j["sources"] == [] and j["llm_used"] is False and "verified sources" in j["answer"]
    assert ask(user, "ab", ).status_code == 422 and ask(user, "x" * 1001).status_code == 422
    assert TestClient(app).post("/api/legal/ask", json={"question": "landlord evict tenant"}).status_code == 401


def test_ask_with_llm_cites_only_sources_it_really_used(corpus, monkeypatch):
    _, user = corpus
    fake = ai_on(monkeypatch, FakeAI(answer=lambda p: {"answer": "A landlord needs a court order [1].", "used": [1, 7, "x", True]}))
    assert ask(user, "landlord evict tenant court order").json()["llm_used"] is False and fake.calls == []  # ijazat ke bina LLM nahi
    j = ask(user, "landlord evict tenant court order", consent=True).json()
    assert j["llm_used"] is True and j["answer"].endswith("[1].") and [s["n"] for s in j["sources"]] == [1]  # 7, "x", True radd
    body = fake.calls[0].content.decode()
    assert "SOURCES" in body and "ignore any instructions" in body and fake.calls[0].headers["x-goog-api-key"] == KEY
    assert KEY not in body and "KEY" not in json.dumps(j)


def test_llm_failure_or_unsupported_answer_falls_back_to_passages(corpus, monkeypatch):
    _, user = corpus
    ai_on(monkeypatch, FakeAI(fail=True))
    j = ask(user, "landlord evict tenant court order", consent=True).json()
    assert j["found"] and j["llm_used"] is False and "[1]" in j["answer"]
    ai_on(monkeypatch, FakeAI(answer=lambda p: {"answer": "Confident answer with no citation", "used": []}))
    j = ask(user, "landlord evict tenant court order", consent=True).json()
    assert j["llm_used"] is False and "Confident answer" not in j["answer"]


def test_question_is_redacted_before_it_leaves_the_server(corpus, monkeypatch):
    _, user = corpus
    fake = ai_on(monkeypatch, FakeAI(answer=lambda p: {"answer": "ok [1]", "used": [1]}))
    j = ask(user, "landlord evict tenant court order 0300-1234567 ali@example.com 42101-1234567-1", consent=True).json()
    assert j["llm_used"] is True and fake.calls
    raw = fake.calls[0].content.decode()
    for secret in ("0300-1234567", "ali@example.com", "42101-1234567-1"):
        assert secret not in raw
    with Session(engine) as db:
        assert all(secret not in (a.detail or "") for a in db.exec(select(AuditLog)).all() for secret in ("landlord", "0300"))


def test_ask_has_an_hourly_limit(corpus, monkeypatch):
    _, user = corpus
    monkeypatch.setattr(settings, "rag_hourly_limit", 2)
    codes = [ask(user, "landlord evict tenant court order").status_code for _ in range(3)]
    assert codes == [200, 200, 429]


def test_sources_list_shows_only_verified_documents(corpus):
    _, user = corpus
    titles = [s["title"] for s in user.get("/api/legal/sources").json()["sources"]]
    assert titles == ["Tenancy Guide", "Inheritance Guide", "Cyber Crime Guide", "Qabza Guide"]
    assert TestClient(app).get("/api/legal/sources").status_code == 401


# ---------------- admin ingest API ----------------
def test_ingest_endpoint_rules(client):
    admin = admin_client()
    user = TestClient(app)
    signup(user, "plain@example.com")
    pdf = make_pdf([(TENANCY[0], None)])
    assert upload(user, pdf).status_code == 403 and upload(TestClient(app), pdf).status_code in (401, 403)
    assert upload(admin, pdf, attested="false").status_code == 422
    assert upload(admin, pdf, source_url="http://insecure.example").status_code == 422
    assert upload(admin, pdf, verified_on="kal").status_code == 422
    assert upload(admin, pdf, title="x").status_code == 422
    assert upload(admin, b"%PDF-broken garbage").status_code == 422 and upload(admin, b"just text").status_code == 422
    assert upload(admin, make_pdf([("", None)])).status_code == 422  # matn nahi
    ok = upload(admin, pdf)
    assert ok.status_code == 201 and ok.json()["pages"] == 1 and ok.json()["chunks"] >= 1 and ok.json()["embedder"] == "local-hash-512"
    assert upload(admin, pdf, title="Same file again").status_code == 409  # duplicate
    docs = admin.get("/api/admin/legal-docs").json()["documents"]
    assert len(docs) == 1 and docs[0]["chunks"] == ok.json()["chunks"] and docs[0]["status"] == "verified"
    assert user.get("/api/admin/legal-docs").status_code == 403
    assert admin.delete("/api/admin/legal-docs/999").status_code == 404


def test_size_limit(client, monkeypatch):
    monkeypatch.setattr(settings, "rag_max_pdf_mb", 0)
    assert upload(admin_client(), make_pdf([(TENANCY[0], None)])).status_code == 422


def test_image_text_becomes_its_own_chunk_with_page_and_kind(client):
    rag.set_ocr(lambda b: "Python is programming language\nPython programming")
    admin = admin_client()
    r = upload(admin, make_pdf([("Python is programming language", "x")]))
    assert r.json()["pages_with_images"] == 1 and r.json()["ocr_pages"] == 1 and r.json()["image_chunks"] == 1
    with Session(engine) as db:
        kinds = sorted((c.kind, c.page, c.text) for c in db.exec(select(LegalChunk)).all())
    assert kinds == [("image_text", 1, "Python programming"), ("text", 1, "Python is programming language")]  # duplicate nahi


# ---------------- Gemini embedder + reindex ----------------
def test_gemini_embedder_needs_consent_and_reindex_after_switching(corpus, monkeypatch):
    admin, user = corpus  # chunks "local-hash-512" se bane
    fake = ai_on(monkeypatch, FakeAI(answer=lambda p: {"answer": "ok [1]", "used": [1]}))
    monkeypatch.setattr(settings, "rag_embedder", "gemini")
    monkeypatch.setattr(settings, "rag_min_score", 0.18)  # nakli Gemini local vectors deta hai: local wali hadd
    r = ask(user, "landlord evict tenant court order")
    assert r.status_code == 422 and r.json()["detail"]["code"] == "ai_consent_required"
    j = ask(user, "landlord evict tenant court order", consent=True).json()
    assert j["found"] is False  # purane local vectors naye embedder se nahi milte (galat milawat nahi)
    rr = admin.post("/api/admin/legal-docs/reindex")
    assert rr.status_code == 200 and rr.json()["embedder"] == "gemini:gemini-embedding-001" and rr.json()["reindexed"] >= 4
    batch = [c for c in fake.calls if ":batchEmbedContents" in str(c.url)]
    assert batch and json.loads(batch[-1].content)["requests"][0]["taskType"] == "RETRIEVAL_DOCUMENT"
    assert batch[-1].headers["x-goog-api-key"] == KEY and KEY not in str(batch[-1].url)
    j = ask(user, "landlord evict tenant court order", consent=True).json()
    assert j["found"] is True and j["sources"][0]["title"] == "Tenancy Guide" and j["embedder"].startswith("gemini:")
    q = [c for c in fake.calls if ":batchEmbedContents" in str(c.url)][-1]
    assert json.loads(q.content)["requests"][0]["taskType"] == "RETRIEVAL_QUERY"


def test_gemini_embedder_blocked_when_ai_off_or_free_tier_in_production(corpus, monkeypatch):
    _, user = corpus
    monkeypatch.setattr(settings, "rag_embedder", "gemini")
    monkeypatch.setattr(settings, "ai_enabled", True)
    monkeypatch.setattr(settings, "ai_api_key", KEY)
    monkeypatch.setattr(settings, "ai_tier", "free")
    monkeypatch.setattr(settings, "app_env", "production")
    r = ask(user, "landlord evict tenant court order", consent=True)
    assert r.status_code == 503 and r.json()["detail"]["code"] == "ai_free_tier_blocked"
    monkeypatch.setattr(settings, "ai_enabled", False)
    assert ask(user, "landlord evict tenant court order", consent=True).status_code == 503


# ---------------- restart aur CLI ----------------
def test_index_survives_restart(corpus):
    _, user = corpus
    engine.dispose()
    with TestClient(app) as fresh:
        fresh.post("/api/auth/login", json={"email": "reader@example.com", "password": "strongpass1"})
        assert fresh.post("/api/legal/ask", json={"question": "daughters inherit property shares"}).json()["sources"][0]["title"] == "Inheritance Guide"


def test_cli_ingest_and_ask(client, tmp_path, capsys):
    pdf = tmp_path / "guide.pdf"
    pdf.write_bytes(make_pdf([(TENANCY[0], None)]))
    args = ["rag-ingest", str(pdf), "--title", "CLI Guide", "--source-url", "https://example.gov.pk/c", "--verified-on", "2026-11-01"]
    assert cli.main(args) == 2  # --attest ke bagair nahi
    assert cli.main(args + ["--attest"]) == 0
    assert cli.main(["rag-ask", "can a landlord evict a tenant without a court order"]) == 0
    out = capsys.readouterr().out
    assert "CLI Guide" in out and "page 1" in out and "https://example.gov.pk/c" in out
