import pytest

from open_refinery import (
    EXECUTORS,
    ExecutionError,
    PolicyDenied,
    QuotaExceeded,
    SqliteSink,
    connect,
    create_policy,
    create_process,
    create_quota,
    create_route,
    create_target,
    create_team,
    create_user,
    execute,
    query_events,
    set_user_team,
    team_usage,
)


def setup(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    conn = connect("sqlite:///:memory:")
    ian, _ = create_user(conn, "ian@x.dev", "pw", "developer")
    boss, _ = create_user(conn, "boss@x.dev", "pw", "platform")
    proc = create_process(conn, "flow", "board", ["draft", "run"], ian.id)
    return conn, ian, boss, proc


def test_execute_runs_pipeline_and_audits(monkeypatch):
    conn, ian, boss, proc = setup(monkeypatch)
    t = create_target(conn, "opus", "model", "claude-opus-4-8", ian.id)
    create_route(conn, proc.id, t.id, ian.id)
    r = execute(conn, ian.id, proc.id, "hello", SqliteSink(conn), step="run")
    assert r["target"] == "opus" and "hello" in r["output"]
    assert [e.recipe for e in query_events(conn)] == ["invoke"]


def test_execute_attributes_units_to_actor_team(monkeypatch):
    conn, ian, boss, proc = setup(monkeypatch)
    team = create_team(conn, "core", boss.id)
    set_user_team(conn, ian.id, team.id)
    t = create_target(conn, "opus", "model", "claude-opus-4-8", ian.id)
    create_route(conn, proc.id, t.id, ian.id)
    r = execute(conn, ian.id, proc.id, "hello", SqliteSink(conn), step="run")
    assert team_usage(conn, team.id) == r["units"] > 0  # ledger attributed to the team


def test_no_route_raises(monkeypatch):
    conn, ian, boss, proc = setup(monkeypatch)
    with pytest.raises(ExecutionError):
        execute(conn, ian.id, proc.id, "hi", SqliteSink(conn))


def test_content_filtered_in_and_out(monkeypatch):
    conn, ian, boss, proc = setup(monkeypatch)
    t = create_target(conn, "echo", "model", "m", ian.id)
    create_route(conn, proc.id, t.id, ian.id)
    r = execute(conn, ian.id, proc.id, "email me at a@b.com", SqliteSink(conn))
    assert "a@b.com" not in r["output"] and "email" in r["redactions"]


def test_policy_denies_invocation(monkeypatch):
    conn, ian, boss, proc = setup(monkeypatch)
    t = create_target(conn, "m", "model", "m", ian.id)
    create_route(conn, proc.id, t.id, ian.id)
    create_policy(conn, "deny", boss.id, role="developer", action="invoke", resource="model")
    with pytest.raises(PolicyDenied):
        execute(conn, ian.id, proc.id, "hi", SqliteSink(conn))


def test_quota_blocks_invocation(monkeypatch):
    conn, ian, boss, proc = setup(monkeypatch)
    t = create_target(conn, "m", "model", "m", ian.id)
    create_route(conn, proc.id, t.id, ian.id)
    create_quota(conn, t.id, limit=1, owner_id=ian.id)
    execute(conn, ian.id, proc.id, "one", SqliteSink(conn))     # 1/1
    with pytest.raises(QuotaExceeded):
        execute(conn, ian.id, proc.id, "two", SqliteSink(conn))  # blocked


def test_failover_to_next_route(monkeypatch):
    conn, ian, boss, proc = setup(monkeypatch)
    primary = create_target(conn, "primary", "model", "m1", ian.id)   # will fail
    backup = create_target(conn, "backup", "api", "http://b", ian.id)  # will succeed
    create_route(conn, proc.id, primary.id, ian.id, priority=10)
    create_route(conn, proc.id, backup.id, ian.id, priority=1)

    def boom(target, cred, payload):
        raise RuntimeError("provider down")
    monkeypatch.setitem(EXECUTORS, "model", boom)
    # backup is a real 'api' backend now — stub it so failover has somewhere to land
    monkeypatch.setitem(EXECUTORS, "api", lambda t, c, p: {"output": "ok", "units": 1})

    r = execute(conn, ian.id, proc.id, "hi", SqliteSink(conn))
    assert r["target"] == "backup"  # failed over
    recipes = sorted(e.recipe for e in query_events(conn))
    assert recipes == ["invoke", "invoke-failed"]
