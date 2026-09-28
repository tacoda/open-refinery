from open_refinery import (
    connect,
    create_repository,
    create_user,
    create_work_item,
    summary,
    wip_by_stage,
)
from open_refinery.pipeline import store as ps


def build():
    """Two tickets: one never run, one run and landed. The stages the board
    shows are read off the runs, not off a column somebody dragged a card into."""
    conn = connect("sqlite:///:memory:")
    ian, _ = create_user(conn, "ian@x.dev", "pw", "developer")
    repo = create_repository(conn, "or", "git@x:or.git", ian.id)
    create_work_item(conn, repo.id, "A", ian.id)
    b = create_work_item(conn, repo.id, "B", ian.id)

    pipeline = ps.ensure_default(conn, ian.id)
    run = ps.start_run(conn, b.id, pipeline, repo.id, ian.id, spec="ship it")
    run.outcome = "landed"
    conn.add(run); conn.commit()
    return conn, ian


def test_wip_by_stage_is_derived_from_runs():
    conn, _ = build()
    assert wip_by_stage(conn) == {"open": 1, "landed": 1}


def test_wip_by_stage_scopes_to_owner():
    conn, ian = build()
    mal, _ = create_user(conn, "mal@x.dev", "pw", "developer")
    assert wip_by_stage(conn, owner_id=mal.id) == {}
    assert wip_by_stage(conn, owner_id=ian.id) == {"open": 1, "landed": 1}


def test_summary_counts_and_activity():
    conn, ian = build()
    s = summary(conn)
    assert s["wip_by_stage"] == {"open": 1, "landed": 1}
    assert s["event_counts"] == {}          # nothing audited in this fixture
    assert s["activity_by_actor"] == {}


def test_summary_scopes_to_owner():
    conn, ian = build()
    mal, _ = create_user(conn, "mal@x.dev", "pw", "developer")
    assert summary(conn, owner_id=mal.id)["wip_by_stage"] == {}
