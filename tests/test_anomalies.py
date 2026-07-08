from open_refinery import (
    Record,
    SqliteSink,
    connect,
    create_user,
    emit_anomalies,
    query_events,
    scan_anomalies,
)
from open_refinery.models import Event, now_iso


def _conn(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    return connect("sqlite:///:memory:")


def _write(audit, recipe, actor, n=1):
    for _ in range(n):
        audit.write(Record.of(recipe=recipe, actor=actor, owner=actor, inputs={},
                              output="x", subject="w1"))


def test_denial_spike_flagged(monkeypatch):
    conn = _conn(monkeypatch)
    _write(SqliteSink(conn), "denied", "u1", n=6)  # DENIAL_SPIKE = 5
    assert "denial-spike" in {f["kind"] for f in scan_anomalies(conn)}


def test_no_spike_below_threshold(monkeypatch):
    conn = _conn(monkeypatch)
    _write(SqliteSink(conn), "denied", "u1", n=3)
    assert not [f for f in scan_anomalies(conn) if f["kind"] == "denial-spike"]


def test_mass_change_by_actor_is_high(monkeypatch):
    conn = _conn(monkeypatch)
    _write(SqliteSink(conn), "transition", "busy", n=31)  # ≥2×MASS_CHANGE → high
    mass = [f for f in scan_anomalies(conn) if f["kind"] == "mass-change"]
    assert mass and mass[0]["actor"] == "busy" and mass[0]["severity"] == "high"


def test_emit_dedupes_high_findings(monkeypatch):
    conn = _conn(monkeypatch)
    audit = SqliteSink(conn)
    _write(audit, "transition", "busy", n=40)  # high-severity mass-change

    assert emit_anomalies(conn, audit)                        # emits an `anomaly` event
    assert any(e.recipe == "anomaly" for e in query_events(conn))
    assert emit_anomalies(conn, audit) == []                  # same finding → not re-emitted


def test_off_hours_agent_activity(monkeypatch):
    conn = _conn(monkeypatch)
    agent, _ = create_user(conn, "bot@x.dev", "pw", "developer")
    agent.kind = "agent"
    conn.add(agent)
    conn.commit()

    _write(SqliteSink(conn), "invoke", agent.id, n=3)  # OFFHOURS_MIN = 3
    for e in query_events(conn):                       # backdate to 02:00 UTC (off-hours)
        e.created_at = "2026-07-08T02:00:00+00:00"
        conn.add(e)
    conn.commit()

    kinds = {f["kind"] for f in scan_anomalies(conn, "2026-07-08T12:00:00+00:00")}
    assert "off-hours-agent" in kinds
