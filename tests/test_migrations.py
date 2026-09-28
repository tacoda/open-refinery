import sqlite3

from sqlalchemy import text

from open_refinery import connect, run_migrations
from open_refinery.migrations import MIGRATIONS


# `targets` and `quotas` carried the pre-3.0 execution path. The models are gone,
# so `create_all` no longer builds them — but MIGRATIONS v4/v6/v14 still ALTER
# them, because an install that predates 3.0 still *has* them. These tests
# simulate that install, so they build the tables the way that install has them.
LEGACY_TABLES = (
    """CREATE TABLE IF NOT EXISTS targets (
        id TEXT PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL,
        endpoint TEXT NOT NULL, owner_id TEXT NOT NULL, secret TEXT NOT NULL DEFAULT '',
        output_schema TEXT NOT NULL DEFAULT '{}', region TEXT NOT NULL DEFAULT '',
        compliance TEXT NOT NULL DEFAULT '[]', unit_cost INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT '')""",
    """CREATE TABLE IF NOT EXISTS quotas (
        id TEXT PRIMARY KEY, target_id TEXT NOT NULL, "limit" INTEGER NOT NULL,
        used INTEGER NOT NULL DEFAULT 0, window_seconds INTEGER NOT NULL DEFAULT 0,
        window_started_at TEXT NOT NULL DEFAULT '', owner_id TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT '')""",
)


def _add_legacy_tables(raw) -> None:
    for stmt in LEGACY_TABLES:
        raw.execute(stmt)
    raw.commit()


def test_fresh_db_is_stamped_to_latest():
    session = connect("sqlite:///:memory:")
    version = session.exec(text("PRAGMA user_version")).one()[0]
    assert version == len(MIGRATIONS)


def test_run_migrations_applies_in_order_and_is_idempotent():
    conn = sqlite3.connect(":memory:")
    migs = [
        "CREATE TABLE t (x INTEGER)",
        "ALTER TABLE t ADD COLUMN y INTEGER",
    ]
    assert run_migrations(conn, migs) == 2
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 2
    # second run applies nothing
    assert run_migrations(conn, migs) == 0
    # both columns exist
    cols = {r[1] for r in conn.execute("PRAGMA table_info(t)")}
    assert cols == {"x", "y"}


def test_migration_evolves_an_older_db():
    # an older DB already applied migration 0; a new migration is appended
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE t (x INTEGER)")
    conn.execute("PRAGMA user_version = 1")
    applied = run_migrations(conn, ["-- v0 already applied",
                                    "ALTER TABLE t ADD COLUMN y INTEGER"])
    assert applied == 1  # only the new one ran
    assert "y" in {r[1] for r in conn.execute("PRAGMA table_info(t)")}


def test_upgrade_from_1_0_install_adds_new_schema(tmp_path):
    """A 1.0-era DB (schema v7, no systems table) upgrades cleanly: create_all adds
    new tables, run_migrations adds the new columns, version reaches latest."""
    from open_refinery.store import engine_for

    url = f"sqlite:///{tmp_path/'up.db'}"
    engine_for(url)  # build current schema, stamped to latest

    raw = engine_for(url).raw_connection()
    try:
        _add_legacy_tables(raw)          # a 1.0 install has these; 3.0 no longer builds them
        for stmt in (
            "DROP INDEX IF EXISTS ix_policies_pack",  # references policies.pack
            "ALTER TABLE policies DROP COLUMN namespace",
            "ALTER TABLE policies DROP COLUMN pack",
            "ALTER TABLE policies DROP COLUMN layer",
            "ALTER TABLE repositories DROP COLUMN integration_id",
            "ALTER TABLE repositories DROP COLUMN ingest_interval_hours",
            "ALTER TABLE repositories DROP COLUMN last_ingest_at",
            "DROP INDEX IF EXISTS ix_users_team_id",  # indexed → drop before column
            "ALTER TABLE users DROP COLUMN team_id",
            "ALTER TABLE users DROP COLUMN kind",
            "ALTER TABLE users DROP COLUMN harness_kind",
            "ALTER TABLE users DROP COLUMN owner_id",
            "DROP INDEX IF EXISTS ix_events_entry_hash",
            "ALTER TABLE events DROP COLUMN prev_hash",
            "ALTER TABLE events DROP COLUMN entry_hash",
            "DROP INDEX IF EXISTS ix_approval_requests_due_at",
            "ALTER TABLE processes DROP COLUMN approval_sla_hours",
            "ALTER TABLE approval_requests DROP COLUMN due_at",
            "ALTER TABLE approval_requests DROP COLUMN escalated_at",
            "ALTER TABLE users DROP COLUMN totp_secret",
            "ALTER TABLE users DROP COLUMN mfa_enabled",
            "ALTER TABLE users DROP COLUMN active",
            "ALTER TABLE targets DROP COLUMN region",
            "ALTER TABLE targets DROP COLUMN compliance",
            "ALTER TABLE targets DROP COLUMN unit_cost",
            "ALTER TABLE events DROP COLUMN chain_algo",
            "ALTER TABLE audit_chain_state DROP COLUMN algo",
            "ALTER TABLE audit_chain_state DROP COLUMN signature",
            "DROP INDEX IF EXISTS ix_integrations_kind",
            "ALTER TABLE integrations DROP COLUMN last_verified_at",
            "ALTER TABLE integrations DROP COLUMN status",
            "ALTER TABLE integrations DROP COLUMN status_detail",
            "ALTER TABLE integrations DROP COLUMN shared",
            "ALTER TABLE roles DROP COLUMN approves",
            "ALTER TABLE roles DROP COLUMN proposes",
            "ALTER TABLE roles DROP COLUMN manages_users",
            "ALTER TABLE roles DROP COLUMN reads_audit",
            "ALTER TABLE roles DROP COLUMN sees_operations",
            "ALTER TABLE roles DROP COLUMN builtin",
            "ALTER TABLE repositories DROP COLUMN charter_paths",
            "ALTER TABLE repositories DROP COLUMN base_branch",
            "ALTER TABLE repositories DROP COLUMN forge",
            "ALTER TABLE repositories DROP COLUMN max_revisions",
            "ALTER TABLE repositories DROP COLUMN prepare_cmd",
            "ALTER TABLE repositories DROP COLUMN cleanup_cmd",
            "ALTER TABLE repositories DROP COLUMN test_cmd",
            "ALTER TABLE users DROP COLUMN permissions",
            "ALTER TABLE roles DROP COLUMN permissions",
            "ALTER TABLE integrations DROP COLUMN webhook_secret",
            "ALTER TABLE integrations DROP COLUMN intake_repo_id",
            "ALTER TABLE integrations DROP COLUMN intake_process_id",
            "ALTER TABLE integrations DROP COLUMN intake_pipeline",
            "ALTER TABLE integrations DROP COLUMN autostart",
            "PRAGMA user_version = 7",   # pretend this is a 1.0-era install (schema v7)
        ):
            raw.execute(stmt)
        raw.commit()
    finally:
        raw.close()

    engine_for(url)  # reopen → _init_schema upgrades

    raw = engine_for(url).raw_connection()
    try:
        pol = {r[1] for r in raw.execute("PRAGMA table_info(policies)").fetchall()}
        assert {"namespace", "pack", "layer"} <= pol
        repo = {r[1] for r in raw.execute("PRAGMA table_info(repositories)").fetchall()}
        assert "integration_id" in repo
        usr = {r[1] for r in raw.execute("PRAGMA table_info(users)").fetchall()}
        assert "team_id" in usr
        # `create_all` adds tables an older install never had. `roles` is the
        # current example; `systems` was, until it went in 2.15.0.
        assert raw.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='roles'").fetchone()
        usr = {r[1] for r in raw.execute("PRAGMA table_info(users)").fetchall()}
        assert "permissions" in usr
        integ = {r[1] for r in raw.execute("PRAGMA table_info(integrations)").fetchall()}
        assert {"webhook_secret", "autostart"} <= integ
        assert raw.execute("PRAGMA user_version").fetchone()[0] == len(MIGRATIONS)
    finally:
        raw.close()


def test_migrate_down_then_up_round_trips(tmp_path):
    import sqlite3
    from open_refinery.migrations import migrate_to
    from open_refinery.store import engine_for

    url = f"sqlite:///{tmp_path/'rt.db'}"
    engine_for(url)  # latest (v11)
    raw = sqlite3.connect(tmp_path / "rt.db")
    try:
        _add_legacy_tables(raw)          # DOWNGRADES v6/v14 still ALTER them
        def pol_cols():
            return {r[1] for r in raw.execute("PRAGMA table_info(policies)").fetchall()}

        assert {"namespace", "pack", "layer"} <= pol_cols()
        migrate_to(raw, 4)                       # down past all policy-column adds
        assert not ({"namespace", "pack", "layer", "kind"} & pol_cols())
        assert raw.execute("PRAGMA user_version").fetchone()[0] == 4
        migrate_to(raw, len(MIGRATIONS))         # back up to latest
        assert {"namespace", "pack", "layer", "kind"} <= pol_cols()
        assert raw.execute("PRAGMA user_version").fetchone()[0] == len(MIGRATIONS)
    finally:
        raw.close()
