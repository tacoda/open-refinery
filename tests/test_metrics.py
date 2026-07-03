from open_refinery import (
    SqliteSink,
    connect,
    create_process,
    create_repository,
    create_user,
    create_work_item,
    summary,
    transition,
    wip_by_stage,
)


def build():
    conn = connect("sqlite:///:memory:")
    ian, _ = create_user(conn, "ian@x.dev", "pw", "developer")
    repo = create_repository(conn, "or", "git@x:or.git", ian.id)
    proc = create_process(conn, "flow", "board", ["todo", "doing", "done"], ian.id)
    audit = SqliteSink(conn)
    a = create_work_item(conn, repo.id, proc.id, "A", ian.id)
    b = create_work_item(conn, repo.id, proc.id, "B", ian.id)
    transition(conn, a.id, "doing", ian.id, audit)
    transition(conn, b.id, "doing", ian.id, audit)
    transition(conn, b.id, "done", ian.id, audit)
    return conn, ian


def test_wip_by_stage():
    conn, _ = build()
    assert wip_by_stage(conn) == {"doing": 1, "done": 1}


def test_summary_counts_and_activity():
    conn, ian = build()
    s = summary(conn)
    assert s["event_counts"] == {"transition": 3}
    assert s["activity_by_actor"] == {ian.id: 3}
    assert s["lead_times"]["items"] == 2  # two items have events


def test_metrics_scope_to_owner():
    conn, ian = build()
    mal, _ = create_user(conn, "mal@x.dev", "pw", "developer")
    # mal owns nothing acted on
    assert summary(conn, owner_id=mal.id)["event_counts"] == {}
    assert summary(conn, owner_id=ian.id)["event_counts"] == {"transition": 3}
