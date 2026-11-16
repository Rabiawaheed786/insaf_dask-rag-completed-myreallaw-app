"""AI ko bhejne se pehle pehchaan wali cheezein hatana.
Hadd: yeh sirf email, phone, CNIC, IBAN aur lambe numbers pakarta hai. Name aur pata nahi hatta."""
import re

PATTERNS = [
    ("EMAIL", re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")),
    ("IBAN", re.compile(r"\bPK\d{2}[A-Za-z]{4}\d{16}\b", re.I)),
    ("CNIC", re.compile(r"\b\d{5}-\d{7}-\d\b|\b\d{13}\b")),
    ("PHONE", re.compile(r"(?:\+92|0092|\b0)[\s-]?\d{2,3}[\s-]?\d{7}\b")),
    ("ACCOUNT", re.compile(r"\b\d{9,}\b")),
]


def redact(text: str) -> tuple[str, dict]:
    counts: dict[str, int] = {}
    for label, rx in PATTERNS:
        text, n = rx.subn(f"[{label}]", text)
        if n:
            counts[label] = n
    return text, counts
