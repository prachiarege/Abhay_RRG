"""Database session management."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .config import get_settings
from .models import Base

settings = get_settings()

_connect_args: dict = {}
if settings.database_url.startswith("sqlite"):
    _connect_args["check_same_thread"] = False

engine: Engine = create_engine(
    settings.database_url,
    echo=settings.sql_echo,
    future=True,
    pool_pre_ping=True,
    connect_args=_connect_args,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


if settings.database_url.startswith("sqlite"):

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_connection, _record):  # pragma: no cover
        """WAL plus enforced foreign keys, so SQLite behaves closer to Postgres."""
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()


def init_db() -> None:
    """Create tables if absent.

    Sufficient for MVP. When the schema starts evolving in production, swap this for
    Alembic; the models are written to be migration-friendly.
    """
    Base.metadata.create_all(bind=engine)


def get_session() -> Iterator[Session]:
    """FastAPI dependency."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope for scripts and scheduled jobs."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
