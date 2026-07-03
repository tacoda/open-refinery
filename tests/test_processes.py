import pytest

from open_refinery import (
    connect,
    create_process,
    create_user,
    get_process,
    list_processes,
)


def setup():
    conn = connect("sqlite:///:memory:")
    ian, _ = create_user(conn, "ian@tacoda.dev", "s3cret", "platform")
    return conn, ian


def test_doctrine_is_forward_linear():
    conn, ian = setup()
    p = create_process(conn, "remediate", "doctrine",
                       ["detect", "triage", "patch", "verify", "close"], ian.id)
    assert p.initial == "detect"
    assert p.can_transition("detect", "triage")
    assert p.can_transition("verify", "close")
    assert not p.can_transition("close", "verify")  # no implicit feedback


def test_board_allows_free_movement():
    conn, ian = setup()
    p = create_process(conn, "kanban", "board", ["todo", "doing", "done"], ian.id)
    assert p.can_transition("todo", "done")
    assert p.can_transition("done", "todo")
    assert not p.can_transition("todo", "todo")  # no self-loop


def test_feedback_loop_via_explicit_transitions():
    conn, ian = setup()
    # verify -> patch is a feedback loop (rework on failed verification)
    p = create_process(
        conn, "remediate", "doctrine",
        ["detect", "triage", "patch", "verify", "close"], ian.id,
        transitions=[
            ("detect", "triage"), ("triage", "patch"), ("patch", "verify"),
            ("verify", "close"), ("verify", "patch"),  # <- feedback loop
        ],
    )
    assert p.can_transition("patch", "verify")
    assert p.can_transition("verify", "patch")  # loop honored
    assert get_process(conn, p.id) == p  # round-trips through storage


def test_round_trip_and_scoping():
    conn, ian = setup()
    mal, _ = create_user(conn, "mal@x.dev", "pw", "developer")
    create_process(conn, "a", "board", ["x", "y"], ian.id)
    create_process(conn, "b", "board", ["x", "y"], mal.id)
    assert len(list_processes(conn)) == 2
    assert len(list_processes(conn, owner_id=ian.id)) == 1


def test_validation():
    conn, ian = setup()
    with pytest.raises(ValueError):
        create_process(conn, "bad", "kanban", ["a"], ian.id)  # unknown archetype
    with pytest.raises(ValueError):
        create_process(conn, "empty", "board", [], ian.id)  # no stages
    with pytest.raises(ValueError):
        create_process(conn, "bad-init", "board", ["a"], ian.id, initial="z")
    with pytest.raises(ValueError):
        create_process(conn, "bad-trans", "board", ["a", "b"], ian.id,
                       transitions=[("a", "z")])  # unknown stage in transition
