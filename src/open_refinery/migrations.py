"""Schema migrations — minimal, versioned, no framework.

`register_schema` (in store.py) creates every table at its *latest* shape, so a
**fresh** database is complete immediately and is stamped to the newest version.
An **existing** database is evolved by running the pending entries in
`MIGRATIONS` in order, tracked by SQLite's `PRAGMA user_version`.

Rules when the schema changes:
  1. Update the module's `register_schema` DDL to the new shape (for fresh DBs).
  2. Append the incremental change (e.g. `ALTER TABLE … ADD COLUMN …`) to
     `MIGRATIONS` — append only, never edit or reorder existing entries.
"""

from __future__ import annotations

import sqlite3

# Append-only list of incremental schema changes. Empty at 0.2.0: the current
# schema is the baseline. The runner exists so future changes reach live DBs.
MIGRATIONS: list[str] = []


def _version(conn: sqlite3.Connection) -> int:
    return conn.execute("PRAGMA user_version").fetchone()[0]


def run_migrations(conn: sqlite3.Connection, migrations: list[str] | None = None) -> int:
    """Apply pending migrations in order; return how many ran. Idempotent."""
    migrations = MIGRATIONS if migrations is None else migrations
    start = _version(conn)
    for i in range(start, len(migrations)):
        conn.executescript(migrations[i])
        conn.execute(f"PRAGMA user_version = {i + 1}")
    conn.commit()
    return max(0, len(migrations) - start)


def stamp_latest(conn: sqlite3.Connection) -> None:
    """Mark a fresh DB (built at the latest shape) as fully migrated."""
    conn.execute(f"PRAGMA user_version = {len(MIGRATIONS)}")
    conn.commit()
