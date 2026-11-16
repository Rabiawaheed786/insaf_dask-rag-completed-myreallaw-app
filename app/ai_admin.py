"""Admin/coordinator AI provider settings. Key sirf encrypted save hoti hai aur response mein masked jati hai."""
import re

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel
from sqlmodel import Session

from .cases import require_coordinator
from .crypto import decrypt_secret, encrypt_secret
from .db import get_session
from .messages import fail
from .models import AIProviderSettings, AuditLog, User, utcnow
from .services import llm

router = APIRouter(prefix="/api/admin", tags=["admin-ai"])
MODEL_RE = re.compile(r"^[A-Za-z0-9._:/-]{1,120}$")


class AIConfigIn(BaseModel):
    provider_name: str
    model_name: str = ""
    api_key: str = ""


def _public(db: Session) -> dict:
    row = db.get(AIProviderSettings, 1)
    cfg = llm.get_active_config(db) or llm.get_env_config()
    return {
        "provider_name": cfg.provider_name if cfg else (row.provider_name if row else "gemini"),
        "model_name": cfg.model_name if cfg else (row.model_name if row else ""),
        "masked_key": llm.mask_key(cfg.api_key) if cfg else "",
        "configured": cfg is not None,
        "source": cfg.source if cfg else None,
        "providers": list(llm.PROVIDERS),
        "default_models": llm.DEFAULT_MODELS,
    }


@router.get("/ai-config")
def get_ai_config(_: User = Depends(require_coordinator), db: Session = Depends(get_session)):
    return _public(db)


@router.put("/ai-config")
def save_ai_config(data: AIConfigIn, user: User = Depends(require_coordinator),
                   db: Session = Depends(get_session), x_lang: str | None = Header(default=None)):
    lang = x_lang or user.language
    provider = data.provider_name.strip().lower()
    if provider not in llm.PROVIDERS:
        raise fail(422, "ai_provider_invalid", lang)
    model = data.model_name.strip() or llm.DEFAULT_MODELS[provider]
    if not MODEL_RE.fullmatch(model):
        raise fail(422, "ai_model_invalid", lang)

    row = db.get(AIProviderSettings, 1)
    key = data.api_key.strip()
    if key:
        if not (8 <= len(key) <= 500):
            raise fail(422, "ai_key_invalid", lang)
        encrypted = encrypt_secret(key)
    elif row and row.provider_name == provider and decrypt_secret(row.encrypted_api_key):
        encrypted = row.encrypted_api_key  # wahi provider: khali field ka matlab key na badlein
    else:
        raise fail(422, "ai_key_required", lang)

    if not row:
        row = AIProviderSettings(id=1)
    row.provider_name, row.model_name, row.encrypted_api_key = provider, model, encrypted
    row.updated_by, row.updated_at = user.id, utcnow()
    db.add(row)
    db.add(AuditLog(actor_id=user.id, action="ai_config_saved", detail=provider))  # key kabhi audit mein nahi
    db.commit()
    db.refresh(row)
    return _public(db)
