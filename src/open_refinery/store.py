"""Database engine, sessions, and the durable audit sink — SQLModel over SQLite.

`connect()` builds an engine, creates tables from the SQLModel metadata, runs
pending migrations, and returns a `Session`. `engine_for()` exposes the engine
for the web layer's per-request sessions. Only SQLite is wired today; the ORM
keeps other backends within reach.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from . import models  # noqa: F401 — import registers tables in SQLModel.metadata
from .audit import AuditSink, MemorySink  # noqa: F401 — re-exported for convenience
from .models import Event
from .provenance import Record

DEFAULT_DATABASE_URL = "sqlite:///open-refinery.db"


def _sqlite_path(database_url: str) -> str | None:
    prefix = "sqlite:///"
    return database_url[len(prefix):] if database_url.startswith(prefix) else None


def engine_for(database_url: str = DEFAULT_DATABASE_URL) -> Engine:
    """Build an engine and ensure its schema + migrations are applied."""
    if not database_url.startswith("sqlite"):
        raise ValueError(f"unsupported DATABASE_URL: {database_url!r} (sqlite only)")
    path = _sqlite_path(database_url)
    if path and path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    kwargs: dict = {"connect_args": {"check_same_thread": False}}
    if path == ":memory:":  # keep one shared in-memory DB across sessions
        kwargs["poolclass"] = StaticPool
    engine = create_engine(database_url, **kwargs)
    _init_schema(engine)
    return engine


def _init_schema(engine: Engine) -> None:
    from .migrations import run_migrations, stamp_latest

    raw = engine.raw_connection()
    try:
        fresh = raw.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='events'"
        ).fetchone() is None
    finally:
        raw.close()

    SQLModel.metadata.create_all(engine)

    raw = engine.raw_connection()
    try:
        raw.execute("PRAGMA foreign_keys=ON")
        stamp_latest(raw) if fresh else run_migrations(raw)
    finally:
        raw.close()

    # Roles are load-bearing (create_user validates against them) — seed the
    # default ladder before anything creates a user.
    from .users import ensure_default_roles
    with Session(engine) as s:
        ensure_default_roles(s)


def connect(database_url: str = DEFAULT_DATABASE_URL, *, check_same_thread: bool = True) -> Session:
    """Open the store (schema + migrations applied) and return a Session."""
    return Session(engine_for(database_url))


# --- durable audit sink ---------------------------------------------------

class SqlSink:
    """Durable AuditSink — persists each event via the session."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def write(self, record: Record) -> None:
        self._session.add(Event(**record.to_dict()))
        self._session.commit()
        from .webhooks import deliver
        deliver(self._session, record)  # fan out to registered endpoints (best-effort)


# Backwards-compatible alias — the SQL-backed sink used to be SqliteSink.
SqliteSink = SqlSink


def purge_events(session: Session, older_than_days: int) -> int:
    """Delete audit events older than the retention window. Returns how many went."""
    from datetime import datetime, timedelta, timezone
    cutoff = (datetime.now(timezone.utc) - timedelta(days=older_than_days)).isoformat()
    rows = list(session.exec(select(Event).where(Event.created_at < cutoff)))
    for e in rows:
        session.delete(e)
    session.commit()
    return len(rows)


def query_events(
    session: Session,
    *,
    actor: str | None = None,
    recipe: str | None = None,
    owner: str | None = None,
    subject: str | None = None,
    since: str | None = None,
    until: str | None = None,
    limit: int = 100,
) -> list[Event]:
    """Query the audit trail, newest first. Filters combine with AND."""
    stmt = select(Event)
    if actor is not None:
        stmt = stmt.where(Event.actor == actor)
    if recipe is not None:
        stmt = stmt.where(Event.recipe == recipe)
    if owner is not None:
        stmt = stmt.where(Event.owner == owner)
    if subject is not None:
        stmt = stmt.where(Event.subject == subject)
    if since is not None:
        stmt = stmt.where(Event.created_at >= since)
    if until is not None:
        stmt = stmt.where(Event.created_at <= until)
    stmt = stmt.order_by(Event.created_at.desc()).limit(limit)
    return list(session.exec(stmt))
