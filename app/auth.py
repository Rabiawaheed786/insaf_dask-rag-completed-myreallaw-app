import re

from fastapi import APIRouter, Depends, Header, Request, Response
from pydantic import BaseModel
from sqlmodel import Session, select

from .config import settings
from .db import get_session
from .messages import fail
from .ratelimit import ip_limit
from .models import AuditLog, AuthSession, User, utcnow
from .security import (hash_password, minutes_from_now, new_token, session_expiry,
                       token_hash, verify_password)

router = APIRouter(prefix="/api/auth", tags=["auth"])
COOKIE = "insaf_session"
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
LANGS = ("roman_urdu", "en")


class SignupIn(BaseModel):
    email: str
    password: str
    display_name: str = ""
    language: str = "roman_urdu"


class LoginIn(BaseModel):
    email: str
    password: str


class LangIn(BaseModel):
    language: str


def public_user(u: User) -> dict:
    # Password hash ya lock ki tafseel kabhi bahar nahi jati.
    return {"id": u.id, "email": u.email, "display_name": u.display_name,
            "role": u.role, "language": u.language, "timezone": u.timezone}


def _start_session(db: Session, response: Response, user: User):
    token = new_token()
    db.add(AuthSession(token_hash=token_hash(token), user_id=user.id, expires_at=session_expiry()))
    response.set_cookie(COOKIE, token, httponly=True, samesite="lax",
                        secure=settings.cookie_secure,
                        max_age=settings.session_days * 86400, path="/")


def current_user(request: Request, db: Session = Depends(get_session),
                 x_lang: str | None = Header(default=None)) -> User:
    token = request.cookies.get(COOKIE)
    if token:
        s = db.exec(select(AuthSession).where(AuthSession.token_hash == token_hash(token))).first()
        if s and s.expires_at > utcnow():
            user = db.get(User, s.user_id)
            if user:
                return user
    raise fail(401, "not_logged_in", x_lang)


@router.post("/signup", status_code=201, dependencies=[Depends(ip_limit("signup", "signup_per_hour_ip", 3600))])
def signup(data: SignupIn, response: Response, db: Session = Depends(get_session)):
    lang = data.language if data.language in LANGS else "roman_urdu"
    email = data.email.strip().lower()
    if not EMAIL_RE.match(email):
        raise fail(422, "email_invalid", lang)
    if len(data.password) < 8:
        raise fail(422, "password_short", lang)
    if db.exec(select(User).where(User.email == email)).first():
        raise fail(409, "email_taken", lang)
    user = User(email=email, password_hash=hash_password(data.password),
                display_name=data.display_name.strip()[:80], language=lang)
    db.add(user)
    db.commit()
    db.refresh(user)
    db.add(AuditLog(actor_id=user.id, action="signup"))
    _start_session(db, response, user)
    db.commit()
    return public_user(user)


@router.post("/login", dependencies=[Depends(ip_limit("login", "login_per_minute_ip", 60))])
def login(data: LoginIn, response: Response, db: Session = Depends(get_session),
          x_lang: str | None = Header(default=None)):
    email = data.email.strip().lower()
    user = db.exec(select(User).where(User.email == email)).first()
    if user and user.locked_until and user.locked_until > utcnow():
        raise fail(429, "account_locked", x_lang or user.language)
    if not verify_password(data.password, user.password_hash if user else None):
        if user:
            user.failed_logins += 1
            if user.failed_logins >= settings.max_failed_logins:
                user.locked_until = minutes_from_now(settings.lock_minutes)
                user.failed_logins = 0
                db.add(AuditLog(actor_id=user.id, action="account_locked"))
            db.add(user)
            db.commit()
        raise fail(401, "login_failed", x_lang or (user.language if user else None))
    user.failed_logins = 0
    user.locked_until = None
    db.add(user)
    db.add(AuditLog(actor_id=user.id, action="login"))
    _start_session(db, response, user)
    db.commit()
    return public_user(user)


@router.post("/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_session)):
    token = request.cookies.get(COOKIE)
    if token:
        s = db.exec(select(AuthSession).where(AuthSession.token_hash == token_hash(token))).first()
        if s:
            db.delete(s)
            db.commit()
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@router.get("/me")
def me(user: User = Depends(current_user)):
    return public_user(user)


class ProfileIn(BaseModel):
    display_name: str | None = None
    email: str | None = None


@router.put("/me")
def update_profile(data: ProfileIn, user: User = Depends(current_user), db: Session = Depends(get_session),
                   x_lang: str | None = Header(default=None)):
    """Dashboard se apni tafseel badalna. Sirf apna record; email badle to naya unique hona chahiye."""
    lang = x_lang or user.language
    if data.display_name is not None:
        name = data.display_name.strip()
        if len(name) > 80:
            raise fail(422, "field_too_long", lang)
        user.display_name = name
    if data.email is not None:
        email = data.email.strip().lower()
        if not EMAIL_RE.match(email):
            raise fail(422, "email_invalid", lang)
        if email != user.email and db.exec(select(User).where(User.email == email)).first():
            raise fail(409, "email_taken", lang)
        user.email = email
    db.add(user)
    db.add(AuditLog(actor_id=user.id, action="profile_updated"))
    db.commit()
    db.refresh(user)
    return public_user(user)



@router.put("/me/language")
def set_language(data: LangIn, user: User = Depends(current_user), db: Session = Depends(get_session)):
    if data.language not in LANGS:
        raise fail(422, "language_invalid", user.language)
    user.language = data.language
    db.add(user)
    db.commit()
    return public_user(user)


class ChangePasswordIn(BaseModel):
    old_password: str
    new_password: str


@router.post("/change-password")
def change_password(data: ChangePasswordIn, request: Request, user: User = Depends(current_user),
                    db: Session = Depends(get_session), x_lang: str | None = Header(default=None)):
    lang = x_lang or user.language
    if not verify_password(data.old_password, user.password_hash):
        raise fail(401, "password_wrong", lang)
    if len(data.new_password) < 8:
        raise fail(422, "password_short", lang)
    user.password_hash = hash_password(data.new_password)
    db.add(user)
    keep = token_hash(request.cookies.get(COOKIE, ""))
    for s in db.exec(select(AuthSession).where(AuthSession.user_id == user.id)).all():
        if s.token_hash != keep:  # baqi sab jagah se logout (chori hui session bhi)
            db.delete(s)
    db.add(AuditLog(actor_id=user.id, action="password_changed"))
    db.commit()
    return {"ok": True}
