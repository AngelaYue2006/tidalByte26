"""SQLite engine and session. Tables: tasks, contacts, calls, turns, events, receipts."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app import models  # registers the tables on SQLModel.metadata


def make_engine(database_url: str) -> Engine:
    """One engine per app. SQLite needs check_same_thread off for FastAPI's threadpool; in-memory URLs share one connection."""
    kwargs: dict = {}
    if database_url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
        if database_url in ("sqlite://", "sqlite:///:memory:"):
            kwargs["poolclass"] = StaticPool
    return create_engine(database_url, **kwargs)


def init_db(engine: Engine) -> None:
    """Create missing tables, then apply the schema guarantees create_all leaves out on tables that already existed."""
    SQLModel.metadata.create_all(engine)
    with engine.begin() as conn:
        # create_all never alters an existing table; a database from before #20 has turns without this index.
        conn.exec_driver_sql(f"CREATE UNIQUE INDEX IF NOT EXISTS {models.TURNS_UNIQUE_INDEX} ON turns (call_id, seq)")


@contextmanager
def session_scope(engine: Engine) -> Iterator[Session]:
    """Commit on success, roll back on error."""
    with Session(engine) as session:
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
