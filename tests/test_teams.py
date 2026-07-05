import pytest

from open_refinery import (
    ConcurrencyExceeded,
    connect,
    create_team,
    create_user,
    delete_team,
    in_flight,
    list_teams,
    record_usage,
    set_user_team,
    slot,
    team_usage,
    usage_by_team,
)
from open_refinery.settings import set_setting


def setup(monkeypatch=None):
    if monkeypatch:
        monkeypatch.setenv("SECRET_KEY", "test-secret")
    conn = connect("sqlite:///:memory:")
    owner, _ = create_user(conn, "own@x.dev", "pw", "platform")
    return conn, owner


def test_team_crud_and_membership():
    conn, owner = setup()
    t = create_team(conn, "core", owner.id, max_concurrency=2)
    assert t in list_teams(conn) and t.max_concurrency == 2
    dev, _ = create_user(conn, "dev@x.dev", "pw", "developer")
    assigned = set_user_team(conn, dev.id, t.id)
    assert assigned.team_id == t.id
    # deleting the team unassigns its members
    delete_team(conn, t.id)
    from open_refinery import User
    assert conn.get(User, dev.id).team_id is None
    assert not list_teams(conn)


def test_ledger_attributes_units_to_actor_team():
    conn, owner = setup()
    t = create_team(conn, "core", owner.id)
    a, _ = create_user(conn, "a@x.dev", "pw", "developer")
    b, _ = create_user(conn, "b@x.dev", "pw", "developer")
    set_user_team(conn, a.id, t.id)  # a on team, b unassigned
    record_usage(conn, a.id, "tgt-1", 10, subject="w1")
    record_usage(conn, a.id, "tgt-1", 5, subject="w2")
    record_usage(conn, b.id, "tgt-1", 3)
    assert team_usage(conn, t.id) == 15
    rollup = {r["team"]: r["units"] for r in usage_by_team(conn)}
    assert rollup["core"] == 15 and rollup["unassigned"] == 3


def test_concurrency_slot_caps_in_flight():
    # cap of 2: two slots held, a third raises; releasing frees capacity
    with slot("team-x", 2):
        with slot("team-x", 2):
            assert in_flight("team-x") == 2
            with pytest.raises(ConcurrencyExceeded):
                with slot("team-x", 2):
                    pass
        assert in_flight("team-x") == 1  # inner released
    assert in_flight("team-x") == 0


def test_concurrency_unlimited_without_team_or_cap():
    with slot(None, 5):        # no team → never caps
        with slot("t", 0):     # cap 0 → unlimited
            pass  # no raise
