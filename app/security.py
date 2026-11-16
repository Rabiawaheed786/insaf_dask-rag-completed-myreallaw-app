import hashlib
import secrets
from datetime import timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from .config import settings
from .models import utcnow

_ph = PasswordHasher()
# "User nahi mila" par bhi utna hi waqt lage, taake pata na chale email maujood hai ya nahi.
_DUMMY_HASH = _ph.hash(secrets.token_hex(16))


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    try:
        _ph.verify(password_hash or _DUMMY_HASH, password)
        return password_hash is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def session_expiry():
    return utcnow() + timedelta(days=settings.session_days)


def minutes_from_now(m: int):
    return utcnow() + timedelta(minutes=m)
