import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from alembic import context
from sqlalchemy import create_engine
from sqlmodel import SQLModel

from app import models  # noqa: F401
from app.config import settings

target_metadata = SQLModel.metadata


def run_migrations_online():
    engine = create_engine(settings.database_url)
    with engine.connect() as conn:
        context.configure(connection=conn, target_metadata=target_metadata,
                          render_as_batch=settings.database_url.startswith("sqlite"))
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
