"""Admin ke command-line kaam (server band ho to bhi). Madad: uv run python -m app.cli --help"""
import argparse
import secrets
import sys

from sqlmodel import Session, select

from .db import engine
from .models import AuditLog, AuthSession, User


def make_admin(email: str) -> bool:
    """Owner account ko super_admin banata hai (RBAC ka sab se ooncha role)."""
    with Session(engine) as db:
        u = db.exec(select(User).where(User.email == email.strip().lower())).first()
        if not u:
            return False
        u.role = "super_admin"
        db.add(u)
        db.commit()
        return True


def reset_password(email: str) -> str | None:
    """Naya aarzi password banata hai aur us user ki saari sessions band. Password sirf ek baar dikhta hai."""
    from .security import hash_password
    with Session(engine) as db:
        u = db.exec(select(User).where(User.email == email.strip().lower())).first()
        if not u:
            return None
        temp = secrets.token_urlsafe(9)
        u.password_hash, u.failed_logins, u.locked_until = hash_password(temp), 0, None
        db.add(u)
        for s in db.exec(select(AuthSession).where(AuthSession.user_id == u.id)).all():
            db.delete(s)
        db.add(AuditLog(actor_id=None, action="password_reset_by_admin_cli", detail=str(u.id)))
        db.commit()
        return temp


def revoke_sessions(email: str | None) -> int:
    """Incident mein: sab (ya ek user ki) sessions foran band."""
    with Session(engine) as db:
        q = select(AuthSession)
        if email:
            u = db.exec(select(User).where(User.email == email.strip().lower())).first()
            if not u:
                return -1
            q = q.where(AuthSession.user_id == u.id)
        rows = db.exec(q).all()
        for s in rows:
            db.delete(s)
        db.add(AuditLog(actor_id=None, action="sessions_revoked_by_cli", detail=email or "all"))
        db.commit()
        return len(rows)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m app.cli")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("make-admin").add_argument("email")
    sub.add_parser("make-super-admin").add_argument("email")
    sub.add_parser("reset-password").add_argument("email")
    sub.add_parser("revoke-sessions").add_argument("email", nargs="?")
    b = sub.add_parser("backup")
    b.add_argument("--out", default="backups")
    b.add_argument("--keep", type=int, default=None)
    g = sub.add_parser("rag-ingest")
    g.add_argument("file")
    g.add_argument("--title", required=True)
    g.add_argument("--source-url", required=True)
    g.add_argument("--verified-on", required=True)
    g.add_argument("--jurisdiction", default="Pakistan")
    g.add_argument("--attest", action="store_true")
    q = sub.add_parser("rag-ask")
    q.add_argument("question")
    q.add_argument("--lang", default="roman_urdu")
    q.add_argument("--llm", action="store_true")
    r = sub.add_parser("restore")
    r.add_argument("file")
    r.add_argument("--yes", action="store_true")
    a = p.parse_args(argv)
    if a.cmd in ("make-admin", "make-super-admin"):
        ok = make_admin(a.email)
        print("Super admin ban gaya." if ok else "Yeh email wala user nahi mila; pehle signup karein.")
        return 0 if ok else 1
    if a.cmd == "reset-password":
        t = reset_password(a.email)
        if not t:
            print("Yeh email wala user nahi mila.")
            return 1
        print(f"Aarzi password (sirf abhi dikhta hai, user se kahein foran change karein): {t}")
        return 0
    if a.cmd == "revoke-sessions":
        n = revoke_sessions(a.email)
        print("User nahi mila." if n < 0 else f"{n} sessions band.")
        return 1 if n < 0 else 0
    if a.cmd in ("rag-ingest", "rag-ask"):
        from . import rag
        from .main import SQLModel  # noqa: F401  (tables tayyar)
        with Session(engine) as db:
            try:
                if a.cmd == "rag-ingest":
                    if not a.attest:
                        print("Sirf official source se verify kiye hue document daalein, aur --attest likh kar tasdeeq karein.")
                        return 2
                    with open(a.file, "rb") as f:
                        print(rag.ingest_pdf(db, f.read(), a.title, a.source_url, a.verified_on, a.jurisdiction, None))
                else:
                    r = rag.ask(db, a.question, a.lang, allow_llm=a.llm)
                    print(r["answer"], "\n")
                    for s in r["sources"]:
                        print(f"[{s['n']}] {s['title']} | page {s['page']} | {s['source_url']} | verified {s['verified_on']} | score {s['score']}")
                    print("\n" + r["disclaimer"])
            except (rag.RagError, OSError) as e:
                print(f"Masla: {e}")
                return 1
        return 0
    from .backup import BackupError, create_backup, restore_backup
    try:
        if a.cmd == "backup":
            path = create_backup(a.out, keep=a.keep)
            print(f"Backup bana: {path}\nIs mein hassas data hai: isay mehfooz (encrypted) jagah rakhein.")
        else:
            if not a.yes:
                print("Restore maujooda database aur files ki jagah le leta hai (purana '.pre-restore' name se bachta hai).\n"
                      "Pehle server band karein, phir yahi command --yes ke saath chalayein.")
                return 2
            counts = restore_backup(a.file)
            print(f"Restore ho gaya. Ginti: {counts}")
    except BackupError as e:
        print(f"Masla: {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
