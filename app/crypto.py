"""AI provider keys ke liye symmetric encryption.

Fernet key AI_KEY_SECRET se derive hoti hai, is liye DB backup akela key ko expose nahi karta.
"""
import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from .config import settings

_FALLBACK_SECRET = "dev-only-change-this-ai-key-secret"


def _fernet() -> Fernet:
    secret = settings.ai_key_secret or _FALLBACK_SECRET
    digest = hashlib.sha256(("insaf-dastak-ai:" + secret).encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt_secret(token: str) -> str:
    if not token:
        return ""
    try:
        return _fernet().decrypt(token.encode()).decode()
    except (InvalidToken, ValueError, TypeError):
        return ""
