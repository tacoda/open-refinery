import pytest

from open_refinery import (
    QuotaExceeded,
    connect,
    consume_quota,
    create_process,
    create_quota,
    create_route,
    create_target,
    create_user,
    list_targets,
    resolve_target,
    target_credential,
)


def setup():
    conn = connect("sqlite:///:memory:")
    ian, _ = create_user(conn, "ian@x.dev", "pw", "platform")
    return conn, ian


def test_create_target_and_encrypted_credential(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    conn, ian = setup()
    t = create_target(conn, "gpt", "model", "claude-opus-4-8", ian.id,
                      credential={"api_key": "sk-xyz"})
    assert t.kind == "model" and t.endpoint == "claude-opus-4-8"
    assert "sk-xyz" not in t.secret  # encrypted
    assert target_credential(conn, t.id) == {"api_key": "sk-xyz"}


def test_target_without_credential():
    conn, ian = setup()
    t = create_target(conn, "local-mcp", "mcp", "http://localhost:9000", ian.id)
    assert t.secret == "" and target_credential(conn, t.id) == {}


def test_unknown_kind_rejected():
    conn, ian = setup()
    with pytest.raises(ValueError):
        create_target(conn, "x", "database", "y", ian.id)


def test_routing_prefers_step_then_priority():
    conn, ian = setup()
    proc = create_process(conn, "flow", "board", ["a", "b"], ian.id)
    t_default = create_target(conn, "default", "model", "m1", ian.id)
    t_step = create_target(conn, "for-b", "model", "m2", ian.id)
    t_low = create_target(conn, "low", "model", "m3", ian.id)
    create_route(conn, proc.id, t_low.id, ian.id, priority=1)
    create_route(conn, proc.id, t_default.id, ian.id, priority=5)          # process-wide
    create_route(conn, proc.id, t_step.id, ian.id, step="b", priority=5)   # step-specific

    assert resolve_target(conn, proc.id, "a").id == t_default.id  # highest priority, no step match
    assert resolve_target(conn, proc.id, "b").id == t_step.id     # step-specific wins the tie
    assert resolve_target(conn, "nope", "a") is None


def test_quota_enforced_before_consume():
    conn, ian = setup()
    t = create_target(conn, "m", "model", "m1", ian.id)
    create_quota(conn, t.id, limit=2, owner_id=ian.id)
    consume_quota(conn, t.id)          # 1/2
    consume_quota(conn, t.id)          # 2/2
    with pytest.raises(QuotaExceeded):
        consume_quota(conn, t.id)      # would be 3/2 — blocked, nothing consumed

    # a target with no quota is unlimited
    free = create_target(conn, "free", "api", "http://x", ian.id)
    consume_quota(conn, free.id, units=100)
