import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlmodel import SQLModel

from . import models  # noqa: F401  (tables register hon)
from sqlmodel import Session

from .auth import router as auth_router
from .cases import router as cases_router, seed_official_contacts
from .ai_admin import router as ai_admin_router
from .ai_api import router as ai_router
from .chat import router as chat_router
from .kb import router as kb_router
from .config import settings
from .messages import MESSAGES, pick_lang
from .db import engine
from .privacy import router as privacy_router
from .rag_api import router as rag_router
from .notify import router as notify_router, run_all
from .reports import router as reports_router
from .slots import router as slots_router
from .lawyers import router as lawyers_router
from .ops import router as ops_router

STATIC = Path(__file__).resolve().parent.parent / "static"


log = logging.getLogger("insaf.scheduler")


def _tick():
    with Session(engine) as db:
        run_all(db)


async def _scheduler():
    """Har interval par jobs. Stateless hai (waqt se due nikalta hai), is liye restart ke baad bhi duplicate nahi."""
    while True:
        try:
            await asyncio.to_thread(_tick)
        except Exception:  # agli baar dobara; masle ka matn kabhi log nahi hota
            log.exception("scheduler tick failed")
        await asyncio.sleep(settings.scheduler_interval_seconds)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Local development ke liye tables bana deta hai; asli tabdeeli Alembic migrations se hoti hai.
    SQLModel.metadata.create_all(engine)
    with Session(engine) as db:
        seed_official_contacts(db)
    task = asyncio.create_task(_scheduler()) if settings.scheduler_enabled else None
    try:
        yield
    finally:
        if task:
            task.cancel()


app = FastAPI(title="Insaf Dastak", lifespan=lifespan)
app.include_router(auth_router)
app.include_router(cases_router)
app.include_router(ops_router)
app.include_router(ai_admin_router)
app.include_router(ai_router)
app.include_router(lawyers_router)
app.include_router(chat_router)
app.include_router(notify_router)
app.include_router(reports_router)
app.include_router(slots_router)
app.include_router(privacy_router)
app.include_router(rag_router)
app.include_router(kb_router)


def _origin_ok(request) -> bool:
    """CSRF ki doosri dewar (SameSite=Lax ke ilawa): doosri website se aayi POST/PUT/DELETE rok do."""
    if request.url.path.startswith("/api/widget/"):  # embed widget: token hi ijazat hai, cookie nahi
        return True
    if request.headers.get("sec-fetch-site") == "cross-site":
        return False
    origin = request.headers.get("origin")
    if not origin:
        return True  # aam API client / curl: Origin nahi bhejte
    trusted = {o.strip().rstrip("/") for o in settings.trusted_origins.split(",") if o.strip()}
    return origin.rstrip("/") in trusted or urlparse(origin).netloc == request.headers.get("host", "")


CSP = ("default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
       "frame-ancestors 'none'; base-uri 'none'; form-action 'self'")


@app.middleware("http")
async def security_headers(request, call_next):
    if request.method not in ("GET", "HEAD", "OPTIONS") and not _origin_ok(request):
        return JSONResponse(status_code=403, content={"detail": {
            "code": "csrf_blocked", "message": MESSAGES["csrf_blocked"][pick_lang(request.headers.get("x-lang"))]}})
    resp = await call_next(request)
    if request.url.path.startswith("/api/widget/"):  # kisi bhi website par lagaya ja sakta hai; token endpoint mein check hota hai
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type, X-Kb-Token, X-Lang"
        resp.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["Cache-Control"] = "no-store"
    resp.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if not request.url.path.startswith(("/docs", "/redoc", "/openapi.json")):  # Swagger CDN se chalta hai
        resp.headers["Content-Security-Policy"] = CSP
    if settings.cookie_secure:
        resp.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return resp


@app.get("/api/health")
def health():
    return {"status": "ok"}


app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")
