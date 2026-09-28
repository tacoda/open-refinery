import pytest

from open_refinery import (
    ConcurrencyExceeded,
    connect,
    create_team,
    create_user,
    delete_team,
    in_flight,
    list_teams,
    set_user_team,
    slot,
)


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
