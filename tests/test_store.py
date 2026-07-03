import pytest

from open_refinery import Factory, SqliteSink, connect, query_events


def make(conn):
    f = Factory(audit=SqliteSink(conn))
    f.register("upper", lambda text: text.upper())
    return f


def test_events_persist_and_query():
    conn = connect("sqlite:///:memory:")
    f = make(conn)
    f.produce("upper", actor="ian", text="a")
    f.produce("upper", actor="mallory", text="b")

    all_events = query_events(conn)
    assert len(all_events) == 2
    assert {e.actor for e in all_events} == {"ian", "mallory"}
    assert all(e.artifact_id and e.output_digest for e in all_events)


def test_query_filters_by_actor():
    conn = connect("sqlite:///:memory:")
    f = make(conn)
    f.produce("upper", actor="ian", text="a")
    f.produce("upper", actor="mallory", text="b")

    ian = query_events(conn, actor="ian")
    assert len(ian) == 1
    assert ian[0].actor == "ian"


def test_query_respects_limit():
    conn = connect("sqlite:///:memory:")
    f = make(conn)
    for i in range(5):
        f.produce("upper", actor="ian", text=str(i))
    assert len(query_events(conn, limit=3)) == 3


def test_unsupported_database_url():
    with pytest.raises(ValueError):
        connect("postgres://localhost/db")
