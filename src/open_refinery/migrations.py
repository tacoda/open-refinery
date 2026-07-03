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

# Append-only list of incremental schema changes. The current register_schema
# reflects the latest shape (for fresh DBs); each entry evolves an existing DB.
MIGRATIONS: list[str] = [
    # v1 (0.4.0): synced work items carry an external tracker reference
    "ALTER TABLE work_items ADD COLUMN external_ref TEXT;",
    # v2 (0.9.0): per-process risk profile — min role to approve a gated move
    "ALTER TABLE processes ADD COLUMN min_approver_role TEXT NOT NULL DEFAULT 'senior';",
    # v3 (0.10.0): ordered approval chain (roles) for async/chained approvals
    "ALTER TABLE processes ADD COLUMN approval_chain TEXT NOT NULL DEFAULT '[]';",
    # v4 (0.11.0): optional structured-output schema per target
    "ALTER TABLE targets ADD COLUMN output_schema TEXT NOT NULL DEFAULT '{}';",
    # v5 (0.13.0): policies become governed harness artifacts + strict override lock
    "ALTER TABLE policies ADD COLUMN kind TEXT NOT NULL DEFAULT 'rule';"
    "ALTER TABLE policies ADD COLUMN strict INTEGER NOT NULL DEFAULT 0;"
    "ALTER TABLE policies ADD COLUMN content TEXT NOT NULL DEFAULT '';",
]


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
