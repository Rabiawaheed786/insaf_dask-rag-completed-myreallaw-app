import hashlib
import re

import httpx
import numpy as np

from .config import settings
from .models import KnowledgeBase, KnowledgeChunk

_transport = None


class VectorStoreError(Exception):
    pass


def _request(method: str, path: str, body: dict | None = None, missing_ok: bool = False):
    try:
        with httpx.Client(timeout=settings.qdrant_timeout_seconds, transport=_transport) as client:
            response = client.request(method, settings.qdrant_url.rstrip("/") + path, json=body,
                                      headers={"api-key": settings.qdrant_api_key} if settings.qdrant_api_key else {})
        if missing_ok and response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()["result"]
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        raise VectorStoreError() from None


def namespace(kb: KnowledgeBase) -> str:
    identity = hashlib.sha256(kb.embed_token.encode()).hexdigest()[:16]
    return f"insaf_u{kb.user_id}_c{kb.id}_{identity}_"


def collection_name(kb: KnowledgeBase, embedder: str, dim: int) -> str:
    model = hashlib.sha256(embedder.encode()).hexdigest()[:16]
    return f"{namespace(kb)}{model}_{dim}"


def scope(kb: KnowledgeBase, chunk_id: int | None = None) -> dict:
    conditions = [{"key": "user_id", "match": {"value": kb.user_id}},
                  {"key": "collection_id", "match": {"value": kb.id}}]
    if chunk_id is not None:
        conditions.append({"key": "chunk_id", "match": {"value": chunk_id}})
    return {"must": conditions}


def ensure(kb: KnowledgeBase, embedder: str, dim: int | None):
    if not settings.qdrant_url:
        return
    name = collection_name(kb, embedder, dim) if dim else namespace(kb) + "pending"
    path = f"/collections/{name}"
    if _request("GET", path, missing_ok=True) is None:
        try:
            _request("PUT", path, {"vectors": {"size": dim, "distance": "Cosine"} if dim else {}})
        except VectorStoreError:
            # Another upload may have created the same scoped collection concurrently.
            if _request("GET", path, missing_ok=True) is None:
                raise


def upsert(kb: KnowledgeBase, chunks: list[KnowledgeChunk]):
    if not settings.qdrant_url or not chunks:
        return
    groups = {}
    for chunk in chunks:
        if chunk.user_id != kb.user_id or chunk.kb_id != kb.id:
            raise VectorStoreError()
        groups.setdefault((chunk.embedder, chunk.dim), []).append(chunk)
    for (embedder, dim), rows in groups.items():
        ensure(kb, embedder, dim)
        path = f"/collections/{collection_name(kb, embedder, dim)}/points?wait=true"
        for start in range(0, len(rows), 128):
            points = [{"id": c.id, "vector": np.frombuffer(c.embedding, dtype=np.float32).tolist(),
                       "payload": {"user_id": kb.user_id, "collection_id": kb.id, "kb_id": kb.id,
                                   "chunk_id": c.id, "embedder": c.embedder}}
                      for c in rows[start:start + 128]]
            _request("PUT", path, {"points": points})


def search(kb: KnowledgeBase, embedder: str, vector: np.ndarray) -> list[tuple[int, float]]:
    query_filter = scope(kb)
    query_filter["must"].append({"key": "embedder", "match": {"value": embedder}})
    result = _request("POST", f"/collections/{collection_name(kb, embedder, len(vector))}/points/query",
                      {"query": vector.tolist(), "filter": query_filter, "limit": settings.rag_top_k,
                       "with_payload": True, "with_vector": False})
    try:
        hits = []
        for point in result["points"]:
            payload = point["payload"]
            if (payload.get("user_id") == kb.user_id and payload.get("collection_id") == kb.id
                    and payload.get("embedder") == embedder and payload.get("chunk_id") == point["id"]):
                hits.append((int(point["id"]), float(point["score"])))
        return hits
    except (KeyError, TypeError, ValueError):
        raise VectorStoreError() from None


def delete_chunk(kb: KnowledgeBase, chunk: KnowledgeChunk):
    if not settings.qdrant_url:
        return
    path = f"/collections/{collection_name(kb, chunk.embedder, chunk.dim)}"
    if _request("GET", path, missing_ok=True) is not None:
        _request("POST", path + "/points/delete?wait=true", {"filter": scope(kb, chunk.id)})


def delete_collection(kb: KnowledgeBase):
    if not settings.qdrant_url:
        return
    result = _request("GET", "/collections")
    try:
        names = [item["name"] for item in result["collections"]
                 if re.fullmatch(re.escape(namespace(kb)) + r"(?:pending|[0-9a-f]{16}_[1-9][0-9]*)", item["name"])]
    except (KeyError, TypeError, AttributeError):
        raise VectorStoreError() from None
    for name in names:
        _request("DELETE", f"/collections/{name}", missing_ok=True)
