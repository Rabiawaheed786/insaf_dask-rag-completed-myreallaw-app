# RAG pipeline (Phase 9): diagram se code tak

Maqsad: verified qanooni PDF se sawal ka jawab, source ke saath. Users ke apne masle is mein kabhi nahi jate.

| Diagram ka hissa | Code (app/rag.py) | Kya karta hai |
|---|---|---|
| PDF Document -> har page | `extract_pdf` | PyMuPDF se page ka text |
| `is_image` | `extract_pdf` (page.get_images) | page par tasveer hai ya nahi |
| `is_image == true` -> Pytesseract + OCR | `_ocr`, `ocr_available` | sirf tasveer wale pages par OCR; chhote logo (64px se kam) chhor diye jate hain |
| After Extraction: Text, Text in image | `PageData` | Data01 = text, Data02 = text in image |
| LLM: "keep only necessary data, no duplication" | `normalize_llm` (Gemini), warna `normalize_local` | duplicate hata kar saaf data. LLM ka jawab tab hi liya jata hai jab us ke saare lafz asli data mein hon (`faithful`), yani LLM naya qanooni matn nahi ghusa sakta |
| Data -> Embed | `chunk_text`, `embed` | tukray (900 harf, 120 overlap) phir vectors |
| VectorDB | `legal_chunks` table (SQLite + numpy) | vector, page, kind (text/image_text) aur source ke saath |
| User -> Similarity Search | `search` | sawal ka embedding, cosine similarity, top-k |
| LLM jawab | `ask` | sirf mile hue tukron se jawab, [1] [2] citations; LLM na ho to sirf milte julte tukray |

## Chalane ka tareeqa
1. Admin banayein (`uv run python -m app.cli make-admin email`), `/docs` mein login.
2. `POST /api/admin/legal-docs`: PDF, title, source_url (https), verified_on, attested=true.
   Ya CLI: `uv run python -m app.cli rag-ingest file.pdf --title "..." --source-url https://... --verified-on 2026-11-01 --attest`
3. Sawal: `POST /api/legal/ask` (login ke baad) ya `uv run python -m app.cli rag-ask "sawal"`.
4. Dekhein: `GET /api/admin/legal-docs`, `GET /api/legal/sources`.

## OCR (Tesseract) Windows par
Tesseract alag program hai (pip se nahi). Windows ke liye "Tesseract OCR UB Mannheim installer" install karein,
phir `.env` mein `TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe`. Install na ho to ingest chalta hai,
bas tasveer ka matn nahi parha jata (report mein `ocr_status: unavailable`). Urdu script ke liye `urd` language data aur `OCR_LANG=urd+eng`
(maine sirf English OCR test kiya hai).

## Embedding: do option
- `RAG_EMBEDDER=local` (default): offline, bina key; lafzon ki milawat dhoondta hai. Roman Urdu sawal Roman Urdu document se milta hai;
  English document se nahi (hum-maani lafz ya zubaan ka farq nahi samajhta).
- `RAG_EMBEDDER=gemini`: matlab ki milawat (zubaanon ke aar-paar), key aur `AI_ENABLED=true` chahiye. Sawal bahar jata hai, is liye
  user ki ijazat (`consent`) zaroori hai aur free key production mein band hai. Embedder badalne ke baad `POST /api/admin/legal-docs/reindex`.
  Maine isay nakli Gemini se test kiya hai, asli Google se nahi: model ka name (`EMBED_MODEL`) aur hadd (`RAG_MIN_SCORE`, default 0.55) aap ko asli data par tune karni hongi.

## Hadden (sach)
- Vector store SQLite + numpy hai (hazaron tukron tak theek). Bohat bara data ho to pgvector/FAISS/Chroma: `search` aur `ingest_pdf` hi badalne hain.
- LLM ke jawab mein galti ho sakti hai; is liye har jawab ke saath sources (page, link, tareekh) aur disclaimer aata hai, aur jawab sirf mile hue tukron tak mehdood hone ko kaha jata hai (is ki guarantee nahi).
- Library ka asli kaam insani hai: sirf official source ke PDF, admin ki tasdeeq ke saath. Galat ya purana document galat jawab dega.
- PDF ke andar likhi hidayat (prompt injection) se bachne ke liye LLM ko data ko "data" batane ki hidayat hai, lekin yeh mukammal hifazat nahi.
