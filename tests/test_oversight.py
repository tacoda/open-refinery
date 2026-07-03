import pytest

from open_refinery import (
    ApprovalRequired,
    SqliteSink,
    connect,
    create_process,
    create_repository,
    create_user,
    create_work_item,
    query_events,
    requires_approval,
    transition,
)


def test_requires_approval_matrix():
    gates = frozenset({"patch"})
    assert requires_approval("manual", "anything", gates) is True
    assert requires_approval("assisted", "anything", gates) is True
    assert requires_approval("supervised", "patch", gates) is True   # gated step
    assert requires_approval("supervised", "triage", gates) is False  # ungated step
    assert requires_approval("autonomous", "patch", gates) is False
    assert requires_approval("dark", "patch", gates) is False


def _fixture(oversight, gates=None):
    conn = connect("sqlite:///:memory:")
    ian, _ = create_user(conn, "ian@x.dev", "pw", "developer")
    boss, _ = create_user(conn, "boss@x.dev", "pw", "platform")
    repo = create_repository(conn, "or", "git@x:or.git", ian.id)
    proc = create_process(conn, "flow", "board", ["todo", "doing", "done"], ian.id,
                          oversight=oversight, gates=gates)
    item = create_work_item(conn, repo.id, proc.id, "T", ian.id)
    return conn, ian, boss, item


def test_dark_transitions_without_approval():
    conn, ian, _, item = _fixture("dark")
    audit = SqliteSink(conn)
    moved = transition(conn, item.id, "doing", ian.id, audit)
    assert moved.current_stage == "doing"
    assert [e.recipe for e in query_events(conn, subject=item.id)] == ["transition"]


def test_assisted_blocks_without_approver():
    conn, ian, boss, item = _fixture("assisted")
    audit = SqliteSink(conn)
    with pytest.raises(ApprovalRequired):
        transition(conn, item.id, "doing", ian.id, audit)
    # nothing applied or recorded
    assert query_events(conn, subject=item.id) == []


def test_assisted_applies_with_approver_and_audits_both():
    conn, ian, boss, item = _fixture("assisted")
    audit = SqliteSink(conn)
    moved = transition(conn, item.id, "doing", ian.id, audit, approver_id=boss.id)
    assert moved.current_stage == "doing"
    recipes = sorted(e.recipe for e in query_events(conn, subject=item.id))
    assert recipes == ["approval", "transition"]


def test_supervised_only_gates_named_steps():
    conn, ian, boss, item = _fixture("supervised", gates=["done"])
    audit = SqliteSink(conn)
    # ungated step: no approval needed
    transition(conn, item.id, "doing", ian.id, audit)
    # gated step: approval required
    with pytest.raises(ApprovalRequired):
        transition(conn, item.id, "done", ian.id, audit)
    transition(conn, item.id, "done", ian.id, audit, approver_id=boss.id)
    assert sorted(e.recipe for e in query_events(conn, subject=item.id)) == [
        "approval", "transition", "transition",
    ]


def test_bad_oversight_and_gates_rejected():
    conn = connect("sqlite:///:memory:")
    ian, _ = create_user(conn, "ian@x.dev", "pw", "developer")
    with pytest.raises(ValueError):
        create_process(conn, "x", "board", ["a", "b"], ian.id, oversight="loose")
    with pytest.raises(ValueError):
        create_process(conn, "x", "board", ["a", "b"], ian.id, gates=["z"])
