import pytest

from open_refinery import SqliteSink, connect, query_events
from open_refinery.provenance import Record


def write(conn, actor, text):
    """One audited production. The `Factory` recipe registry this used to go
    through was the 0.1.0 demo core, removed in 2.15.0 — the sink is what the
    product actually writes through."""
    SqliteSink(conn).write(Record.of(recipe="upper", actor=actor, owner=actor,
                                     inputs={"text": text}, output=text.upper()))


def test_events_persist_and_query():
    conn = connect("sqlite:///:memory:")
    write(conn, "ian", "a")
    write(conn, "mallory", "b")

    all_events = query_events(conn)
    assert len(all_events) == 2
    assert {e.actor for e in all_events} == {"ian", "mallory"}
    assert all(e.artifact_id and e.output_digest for e in all_events)


def test_query_filters_by_actor():
    conn = connect("sqlite:///:memory:")
    write(conn, "ian", "a")
    write(conn, "mallory", "b")

    ian = query_events(conn, actor="ian")
    assert len(ian) == 1
    assert ian[0].actor == "ian"


def test_query_respects_limit():
    conn = connect("sqlite:///:memory:")
    for i in range(5):
        write(conn, "ian", str(i))
    assert len(query_events(conn, limit=3)) == 3


def test_unsupported_database_url():
    with pytest.raises(ValueError):
        connect("postgres://localhost/db")
