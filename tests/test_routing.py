import pytest

from open_refinery import (
    SqliteSink,
    connect,
    create_process,
    create_route,
    create_target,
    create_team,
    create_user,
    execute,
    resolve_targets,
    set_user_team,
    traffic_graph,
)
from open_refinery.settings import set_setting
from open_refinery.targets import ROUTING_POLICY_KEY


def setup(monkeypatch=None):
    if monkeypatch:
        monkeypatch.setenv("SECRET_KEY", "test-secret")
    conn = connect("sqlite:///:memory:")
    dev, _ = create_user(conn, "dev@x.dev", "pw", "developer")
    proc = create_process(conn, "flow", "board", ["run"], dev.id)
    return conn, dev, proc


def _policy(conn, dev, **policy):
    import json
    set_setting(conn, ROUTING_POLICY_KEY, json.dumps(policy), dev.id)


def test_routing_requires_region_and_compliance(monkeypatch):
    conn, dev, proc = setup(monkeypatch)
    eu = create_target(conn, "eu", "model", "m", dev.id, region="eu", compliance=["gdpr"])
    us = create_target(conn, "us", "model", "m", dev.id, region="us")
    for t in (eu, us):
        create_route(conn, proc.id, t.id, dev.id)

    assert {t.name for t in resolve_targets(conn, proc.id)} == {"eu", "us"}  # no policy
    _policy(conn, dev, require_region="eu")
    assert [t.name for t in resolve_targets(conn, proc.id)] == ["eu"]
    _policy(conn, dev, require_compliance=["gdpr"])
    assert [t.name for t in resolve_targets(conn, proc.id)] == ["eu"]        # only eu has gdpr


def test_prefer_cost_orders_cheapest_first_within_priority(monkeypatch):
    conn, dev, proc = setup(monkeypatch)
    cheap = create_target(conn, "cheap", "model", "m", dev.id, unit_cost=1)
    pricey = create_target(conn, "pricey", "model", "m", dev.id, unit_cost=9)
    create_route(conn, proc.id, cheap.id, dev.id, priority=0)
    create_route(conn, proc.id, pricey.id, dev.id, priority=0)
    _policy(conn, dev, prefer="cost")
    assert [t.name for t in resolve_targets(conn, proc.id)] == ["cheap", "pricey"]


def test_compliance_gate_blocking_all_targets_yields_no_route(monkeypatch):
    conn, dev, proc = setup(monkeypatch)
    t = create_target(conn, "plain", "model", "m", dev.id)
    create_route(conn, proc.id, t.id, dev.id)
    _policy(conn, dev, require_compliance=["hipaa"])
    assert resolve_targets(conn, proc.id) == []   # nothing compliant → executor sees no route


def test_traffic_graph_wires_actor_to_target(monkeypatch):
    conn, dev, proc = setup(monkeypatch)
    team = create_team(conn, "core", dev.id)
    set_user_team(conn, dev.id, team.id)
    t = create_target(conn, "opus", "model", "claude-opus-4-8", dev.id)
    create_route(conn, proc.id, t.id, dev.id)
    execute(conn, dev.id, proc.id, "hi", SqliteSink(conn), step="run")

    g = traffic_graph(conn)
    assert any(n["type"] == "actor" and n["team"] == "core" for n in g["nodes"])
    assert any(n["type"] == "target" and n["label"] == "opus" for n in g["nodes"])
    assert len(g["edges"]) == 1 and g["edges"][0]["count"] == 1 and g["edges"][0]["units"] > 0
