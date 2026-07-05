from datetime import datetime, timedelta, timezone

from open_refinery import (
    connect,
    create_repository,
    create_user,
    due_repos,
    list_jobs,
    run_due_ingests,
    set_ingest_schedule,
)
from open_refinery.store import engine_for


def _now(offset_h=0):
    return (datetime.now(timezone.utc) + timedelta(hours=offset_h)).isoformat()


def setup():
    engine = engine_for("sqlite:///:memory:")
    from sqlmodel import Session
    conn = Session(engine)
    dev, _ = create_user(conn, "dev@x.dev", "pw", "developer")
    repo = create_repository(conn, "app", "git@github.com:acme/app.git", dev.id)
    return conn, engine, dev, repo


def test_manual_repo_never_due():
    conn, engine, dev, repo = setup()
    assert due_repos(conn) == []                       # interval 0 = manual


def test_scheduled_repo_due_when_never_ingested():
    conn, engine, dev, repo = setup()
    set_ingest_schedule(conn, repo.id, 24)
    assert [r.id for r in due_repos(conn)] == [repo.id]


def test_run_due_enqueues_and_stamps_then_not_due():
    conn, engine, dev, repo = setup()
    set_ingest_schedule(conn, repo.id, 24)
    scheduled = run_due_ingests(conn, engine)
    assert scheduled == [repo.id]
    assert len(list_jobs(conn)) == 1                   # a background ingest job was enqueued
    assert run_due_ingests(conn, engine) == []         # freshly stamped → not due again


def test_due_again_after_interval_elapses():
    conn, engine, dev, repo = setup()
    set_ingest_schedule(conn, repo.id, 1)
    run_due_ingests(conn, engine)                      # stamps last_ingest ~ now
    assert due_repos(conn) == []
    # 2h later it is due again
    assert [r.id for r in due_repos(conn, _now(2))] == [repo.id]
