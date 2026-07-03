import pytest

from open_refinery import (
    AttestationFailed,
    AttestationMissing,
    SqliteSink,
    attest,
    attestations_for,
    connect,
    create_process,
    create_repository,
    create_user,
    create_work_item,
    query_events,
    transition,
)


def fixture(checks):
    conn = connect("sqlite:///:memory:")
    ian, _ = create_user(conn, "ian@x.dev", "pw", "developer")
    repo = create_repository(conn, "or", "git@x:or.git", ian.id)
    proc = create_process(conn, "flow", "board", ["todo", "review", "done"], ian.id,
                          checks=checks)
    item = create_work_item(conn, repo.id, proc.id, "T", ian.id)
    return conn, ian, item


def test_latest_attestation_wins():
    conn, ian, item = fixture({})
    audit = SqliteSink(conn)
    attest(conn, item.id, "tests", ian.id, False, audit)
    attest(conn, item.id, "tests", ian.id, True, audit)
    assert attestations_for(conn, item.id) == {"tests": True}


def test_missing_required_check_blocks_transition():
    conn, ian, item = fixture({"done": ["tests"]})
    audit = SqliteSink(conn)
    with pytest.raises(AttestationMissing):
        transition(conn, item.id, "done", ian.id, audit)
    assert query_events(conn, subject=item.id) == []  # move not applied


def test_failed_required_check_blocks_transition():
    conn, ian, item = fixture({"done": ["tests"]})
    audit = SqliteSink(conn)
    attest(conn, item.id, "tests", ian.id, False, audit)
    with pytest.raises(AttestationFailed):
        transition(conn, item.id, "done", ian.id, audit)


def test_passing_checks_allow_transition_and_audit():
    conn, ian, item = fixture({"done": ["tests", "codehealth"]})
    audit = SqliteSink(conn)
    attest(conn, item.id, "tests", ian.id, True, audit)
    attest(conn, item.id, "codehealth", ian.id, True, audit)
    moved = transition(conn, item.id, "done", ian.id, audit)
    assert moved.current_stage == "done"
    recipes = sorted(e.recipe for e in query_events(conn, subject=item.id))
    assert recipes == ["attestation", "attestation", "transition"]


def test_checks_gate_every_level_even_dark():
    # dark oversight = no approval, but checks still gate the move
    conn, ian, item = fixture({"review": ["lint"]})
    audit = SqliteSink(conn)
    with pytest.raises(AttestationMissing):
        transition(conn, item.id, "review", ian.id, audit)


def test_bad_check_step_rejected():
    conn = connect("sqlite:///:memory:")
    ian, _ = create_user(conn, "ian@x.dev", "pw", "developer")
    with pytest.raises(ValueError):
        create_process(conn, "x", "board", ["a", "b"], ian.id, checks={"z": ["t"]})


def test_attest_unknown_item():
    conn, ian, _ = fixture({})
    with pytest.raises(ValueError):
        attest(conn, "ghost", "tests", ian.id, True, SqliteSink(conn))
