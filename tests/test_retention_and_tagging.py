from datetime import datetime, timedelta, timezone

from open_refinery import (
    add_sample,
    connect,
    create_experiment,
    create_user,
    purge_events,
    query_events,
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
