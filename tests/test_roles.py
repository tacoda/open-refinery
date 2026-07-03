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


def test_admin_role_and_in_use_role_protected():
    conn = connect("sqlite:///:memory:")
    with pytest.raises(ValueError):
        delete_role(conn, "admin")          # load-bearing, never removable
    create_user(conn, "d@x.dev", "pw", "developer")
    with pytest.raises(RoleInUse):
        delete_role(conn, "developer")      # still assigned to a user


def test_default_roles_seeded():
    conn = connect("sqlite:///:memory:")
    names = [r.name for r in list_roles(conn)]
    assert names == ["developer", "platform", "admin"]  # ordered by rank
    assert valid_role(conn, "developer") and not valid_role(conn, "senior")


def test_role_ladder():
    conn = connect("sqlite:///:memory:")
    assert at_least(conn, "platform", "platform") and at_least(conn, "admin", "platform")
    assert not at_least(conn, "developer", "platform")


def fixture():
    conn = connect("sqlite:///:memory:")
    dev, _ = create_user(conn, "dev@x.dev", "pw", "developer")
    dev2, _ = create_user(conn, "dev2@x.dev", "pw", "developer")
    platform, _ = create_user(conn, "platform@x.dev", "pw", "platform")
    repo = create_repository(conn, "or", "git@x:or.git", dev.id)
    # assisted process: every move needs approval (default approver = platform)
    proc = create_process(conn, "flow", "board", ["todo", "done"], dev.id, oversight="assisted")
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
