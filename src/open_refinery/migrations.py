"""Schema migrations — minimal, versioned, no framework.

`SQLModel.metadata.create_all` (in store.py) builds every table at its *latest*
model shape. A **fresh** DB is complete immediately and stamped to the newest
version. An **existing** DB is evolved by running the pending entries in
`MIGRATIONS` in order, tracked by SQLite's `PRAGMA user_version`. Both run on
`engine_for()` — i.e. automatically at `open-refinery serve` (and any `connect`);
`open-refinery migrate` runs them explicitly without starting the server.

**Standard practice — every schema change ships a migration.** Whenever a model
changes, add the corresponding migration so existing installs upgrade:
  - **New table** → handled by `create_all` (creates missing tables on upgrade);
    no `MIGRATIONS` entry needed.
  - **New / changed column** → append an `ALTER TABLE … ADD COLUMN …` (with a
    NOT NULL DEFAULT for non-nullable) to `MIGRATIONS`.
  - **New index on an existing table's column** → append
    `CREATE INDEX IF NOT EXISTS …` (`create_all` only makes indexes on *new*
    tables, so an ALTER-added indexed column needs this too).
Append only — never edit or reorder existing entries. The schema is frozen at
1.0.0: additive changes only (new tables / nullable-or-default columns), no
drops, renames, or restructures.
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
    # v6 (0.13.17): rolling rate windows on quotas
    "ALTER TABLE quotas ADD COLUMN window_seconds INTEGER NOT NULL DEFAULT 0;"
    "ALTER TABLE quotas ADD COLUMN window_started_at TEXT NOT NULL DEFAULT '';",
    # v7 (0.13.19): packs can seed example processes (tagged for removal on disable)
    "ALTER TABLE processes ADD COLUMN pack TEXT NOT NULL DEFAULT '';",
    # ── SCHEMA FROZEN AT 1.0.0 ──────────────────────────────────────────────
    # Post-1.0 migrations are ADDITIVE ONLY: new tables, or new NULLable / DEFAULT
    # columns. No column drops/renames, no table restructures — never edit or
    # reorder the entries above. Append new additive migrations below this line.
    # v8 (1.1.0): packs can seed policy artifacts; policies carry a namespace
    "ALTER TABLE policies ADD COLUMN namespace TEXT NOT NULL DEFAULT '';"
    "ALTER TABLE policies ADD COLUMN pack TEXT NOT NULL DEFAULT '';",
    # v9 (1.2.0): governance layer graph — artifact axis (factory>harness>charter)
    "ALTER TABLE policies ADD COLUMN layer TEXT NOT NULL DEFAULT 'charter';",
    # v10 (1.4.0): explicit source integration per repo (for ingest)
    "ALTER TABLE repositories ADD COLUMN integration_id TEXT;",
    # v11 (1.4.1): catch up indexes for pack columns added by ALTER (create_all
    # only makes indexes on *new* tables, so upgraded installs missed these).
    "CREATE INDEX IF NOT EXISTS ix_policies_pack ON policies (pack);"
    "CREATE INDEX IF NOT EXISTS ix_processes_pack ON processes (pack);",
    # v12 (1.8.0): scheduled ingest cadence per repo
    "ALTER TABLE repositories ADD COLUMN ingest_interval_hours INTEGER NOT NULL DEFAULT 0;"
    "ALTER TABLE repositories ADD COLUMN last_ingest_at TEXT NOT NULL DEFAULT '';",
    # v13 (1.15.0): a user belongs to a team (cost attribution + concurrency caps).
    # ALTER-added indexed column → create the index too (create_all only indexes
    # new tables). Teams + ledger_entries are new tables, handled by create_all.
    "ALTER TABLE users ADD COLUMN team_id TEXT;"
    "CREATE INDEX IF NOT EXISTS ix_users_team_id ON users (team_id);",
    # v14 (1.16.0): routing policy inputs — targets carry region, compliance tags,
    # and a per-unit cost so route resolution can filter/prefer on them.
    "ALTER TABLE targets ADD COLUMN region TEXT NOT NULL DEFAULT '';"
    "ALTER TABLE targets ADD COLUMN compliance TEXT NOT NULL DEFAULT '[]';"
    "ALTER TABLE targets ADD COLUMN unit_cost INTEGER NOT NULL DEFAULT 0;",
    # v15 (1.17.0): harness identities — a coding agent (Claude Code, LangGraph, …)
    # is a service-account user (kind='agent') owned by a person, governed by its
    # role like anyone. Its token authenticates the CLI to the platform.
    "ALTER TABLE users ADD COLUMN kind TEXT NOT NULL DEFAULT 'human';"
    "ALTER TABLE users ADD COLUMN harness_kind TEXT;"
    "ALTER TABLE users ADD COLUMN owner_id TEXT;",
]

# Reverse of each MIGRATIONS entry (same index), for downgrading to a pinned
# version. ⚠ Downgrading is DESTRUCTIVE — dropping a column drops its data.
# Kept in sync with MIGRATIONS (append the reverse whenever you append an entry).
DOWNGRADES: list[str] = [
    "ALTER TABLE work_items DROP COLUMN external_ref;",                                  # v1
    "ALTER TABLE processes DROP COLUMN min_approver_role;",                              # v2
    "ALTER TABLE processes DROP COLUMN approval_chain;",                                 # v3
    "ALTER TABLE targets DROP COLUMN output_schema;",                                    # v4
    "ALTER TABLE policies DROP COLUMN kind;"
    "ALTER TABLE policies DROP COLUMN strict;"
    "ALTER TABLE policies DROP COLUMN content;",                                         # v5
    "ALTER TABLE quotas DROP COLUMN window_seconds;"
    "ALTER TABLE quotas DROP COLUMN window_started_at;",                                 # v6
    "ALTER TABLE processes DROP COLUMN pack;",                                           # v7
    "ALTER TABLE policies DROP COLUMN namespace;"
    "ALTER TABLE policies DROP COLUMN pack;",                                            # v8
    "ALTER TABLE policies DROP COLUMN layer;",                                           # v9
    "ALTER TABLE repositories DROP COLUMN integration_id;",                              # v10
    "DROP INDEX IF EXISTS ix_policies_pack;"
    "DROP INDEX IF EXISTS ix_processes_pack;",                                           # v11
    "ALTER TABLE repositories DROP COLUMN ingest_interval_hours;"
    "ALTER TABLE repositories DROP COLUMN last_ingest_at;",                              # v12
    "DROP INDEX IF EXISTS ix_users_team_id;"
    "ALTER TABLE users DROP COLUMN team_id;",                                            # v13
    "ALTER TABLE targets DROP COLUMN region;"
    "ALTER TABLE targets DROP COLUMN compliance;"
    "ALTER TABLE targets DROP COLUMN unit_cost;",                                        # v14
    "ALTER TABLE users DROP COLUMN kind;"
    "ALTER TABLE users DROP COLUMN harness_kind;"
    "ALTER TABLE users DROP COLUMN owner_id;",                                           # v15
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


def migrate_to(conn: sqlite3.Connection, target: int) -> int:
    """Migrate up or down to a target schema version. Returns the version reached.

    Down-migrations are destructive (dropping a column drops its data) — the CLI
    warns before running one. Assumes DOWNGRADES stays aligned with MIGRATIONS.
    """
    assert len(DOWNGRADES) == len(MIGRATIONS), "DOWNGRADES must mirror MIGRATIONS"
    n = len(MIGRATIONS)
    target = max(0, min(target, n))
    cur = _version(conn)
    if target > cur:                       # up
        for i in range(cur, target):
            conn.executescript(MIGRATIONS[i])
            conn.execute(f"PRAGMA user_version = {i + 1}")
    elif target < cur:                     # down (reverse order)
        for i in range(cur - 1, target - 1, -1):
            conn.executescript(DOWNGRADES[i])
            conn.execute(f"PRAGMA user_version = {i}")
    conn.commit()
    return target


def stamp_latest(conn: sqlite3.Connection) -> None:
    """Mark a fresh DB (built at the latest shape) as fully migrated."""
    conn.execute(f"PRAGMA user_version = {len(MIGRATIONS)}")
    conn.commit()
