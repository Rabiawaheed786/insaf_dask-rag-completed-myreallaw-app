"""Backup aur restore (SQLite abhi). Backup mein hassas data hota hai: usay mehfooz (encrypted) jagah rakhein.
Restore se pehle manifest ke hash check hote hain, aur purana data '.pre-restore' name se bacha liya jata hai."""
import hashlib
import json
import re
import shutil
import sqlite3
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from .config import settings

UPLOAD_NAME = re.compile(r"^uploads/[0-9a-f]{32}$")


class BackupError(Exception):
    pass


def _db_path(db_url: str | None) -> Path:
    url = db_url or settings.database_url
    if not url.startswith("sqlite:///"):
        raise BackupError("Abhi sirf SQLite ka backup hai; PostgreSQL ke liye pg_dump istemal karein.")
    return Path(url[len("sqlite:///"):])


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def create_backup(out_dir: str | Path = "backups", db_url: str | None = None,
                  upload_dir: str | None = None, keep: int | None = None) -> Path:
    db_path, uploads = _db_path(db_url), Path(upload_dir or settings.upload_dir)
    if not db_path.exists():
        raise BackupError("Database file nahi mili.")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    target = out_dir / f"insaf-backup-{stamp}.zip"
    with tempfile.TemporaryDirectory() as tmp:
        snap = Path(tmp) / "database.db"
        src, dst = sqlite3.connect(db_path), sqlite3.connect(snap)
        with dst:
            src.backup(dst)  # chalte database ki bhi mehfooz copy
        counts = {t: dst.execute(f"select count(*) from {t}").fetchone()[0]
                  for t in ("users", "requests", "attachments", "chat_messages")}
        src.close()
        dst.close()
        files = {"database.db": _sha(snap)}
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(snap, "database.db")
            if uploads.exists():
                for f in sorted(uploads.iterdir()):
                    if f.is_file() and re.fullmatch(r"[0-9a-f]{32}", f.name):
                        z.write(f, f"uploads/{f.name}")
                        files[f"uploads/{f.name}"] = _sha(f)
            manifest = {"format": 1, "created_at": datetime.now(timezone.utc).isoformat(), "files": files,
                        "counts": counts}
            z.writestr("manifest.json", json.dumps(manifest, indent=2))
    if keep:
        for old in sorted(out_dir.glob("insaf-backup-*.zip"))[:-keep]:
            old.unlink()
    return target


def restore_backup(zip_path: str | Path, db_url: str | None = None, upload_dir: str | None = None) -> dict:
    db_path, uploads = _db_path(db_url), Path(upload_dir or settings.upload_dir)
    try:
        z = zipfile.ZipFile(zip_path)
        manifest = json.loads(z.read("manifest.json"))
    except (OSError, KeyError, ValueError, zipfile.BadZipFile) as e:
        raise BackupError(f"Backup file kharab ya ghalat hai ({type(e).__name__}).") from None
    with z, tempfile.TemporaryDirectory() as tmp:
        names = set(z.namelist()) - {"manifest.json"}
        if names != set(manifest["files"]) or "database.db" not in names \
                or any(n != "database.db" and not UPLOAD_NAME.match(n) for n in names):
            raise BackupError("Backup ki list manifest se nahi milti.")
        for n in names:  # har file ka hash: chheda-chhaadi pakri jati hai
            p = Path(tmp) / n.replace("/", "_")
            p.write_bytes(z.read(n))
            if _sha(p) != manifest["files"][n]:
                raise BackupError(f"Hash nahi mila: {n}. Backup badla gaya hai.")
        snap = Path(tmp) / "database.db"
        check = sqlite3.connect(snap)
        ok = check.execute("pragma integrity_check").fetchone()[0]
        check.close()
        if ok != "ok":
            raise BackupError("Backup ka database integrity check mein fail hua.")
        if db_path.exists():
            shutil.copy2(db_path, db_path.with_name(db_path.name + ".pre-restore"))
        for suffix in ("-wal", "-shm"):
            db_path.with_name(db_path.name + suffix).unlink(missing_ok=True)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(snap, db_path)
        if uploads.exists():
            old = uploads.with_name(uploads.name + ".pre-restore")
            shutil.rmtree(old, ignore_errors=True)
            uploads.rename(old)
        uploads.mkdir(parents=True, exist_ok=True)
        for n in names:
            if n != "database.db":
                shutil.copy2(Path(tmp) / n.replace("/", "_"), uploads / n.split("/", 1)[1])
    return manifest["counts"]
