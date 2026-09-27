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
    # v16 (2.3.0): tamper-evident audit — hash-chain columns on events (entry_hash
    # indexed → create the index too). audit_chain_state is a new table.
    "ALTER TABLE events ADD COLUMN prev_hash TEXT NOT NULL DEFAULT '';"
    "ALTER TABLE events ADD COLUMN entry_hash TEXT NOT NULL DEFAULT '';"
    "CREATE INDEX IF NOT EXISTS ix_events_entry_hash ON events (entry_hash);",
    # v17 (2.7.0): approval SLAs + escalation. Processes carry an SLA (hours);
    # approval requests carry the derived deadline (indexed → overdue sweep) and
    # an escalation-emitted stamp (dedup).
    "ALTER TABLE processes ADD COLUMN approval_sla_hours INTEGER NOT NULL DEFAULT 0;"
    "ALTER TABLE approval_requests ADD COLUMN due_at TEXT NOT NULL DEFAULT '';"
    "ALTER TABLE approval_requests ADD COLUMN escalated_at TEXT NOT NULL DEFAULT '';"
    "CREATE INDEX IF NOT EXISTS ix_approval_requests_due_at ON approval_requests (due_at);",
    # v18 (2.10.0): TOTP MFA for local password accounts. totp_secret is encrypted
    # at rest; mfa_enabled flips true only after the enrollment code is confirmed.
    "ALTER TABLE users ADD COLUMN totp_secret TEXT NOT NULL DEFAULT '';"
    "ALTER TABLE users ADD COLUMN mfa_enabled INTEGER NOT NULL DEFAULT 0;",
    # v19 (2.11.0): SCIM deprovisioning soft-deactivates users (active=0) rather
    # than deleting them; inactive users can't authenticate.
    "ALTER TABLE users ADD COLUMN active INTEGER NOT NULL DEFAULT 1;",
    # v20 (2.13.0): the audit chain becomes keyed. Existing rows keep their
    # unkeyed sha256 hashes and still verify; everything written from here is
    # HMAC'd with a key derived from SECRET_KEY, so the chain cannot be
    # recomputed by anyone holding only the database.
    "ALTER TABLE events ADD COLUMN chain_algo TEXT NOT NULL DEFAULT 'sha256';",
    # v21 (2.13.0): the chain head is authenticated, so a wholesale rewrite that
    # relabels every row as the old unkeyed construction still fails.
    "ALTER TABLE audit_chain_state ADD COLUMN algo TEXT NOT NULL DEFAULT '';"
    "ALTER TABLE audit_chain_state ADD COLUMN signature TEXT NOT NULL DEFAULT '';",
    # v22 (2.14.0): integrations become the one credential store for models,
    # forges and trackers — with the verify outcome kept so the Connections
    # screen can show a key that has stopped working, and `shared` for the
    # org-wide model key an admin may publish.
    "ALTER TABLE integrations ADD COLUMN last_verified_at TEXT NOT NULL DEFAULT '';"
    "ALTER TABLE integrations ADD COLUMN status TEXT NOT NULL DEFAULT 'ok';"
    "ALTER TABLE integrations ADD COLUMN status_detail TEXT NOT NULL DEFAULT '';"
    "ALTER TABLE integrations ADD COLUMN shared INTEGER NOT NULL DEFAULT 0;"
    "CREATE INDEX IF NOT EXISTS ix_integrations_kind ON integrations (kind);",
    # v23 (2.14.5): authority becomes data on the role rather than a rank, and
    # the four built-ins are seeded/backfilled by `ensure_default_roles`.
    "ALTER TABLE roles ADD COLUMN approves TEXT NOT NULL DEFAULT '[]';"
    "ALTER TABLE roles ADD COLUMN proposes TEXT NOT NULL DEFAULT '[]';"
    "ALTER TABLE roles ADD COLUMN manages_users INTEGER NOT NULL DEFAULT 0;"
    "ALTER TABLE roles ADD COLUMN reads_audit INTEGER NOT NULL DEFAULT 0;"
    "ALTER TABLE roles ADD COLUMN sees_operations INTEGER NOT NULL DEFAULT 0;"
    "ALTER TABLE roles ADD COLUMN builtin INTEGER NOT NULL DEFAULT 0;"
    # Repair the fail-open. Migration v2 defaulted min_approver_role to
    # 'senior', a role nothing ever seeded — and because role_rank() returns 0
    # for an unknown role, at_least(developer, 'senior') was TRUE. Every process
    # left on that default had no effective approval minimum.
    "UPDATE processes SET min_approver_role = 'lead' WHERE min_approver_role = 'senior';"
    "UPDATE approval_requests SET required_roles = REPLACE(required_roles, '\"senior\"', '\"lead\"')"
    " WHERE required_roles LIKE '%senior%';",
    # v24 (2.15.0): a repo may say where its agent configuration lives.
    "ALTER TABLE repositories ADD COLUMN charter_paths TEXT NOT NULL DEFAULT '[]';",
    # v25 (2.16.0): permissions move onto the USER — that set is the only thing
    # checked. `roles` becomes a table of presets. Existing users are backfilled
    # from the preset they were created with, so an upgrade changes nobody's
    # access; a user left with an empty set could do nothing at all.
    "ALTER TABLE users ADD COLUMN permissions TEXT NOT NULL DEFAULT '[]';"
    "ALTER TABLE roles ADD COLUMN permissions TEXT NOT NULL DEFAULT '[]';"
    "UPDATE users SET permissions = '[\"approve:code\", \"propose:code\", \"propose:harness\", \"propose:factory\", \"propose:charter\", \"run:factory\"]' WHERE role = 'developer' AND permissions = '[]';UPDATE users SET permissions = '[\"approve:harness\", \"approve:charter\", \"propose:code\", \"propose:harness\", \"propose:factory\", \"propose:charter\", \"run:factory\"]' WHERE role = 'lead' AND permissions = '[]';UPDATE users SET permissions = '[\"approve:factory\", \"propose:factory\", \"see:operations\", \"run:factory\"]' WHERE role = 'platform' AND permissions = '[]';UPDATE users SET permissions = '[\"manage:users\", \"read:audit\"]' WHERE role = 'admin' AND permissions = '[]';UPDATE users SET permissions = '[\"read:audit\"]' WHERE role = 'auditor' AND permissions = '[]';"
    "UPDATE roles SET permissions = '[\"approve:code\", \"propose:code\", \"propose:harness\", \"propose:factory\", \"propose:charter\", \"run:factory\"]' WHERE name = 'developer';UPDATE roles SET permissions = '[\"approve:harness\", \"approve:charter\", \"propose:code\", \"propose:harness\", \"propose:factory\", \"propose:charter\", \"run:factory\"]' WHERE name = 'lead';UPDATE roles SET permissions = '[\"approve:factory\", \"propose:factory\", \"see:operations\", \"run:factory\"]' WHERE name = 'platform';UPDATE roles SET permissions = '[\"manage:users\", \"read:audit\"]' WHERE name = 'admin';UPDATE roles SET permissions = '[\"read:audit\"]' WHERE name = 'auditor';",
    # v26 (2.19.0): per-repository factory config. A repo says how the factory
    # works in it — what to branch from, which forge, how to set the worktree up.
    "ALTER TABLE repositories ADD COLUMN base_branch TEXT NOT NULL DEFAULT 'main';"
    "ALTER TABLE repositories ADD COLUMN forge TEXT NOT NULL DEFAULT '';"
    "ALTER TABLE repositories ADD COLUMN max_revisions INTEGER NOT NULL DEFAULT 2;"
    "ALTER TABLE repositories ADD COLUMN prepare_cmd TEXT NOT NULL DEFAULT '';"
    "ALTER TABLE repositories ADD COLUMN cleanup_cmd TEXT NOT NULL DEFAULT '';"
    "ALTER TABLE repositories ADD COLUMN test_cmd TEXT NOT NULL DEFAULT '';",
    # v27 (2.17.0): the factory's own tables — pipelines, runs, run steps. New
    # tables are created by `create_all`; this entry is the version bump so an
    # existing install records that it has them.
    "SELECT 1;",
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
    "DROP INDEX IF EXISTS ix_events_entry_hash;"
    "ALTER TABLE events DROP COLUMN prev_hash;"
    "ALTER TABLE events DROP COLUMN entry_hash;",                                        # v16
    "DROP INDEX IF EXISTS ix_approval_requests_due_at;"
    "ALTER TABLE processes DROP COLUMN approval_sla_hours;"
    "ALTER TABLE approval_requests DROP COLUMN due_at;"
    "ALTER TABLE approval_requests DROP COLUMN escalated_at;",                           # v17
    "ALTER TABLE users DROP COLUMN totp_secret;"
    "ALTER TABLE users DROP COLUMN mfa_enabled;",                                        # v18
    "ALTER TABLE users DROP COLUMN active;",                                             # v19
    "ALTER TABLE events DROP COLUMN chain_algo;",                                        # v20
    "ALTER TABLE audit_chain_state DROP COLUMN algo;"
    "ALTER TABLE audit_chain_state DROP COLUMN signature;",                              # v21
    "DROP INDEX IF EXISTS ix_integrations_kind;"
    "ALTER TABLE integrations DROP COLUMN last_verified_at;"
    "ALTER TABLE integrations DROP COLUMN status;"
    "ALTER TABLE integrations DROP COLUMN status_detail;"
    "ALTER TABLE integrations DROP COLUMN shared;",                                      # v22
    "ALTER TABLE roles DROP COLUMN approves;"
    "ALTER TABLE roles DROP COLUMN proposes;"
    "ALTER TABLE roles DROP COLUMN manages_users;"
    "ALTER TABLE roles DROP COLUMN reads_audit;"
    "ALTER TABLE roles DROP COLUMN sees_operations;"
    "ALTER TABLE roles DROP COLUMN builtin;",                                            # v23
    "ALTER TABLE repositories DROP COLUMN charter_paths;",                               # v24
    "ALTER TABLE users DROP COLUMN permissions;"
    "ALTER TABLE roles DROP COLUMN permissions;",                                        # v25
    "ALTER TABLE repositories DROP COLUMN base_branch;"
    "ALTER TABLE repositories DROP COLUMN forge;"
    "ALTER TABLE repositories DROP COLUMN max_revisions;"
    "ALTER TABLE repositories DROP COLUMN prepare_cmd;"
    "ALTER TABLE repositories DROP COLUMN cleanup_cmd;"
    "ALTER TABLE repositories DROP COLUMN test_cmd;",                                    # v26
    "DROP TABLE IF EXISTS run_steps;"
    "DROP TABLE IF EXISTS runs;"
    "DROP TABLE IF EXISTS pipelines;",                                                   # v27
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
