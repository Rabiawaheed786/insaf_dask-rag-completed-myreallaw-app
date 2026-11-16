import os
import shutil
import tempfile

# Settings import hone se pehle alag temp database aur tez lock ki setting.
_tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ["MAX_FAILED_LOGINS"] = "3"
os.environ["SCHEDULER_ENABLED"] = "false"
os.environ["UPLOAD_DIR"] = f"{_tmp}/uploads"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlmodel import SQLModel  # noqa: E402

from app import ratelimit  # noqa: E402
from app.db import engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture()
def client():
    ratelimit.reset()
    SQLModel.metadata.drop_all(engine)
    shutil.rmtree(os.environ["UPLOAD_DIR"], ignore_errors=True)  # har test saaf folder se shuru
    with TestClient(app) as c:
        yield c


def signup(c, email="farah@example.com", password="strongpass1", lang="roman_urdu"):
    return c.post("/api/auth/signup", json={"email": email, "password": password,
                                            "display_name": "Test", "language": lang})
