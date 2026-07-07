import sqlite3

from sqlalchemy import text

from open_refinery import connect, run_migrations
from open_refinery.migrations import MIGRATIONS


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
            "ALTER TABLE targets DROP COLUMN region",
            "ALTER TABLE targets DROP COLUMN compliance",
            "ALTER TABLE targets DROP COLUMN unit_cost",
            "DROP TABLE systems",
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
        assert raw.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='systems'").fetchone()
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
