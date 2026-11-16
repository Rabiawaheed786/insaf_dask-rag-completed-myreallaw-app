"""IP ke hisaab se hadd. Yeh ek process ki yaad mein rehti hai (restart par saaf); kai servers par Redis jaisa share chahiye."""
import threading
import time
from collections import defaultdict, deque

from fastapi import Header, Request

from .config import settings
from .messages import fail

_lock = threading.Lock()
_hits: dict[str, deque] = defaultdict(deque)


def hit(key: str, limit: int, window: int) -> bool:
    now = time.monotonic()
    with _lock:
        q = _hits[key]
        while q and q[0] <= now - window:
            q.popleft()
        if len(q) >= limit:
            return False
        q.append(now)
        return True


def reset():
    with _lock:
        _hits.clear()


def ip_limit(name: str, attr: str, window: int):
    def dep(request: Request, x_lang: str | None = Header(default=None)):
        ip = request.client.host if request.client else "unknown"
        if not hit(f"{name}:{ip}", getattr(settings, attr), window):
            raise fail(429, "rate_limited_ip", x_lang)
    return dep
