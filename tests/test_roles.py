import pytest

from open_refinery import (
    PolicyDenied,
    SqliteSink,
    at_least,
    connect,
    create_process,
    create_repository,
    create_user,
    create_work_item,
    transition,
)


def test_role_ladder():
    assert at_least("senior", "senior") and at_least("platform", "senior")
    assert at_least("admin", "senior")
    assert not at_least("developer", "senior")


def fixture():
    conn = connect("sqlite:///:memory:")
    dev, _ = create_user(conn, "dev@x.dev", "pw", "developer")
    dev2, _ = create_user(conn, "dev2@x.dev", "pw", "developer")
    senior, _ = create_user(conn, "senior@x.dev", "pw", "senior")
    repo = create_repository(conn, "or", "git@x:or.git", dev.id)
    # assisted process: every move needs approval
    proc = create_process(conn, "flow", "board", ["todo", "done"], dev.id, oversight="assisted")
    item = create_work_item(conn, repo.id, proc.id, "T", dev.id)
    return conn, dev, dev2, senior, item


def test_developer_cannot_approve_risky_move():
    conn, dev, dev2, senior, item = fixture()
    audit = SqliteSink(conn)
    with pytest.raises(PolicyDenied):
        transition(conn, item.id, "done", dev.id, audit, approver_id=dev2.id)  # dev approving dev


def test_senior_can_approve():
    conn, dev, dev2, senior, item = fixture()
    audit = SqliteSink(conn)
    moved = transition(conn, item.id, "done", dev.id, audit, approver_id=senior.id)
    assert moved.current_stage == "done"
