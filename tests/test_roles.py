import pytest

from open_refinery import (
    PolicyDenied,
    at_least,
    connect,
    create_role,
    create_user,
    delete_role,
    list_roles,
    valid_role,
)
from open_refinery.users import RoleInUse


def test_admin_can_configure_roles():
    conn = connect("sqlite:///:memory:")
    create_role(conn, "senior", 15)  # insert a tier between developer(1) and platform(2)... arbitrary rank
    assert valid_role(conn, "senior") and at_least(conn, "senior", "platform")
    create_role(conn, "senior", 1)   # re-rank in place
    assert not at_least(conn, "senior", "platform")
    delete_role(conn, "senior")
    assert not valid_role(conn, "senior")


def test_builtin_roles_are_protected():
    """All four are load-bearing: the guards and the standard configuration
    assume they exist."""
    conn = connect("sqlite:///:memory:")
    for name in ("developer", "lead", "platform", "admin", "auditor"):
        with pytest.raises(ValueError, match="built-in"):
            delete_role(conn, name)


def test_a_custom_role_in_use_cannot_be_removed():
    conn = connect("sqlite:///:memory:")
    create_role(conn, "reviewer", 2)
    create_user(conn, "d@x.dev", "pw", "reviewer")
    with pytest.raises(RoleInUse):
        delete_role(conn, "reviewer")


def test_default_roles_seeded():
    conn = connect("sqlite:///:memory:")
    names = [r.name for r in list_roles(conn)]
    # `auditor` is the role a time-boxed audit grant resolves to — it existed
    # as a bare string before authority.py and now has a row.
    assert names == ["auditor", "developer", "lead", "platform", "admin"]  # by rank
    assert valid_role(conn, "developer") and not valid_role(conn, "senior")


def test_role_ladder():
    """`at_least` is an ordering for approval chains — not an authority check."""
    conn = connect("sqlite:///:memory:")
    assert at_least(conn, "platform", "platform") and at_least(conn, "admin", "platform")
    assert not at_least(conn, "developer", "platform")


def test_at_least_fails_closed_on_an_unknown_role():
    """It used to fail OPEN: role_rank() returns 0 for a role that does not
    exist, so at_least(developer, 'senior') was True — and migration v2 set
    exactly that as every process's default min_approver_role, leaving those
    processes with no effective approval minimum at all."""
    conn = connect("sqlite:///:memory:")
    assert at_least(conn, "developer", "senior") is False
    assert at_least(conn, "senior", "developer") is False


def test_role_rank_no_longer_decides_anything_that_ships(monkeypatch):
    """After 3.0 the only thing reading role *rank* is the governance proposal
    chain, which uses it as ordering — who signs after whom. Nothing that gates
    an action reads it: policies match permissions, packs need approve:charter,
    and granting a preset compares what you hold."""
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    from open_refinery import grants_beyond
    from open_refinery.packs import enable_pack

    conn = connect("sqlite:///:memory:")
    admin, _ = create_user(conn, "admin@x.dev", "pw", "admin")
    lead, _ = create_user(conn, "lead@x.dev", "pw", "lead")

    # admin outranks lead and still may not touch the standards
    with pytest.raises(PolicyDenied, match="approve:charter"):
        enable_pack(conn, "tdd", admin)
    enable_pack(conn, "tdd", lead)

    # ...nor mint an agent that approves code, which it does not hold itself
    assert grants_beyond(conn, "developer", admin) == [
        "approve:code", "propose:charter", "propose:code",
        "propose:factory", "propose:harness", "run:factory"]
    assert grants_beyond(conn, "auditor", admin) == []   # admin holds read:audit
