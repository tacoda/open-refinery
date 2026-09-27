import pytest

from open_refinery import (
    PolicyDenied,
    SqliteSink,
    at_least,
    connect,
    create_process,
    create_repository,
    create_role,
    create_user,
    create_work_item,
    delete_role,
    list_roles,
    transition,
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


def fixture():
    conn = connect("sqlite:///:memory:")
    dev, _ = create_user(conn, "dev@x.dev", "pw", "developer")
    dev2, _ = create_user(conn, "dev2@x.dev", "pw", "developer")
    platform, _ = create_user(conn, "platform@x.dev", "pw", "platform")
    repo = create_repository(conn, "or", "git@x:or.git", dev.id)
    # assisted process: every move needs approval (default approver = platform)
    proc = create_process(conn, "flow", "board", ["todo", "done"], dev.id, oversight="assisted")  # min approver: lead
    item = create_work_item(conn, repo.id, proc.id, "T", dev.id)
    return conn, dev, dev2, platform, item


def test_developer_cannot_approve_risky_move():
    conn, dev, dev2, platform, item = fixture()
    audit = SqliteSink(conn)
    with pytest.raises(PolicyDenied):
        transition(conn, item.id, "done", dev.id, audit, approver_id=dev2.id)  # dev approving dev


def test_platform_can_approve():
    conn, dev, dev2, platform, item = fixture()
    audit = SqliteSink(conn)
    moved = transition(conn, item.id, "done", dev.id, audit, approver_id=platform.id)
    assert moved.current_stage == "done"
