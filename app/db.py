"""SQLAlchemy engine and session. SQLite by default, Postgres via DATABASE_URL."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    pass


def _make_engine():
    kwargs: dict = {}
    if settings.is_sqlite:
        # FastAPI handles a request on a worker thread; SQLite objects to
        # that unless told otherwise.
        kwargs["connect_args"] = {"check_same_thread": False}
        path = settings.database_url.removeprefix("sqlite:///")
        if path and path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
    return create_engine(settings.database_url, **kwargs)


engine = _make_engine()
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def init_db() -> None:
    """Create the tables. A prototype: no migrations yet."""
    from app import models  # noqa: F401  -- registers the tables on Base

    Base.metadata.create_all(engine)


def get_session() -> Iterator[Session]:
    """FastAPI dependency: one session per request."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
