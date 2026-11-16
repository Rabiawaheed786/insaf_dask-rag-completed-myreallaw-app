"""Dynamic Chat Completion service (Admin BYOK).

Active provider DB se aata hai; key sirf memory mein decrypt hoti hai. Agar DB config
mojood na ho to legacy env fallback chalta hai, taake local tests bina provider ke pass hon.
"""
import json
from dataclasses import dataclass

import httpx
from sqlmodel import Session

from ..config import settings
from ..crypto import decrypt_secret
from ..models import AIProviderSettings, User

PROVIDER_BASE_URLS = {
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai",
    "openai": "https://api.openai.com/v1",
    "deepseek": "https://api.deepseek.com/v1",
}
DEFAULT_MODELS = {
    "gemini": "gemini-3.8-flash",
    "openai": "gpt-4o-mini",
    "deepseek": "deepseek-chat",
}
PROVIDERS = tuple(PROVIDER_BASE_URLS)

_transport = None  # tests mein MockTransport


class LLMError(Exception):
    pass


@dataclass(frozen=True)
class ActiveConfig:
    provider_name: str
    model_name: str
    api_key: str
    source: str  # database | environment


def set_transport(t) -> None:
    global _transport
    _transport = t


def mask_key(key: str) -> str:
    key = (key or "").strip()
    if not key:
        return ""
    if len(key) <= 8:
        return "*" * 4
    return f"{key[:3]}...{key[-4:]}"


def _row_config(db: Session) -> ActiveConfig | None:
    try:
        row = db.get(AIProviderSettings, 1)
    except Exception:  # migration se pehle table na ho to env fallback
        return None
    if not row or row.provider_name not in PROVIDER_BASE_URLS:
        return None
    key = decrypt_secret(row.encrypted_api_key)
    model = (row.model_name or DEFAULT_MODELS[row.provider_name]).strip()
    if not key or not model:
        return None
    return ActiveConfig(row.provider_name, model, key, "database")


def get_active_config(db: Session | None = None) -> ActiveConfig | None:
    if db is not None:
        return _row_config(db)
    try:
        from ..db import engine
        with Session(engine) as own:
            return _row_config(own)
    except Exception:
        return None


def get_env_config() -> ActiveConfig | None:
    if settings.ai_enabled and settings.ai_api_key:
        return ActiveConfig("gemini", settings.ai_model or DEFAULT_MODELS["gemini"],
                            settings.ai_api_key, "environment")
    return None


def get_runtime_config() -> ActiveConfig | None:
    return get_active_config() or get_env_config()


def is_ready() -> bool:
    return get_runtime_config() is not None


def get_user_gemini_key(db: Session, user_id: int) -> str:
    try:
        row = db.get(User, user_id)
    except Exception:  # purana DB jismein nayi column nahi
        return ""
    return decrypt_secret(getattr(row, "encrypted_gemini_key", "") or "") if row else ""


def get_user_config(db: Session, user_id: int) -> ActiveConfig | None:
    key = get_user_gemini_key(db, user_id)
    if not key:
        return None
    model = (settings.ai_model or DEFAULT_MODELS["gemini"]).strip()
    return ActiveConfig("gemini", model, key, "user")


def get_config_for_user(db: Session, user_id: int) -> ActiveConfig | None:
    """User ki apni key pehle; warna admin ki DB config; warna .env fallback."""
    return get_user_config(db, user_id) or get_active_config(db) or get_env_config()


def is_ready_for_user(db: Session, user_id: int) -> bool:
    return get_config_for_user(db, user_id) is not None


def availability_for_user(db: Session, user_id: int, category: str | None = None) -> str | None:
    if get_user_config(db, user_id) is not None:
        return "ai_not_for_category" if category == "children" else None
    return availability_reason(category)


def mask_user_key(key: str) -> str:
    key = (key or "").strip()
    if not key:
        return ""
    return "AIza•••••••" if key.startswith("AIza") else "•••••••"


def availability_reason(category: str | None = None) -> str | None:
    """None = AI ready. DB config admin ka faisla hai; env fallback purani settings maanta hai."""
    if get_active_config() is None:
        if not settings.ai_enabled:
            return "ai_disabled"
        if not settings.ai_api_key:
            return "ai_no_key"
        if settings.ai_tier != "paid" and settings.app_env != "development":
            return "ai_free_tier_blocked"
    if category == "children":
        return "ai_not_for_category"
    return None


def _parse_json(text: str) -> dict:
    text = str(text or "").strip()
    if text.startswith("```"):
        text = text.strip("`").strip()
        if text.lower().startswith("json"):
            text = text[4:].strip()
    out = json.loads(text)
    if not isinstance(out, dict):
        raise ValueError("not an object")
    return out


def chat_json(system: str, user_prompt: str, cfg: ActiveConfig | None = None) -> dict:
    cfg = cfg or get_runtime_config()
    if not cfg:
        raise LLMError("NotConfigured")
    base = PROVIDER_BASE_URLS.get(cfg.provider_name)
    if not base:
        raise LLMError("UnknownProvider")
    body = {
        "model": cfg.model_name,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user_prompt}],
        "temperature": 0.2,
        "max_tokens": 4096,
    }
    if cfg.provider_name != "gemini":  # Gemini compatibility endpoint har model par isay accept nahi karta
        body["response_format"] = {"type": "json_object"}
    try:
        with httpx.Client(timeout=settings.ai_timeout_seconds, transport=_transport) as c:
            r = c.post(f"{base.rstrip('/')}/chat/completions", json=body,
                       headers={"Authorization": f"Bearer {cfg.api_key}"})
        r.raise_for_status()
        return _parse_json(r.json()["choices"][0]["message"]["content"])
    except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as e:
        raise LLMError(type(e).__name__) from None
