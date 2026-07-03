"""Durable event store — persists and queries the audit trail.

The 0.1.0 core records events to a `MemorySink`. This backs them with SQLite so
the audit trail survives restarts and is queryable. `DATABASE_URL` selects the
store; only SQLite is wired today.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from .provenance import Record

DEFAULT_DATABASE_URL = "sqlite:///open-refinery.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    artifact_id   TEXT PRIMARY KEY,
    recipe        TEXT NOT NULL,
    actor         TEXT NOT NULL,
    owner         TEXT NOT NULL,
    input_digest  TEXT NOT NULL,
    output_digest TEXT NOT NULL,
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_events_actor ON events(actor);
CREATE INDEX IF NOT EXISTS ix_events_recipe ON events(recipe);
CREATE INDEX IF NOT EXISTS ix_events_created_at ON events(created_at);
"""


def _sqlite_path(database_url: str) -> str:
    # ponytail: sqlite only for now; Postgres joins at this seam when needed.
    prefix = "sqlite:///"
    if not database_url.startswith(prefix):
        raise ValueError(f"unsupported DATABASE_URL: {database_url!r} (sqlite only)")
    return database_url[len(prefix):]  # sqlite:///rel, sqlite:////abs, sqlite:///:memory:


def connect(database_url: str = DEFAULT_DATABASE_URL) -> sqlite3.Connection:
    """Open the store, applying the schema idempotently."""
    path = _sqlite_path(database_url)
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(_SCHEMA)
    return conn


class SqliteSink:
    """Durable `AuditSink` — one row per production event."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def write(self, record: Record) -> None:
        self._conn.execute(
            "INSERT INTO events "
            "(artifact_id, recipe, actor, owner, input_digest, output_digest, created_at) "
            "VALUES (:artifact_id, :recipe, :actor, :owner, :input_digest, :output_digest, :created_at)",
            record.to_dict(),
        )
        self._conn.commit()


def query_events(
    conn: sqlite3.Connection,
    *,
    actor: str | None = None,
    recipe: str | None = None,
    owner: str | None = None,
    since: str | None = None,
    until: str | None = None,
    limit: int = 100,
) -> list[Record]:
    """Query the audit trail, newest first. Filters combine with AND."""
    clauses: list[str] = []
    params: dict[str, object] = {}
    for col, val in (("actor", actor), ("recipe", recipe), ("owner", owner)):
        if val is not None:
            clauses.append(f"{col} = :{col}")
            params[col] = val
    if since is not None:
        clauses.append("created_at >= :since")
        params["since"] = since
    if until is not None:
        clauses.append("created_at <= :until")
        params["until"] = until

    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    params["limit"] = limit
    rows = conn.execute(
        f"SELECT * FROM events{where} ORDER BY created_at DESC LIMIT :limit", params
    )
    return [Record(**dict(row)) for row in rows]
