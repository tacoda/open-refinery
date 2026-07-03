import pytest

from open_refinery import (
    Policy,
    PolicyDenied,
    SqliteSink,
    connect,
    create_policy,
    create_process,
    create_repository,
    create_user,
    create_work_item,
    decide,
    list_policies,
    scan_content,
    transition,
)


def make_policy(effect, role="*", action="*", resource="*"):
    return Policy(effect=effect, role=role, action=action, resource=resource, owner_id="x")


def test_decide_default_allow_and_deny_overrides():
    assert decide([], "developer", "transition", "done") is True
    ps = [make_policy("deny", role="developer", action="transition", resource="done")]
    assert decide(ps, "developer", "transition", "done") is False
    assert decide(ps, "platform", "transition", "done") is True   # role doesn't match
    assert decide(ps, "developer", "transition", "review") is True  # resource doesn't match


def test_wildcards_match():
    ps = [make_policy("deny", role="developer", action="transition", resource="*")]
    assert decide(ps, "developer", "transition", "anything") is False


def setup():
    conn = connect("sqlite:///:memory:")
    ian, _ = create_user(conn, "ian@x.dev", "pw", "developer")
    boss, _ = create_user(conn, "boss@x.dev", "pw", "platform")
    repo = create_repository(conn, "or", "git@x:or.git", ian.id)
    proc = create_process(conn, "flow", "board", ["todo", "done"], ian.id)
    item = create_work_item(conn, repo.id, proc.id, "T", ian.id)
    return conn, ian, boss, item


def test_policy_blocks_transition_by_role():
    conn, ian, boss, item = setup()
    create_policy(conn, "deny", boss.id, role="developer", action="transition", resource="done")
    audit = SqliteSink(conn)
    with pytest.raises(PolicyDenied):
        transition(conn, item.id, "done", ian.id, audit)
    # platform user is not denied
    moved = transition(conn, item.id, "done", boss.id, audit)
    assert moved.current_stage == "done"


def test_policies_are_fleet_wide():
    conn, ian, boss, item = setup()
    create_policy(conn, "deny", boss.id, action="transition", resource="done")
    assert len(list_policies(conn)) == 1


def test_only_valid_effects():
    conn, ian, boss, _ = setup()
    with pytest.raises(ValueError):
        create_policy(conn, "maybe", boss.id)


def test_content_scan_redacts_secrets():
    text = "contact a@b.com with key AKIAABCDEFGHIJKLMNOP and gho_abcdefghijklmnopqrstuvwxyz012345"
    clean, hits = scan_content(text)
    assert "a@b.com" not in clean
    assert "AKIAABCDEFGHIJKLMNOP" not in clean
    assert set(hits) >= {"email", "aws-key", "bearer-token"}
    assert scan_content("nothing sensitive here") == ("nothing sensitive here", [])
