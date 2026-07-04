import pytest
from datetime import datetime, timedelta, timezone

from open_refinery import (
    add_sample,
    analyze_experiment,
    connect,
    create_experiment,
    create_process,
    create_route,
    create_target,
    create_user,
    execute,
    purge_events,
    query_events,
    SqliteSink,
)
from open_refinery.models import Event


def test_purge_events_by_retention():
    conn = connect("sqlite:///:memory:")
    old = Event(artifact_id="a1", recipe="transition", actor="x", owner="x",
                input_digest="d", output_digest="d",
                created_at=(datetime.now(timezone.utc) - timedelta(days=40)).isoformat())
    new = Event(artifact_id="a2", recipe="transition", actor="x", owner="x",
                input_digest="d", output_digest="d")
    conn.add(old); conn.add(new); conn.commit()
    assert purge_events(conn, 30) == 1                 # only the 40-day-old one
    ids = {e.artifact_id for e in query_events(conn)}
    assert ids == {"a2"}


def test_add_sample_accumulates():
    conn = connect("sqlite:///:memory:")
    dev, _ = create_user(conn, "d@x.dev", "pw", "developer")
    exp = create_experiment(conn, "e", "h", "c", "harness", dev.id)
    add_sample(conn, exp.id, "before", "units", 10)
    run = add_sample(conn, exp.id, "before", "units", 20)
    assert run.n == 2 and run.mean == 15.0           # appended to the same run


def test_experiment_tagged_execute_feeds_eval(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    conn = connect("sqlite:///:memory:")
    dev, _ = create_user(conn, "d@x.dev", "pw", "developer")
    proc = create_process(conn, "p", "board", ["a", "b"], dev.id)
    t = create_target(conn, "m", "model", "claude-opus-4-8", dev.id)  # no cred → stub, units=1
    create_route(conn, proc.id, t.id, dev.id)
    exp = create_experiment(conn, "e", "h", "c", "harness", dev.id)

    execute(conn, dev.id, proc.id, "hi", SqliteSink(conn), experiment_id=exp.id, arm="control")
    execute(conn, dev.id, proc.id, "hi", SqliteSink(conn), experiment_id=exp.id, arm="treatment")
    res = analyze_experiment(conn, exp.id, metric="units")
    assert res["before"] == 1.0 and res["after"] == 1.0  # both stub units=1 → fed control+treatment
