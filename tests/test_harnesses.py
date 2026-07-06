import pytest

from open_refinery import (
    PolicyDenied,
    SqliteSink,
    connect,
    create_policy,
    create_user,
    delete_harness,
    enforce,
    harness_view,
    list_harnesses,
    list_users,
    register_harness,
    rotate_harness,
    user_by_token,
)


def setup():
    conn = connect("sqlite:///:memory:")
    owner, _ = create_user(conn, "ian@x.dev", "pw", "developer")
    return conn, owner


def test_register_creates_owned_role_scoped_agent_with_a_working_token():
    conn, owner = setup()
    agent, token = register_harness(conn, "claude-code", "my claude", owner.id, "developer")
    assert agent.kind == "agent" and agent.harness_kind == "claude-code" and agent.owner_id == owner.id
    # the token authenticates the agent as an actor
    assert user_by_token(conn, token).id == agent.id


def test_agents_are_excluded_from_people_but_listed_as_harnesses():
    conn, owner = setup()
    agent, _ = register_harness(conn, "claude-code", "cc", owner.id, "developer")
    assert agent.id not in [u.id for u in list_users(conn)]              # humans only
    views = [harness_view(a) for a in list_harnesses(conn)]
    assert [v["id"] for v in views] == [agent.id]
    assert views[0]["name"] == "cc" and "token" not in views[0] and "token_hash" not in views[0]


def test_agent_actions_are_governed_by_its_role():
    conn, owner = setup()
    agent, _ = register_harness(conn, "claude-code", "cc", owner.id, "developer")
    create_policy(conn, "deny", owner.id, role="developer", action="invoke", resource="*")
    audit = SqliteSink(conn)
    # the proactive gate applies to the agent exactly as to a person of that role
    with pytest.raises(PolicyDenied):
        enforce(conn, agent.role, "invoke", "model", audit=audit, actor_id=agent.id)


def test_rotate_and_delete():
    conn, owner = setup()
    agent, token = register_harness(conn, "claude-code", "cc", owner.id, "developer")
    new = rotate_harness(conn, agent.id)
    assert user_by_token(conn, new).id == agent.id and user_by_token(conn, token) is None
    delete_harness(conn, agent.id)
    assert list_harnesses(conn) == []


def test_unknown_harness_kind_rejected():
    conn, owner = setup()
    with pytest.raises(ValueError):
        register_harness(conn, "nope", "x", owner.id, "developer")


def test_device_flow_lifecycle():
    from open_refinery import device_start, device_approve, device_poll, DevicePending, DeviceExpired
    conn, owner = setup()
    grant = device_start(conn, "claude-code", "cc")
    assert grant.user_code and grant.device_code and grant.status == "pending"
    # polling before approval → pending
    with pytest.raises(DevicePending):
        device_poll(conn, grant.device_code)
    # a human approves by user code → mints the agent
    device_approve(conn, grant.user_code, owner, "developer")
    token = device_poll(conn, grant.device_code)              # agent collects its token
    assert token and user_by_token(conn, token).kind == "agent"
    # token is returned once; a second poll fails (consumed)
    with pytest.raises(DeviceExpired):
        device_poll(conn, grant.device_code)


def test_device_approve_rejects_unknown_code():
    from open_refinery import device_approve
    conn, owner = setup()
    with pytest.raises(ValueError):
        device_approve(conn, "NOPE-NOPE", owner, "developer")


def test_device_agent_role_cannot_exceed_approver():
    from open_refinery import device_start, device_approve
    conn, _ = setup()
    dev, _ = create_user(conn, "d2@x.dev", "pw", "developer")
    g = device_start(conn, "claude-code", "cc")
    with pytest.raises(ValueError):  # dev can't mint an admin agent
        device_approve(conn, g.user_code, dev, "admin")
