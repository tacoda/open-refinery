import sqlite3

from open_refinery import connect, run_migrations
from open_refinery.migrations import MIGRATIONS


def test_fresh_db_is_stamped_to_latest():
    conn = connect("sqlite:///:memory:")
    assert conn.execute("PRAGMA user_version").fetchone()[0] == len(MIGRATIONS)


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
