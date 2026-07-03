import pytest

from open_refinery import (
    InvalidTransition,
    SqliteSink,
    UnknownWorkItem,
    connect,
    create_process,
    create_repository,
    create_user,
    create_work_item,
    get_work_item,
    list_work_items,
    query_events,
    transition,
)


def setup():
    conn = connect("sqlite:///:memory:")
    ian, _ = create_user(conn, "ian@tacoda.dev", "s3cret", "developer")
    repo = create_repository(conn, "or", "git@x:or.git", ian.id)
    proc = create_process(conn, "remediate", "doctrine",
                          ["detect", "triage", "patch", "verify", "close"], ian.id,
                          transitions=[("detect", "triage"), ("triage", "patch"),
                                       ("patch", "verify"), ("verify", "close"),
                                       ("verify", "patch")])  # feedback loop
    return conn, ian, repo, proc


def test_create_starts_at_initial_stage():
    conn, ian, repo, proc = setup()
    item = create_work_item(conn, repo.id, proc.id, "CVE-123", ian.id)
    assert item.current_stage == "detect"
    assert get_work_item(conn, item.id) == item


def test_transition_moves_and_audits():
    conn, ian, repo, proc = setup()
    audit = SqliteSink(conn)
    item = create_work_item(conn, repo.id, proc.id, "CVE-123", ian.id)

    moved = transition(conn, item.id, "triage", ian.id, audit)
    assert moved.current_stage == "triage"
    assert get_work_item(conn, item.id).current_stage == "triage"

    # audit trail records the transition, subject = the work item
    history = query_events(conn, subject=item.id)
    assert len(history) == 1
    assert history[0].recipe == "transition"
    assert history[0].actor == ian.id


def test_full_history_including_feedback_loop():
    conn, ian, repo, proc = setup()
    audit = SqliteSink(conn)
    item = create_work_item(conn, repo.id, proc.id, "CVE-123", ian.id)
    for step in ["triage", "patch", "verify", "patch", "verify", "close"]:
        transition(conn, item.id, step, ian.id, audit)
    assert get_work_item(conn, item.id).current_stage == "close"
    assert len(query_events(conn, subject=item.id)) == 6  # loop steps all recorded


def test_illegal_transition_rejected_and_not_audited():
    conn, ian, repo, proc = setup()
    audit = SqliteSink(conn)
    item = create_work_item(conn, repo.id, proc.id, "CVE-123", ian.id)
    with pytest.raises(InvalidTransition):
        transition(conn, item.id, "close", ian.id, audit)  # detect -> close not allowed
    assert get_work_item(conn, item.id).current_stage == "detect"  # unchanged
    assert query_events(conn, subject=item.id) == []  # nothing recorded


def test_unknown_item_and_actor():
    conn, ian, repo, proc = setup()
    audit = SqliteSink(conn)
    item = create_work_item(conn, repo.id, proc.id, "CVE-123", ian.id)
    with pytest.raises(UnknownWorkItem):
        transition(conn, "ghost", "triage", ian.id, audit)
    with pytest.raises(ValueError):
        transition(conn, item.id, "triage", "ghost-actor", audit)


def test_list_scoping():
    conn, ian, repo, proc = setup()
    mal, _ = create_user(conn, "mal@x.dev", "pw", "developer")
    create_work_item(conn, repo.id, proc.id, "a", ian.id)
    create_work_item(conn, repo.id, proc.id, "b", mal.id)
    assert len(list_work_items(conn)) == 2
    assert len(list_work_items(conn, owner_id=ian.id)) == 1
    assert len(list_work_items(conn, repo_id=repo.id)) == 2
