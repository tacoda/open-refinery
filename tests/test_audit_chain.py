import pytest

from open_refinery import (
    Record,
    SqliteSink,
    connect,
    events_csv,
    export_chain,
    verify_chain,
)
from open_refinery.models import Event


def sink(monkeypatch=None):
    if monkeypatch:
        monkeypatch.setenv("SECRET_KEY", "test-secret")
    conn = connect("sqlite:///:memory:")
    return conn, SqliteSink(conn)


def _rec(i):
    return Record.of(recipe="transition", actor="a", owner="a",
                     inputs={"n": i}, output=str(i), subject="w1")


def test_chain_links_and_verifies():
    conn, s = sink()
    for i in range(5):
        s.write(_rec(i))
    v = verify_chain(conn)
    assert v["ok"] is True and v["count"] == 5 and v["head"]
    # each event links to the previous
    events = list(conn.exec(__import__("sqlmodel").select(Event)))
    assert all(e.entry_hash for e in events)


def test_editing_an_event_breaks_the_chain():
    conn, s = sink()
    for i in range(3):
        s.write(_rec(i))
    # tamper: change a recorded output digest in place
    e = list(conn.exec(__import__("sqlmodel").select(Event)))[1]
    e.output_digest = "forged"
    conn.add(e); conn.commit()
    v = verify_chain(conn)
    assert v["ok"] is False and "broken_at" in v


def test_deleting_a_middle_event_breaks_the_chain():
    conn, s = sink()
    for i in range(4):
        s.write(_rec(i))
    ev = list(conn.exec(__import__("sqlmodel").select(Event).order_by(Event.created_at)))
    conn.delete(ev[1]); conn.commit()   # remove a middle link
    assert verify_chain(conn)["ok"] is False


def test_signed_export_recomputes_and_signs(monkeypatch):
    conn, s = sink(monkeypatch)
    for i in range(3):
        s.write(_rec(i))
    exp = export_chain(conn)
    assert exp["count"] == 3 and exp["chain_head"] and exp["signature"]
    # signature verifies against the head with the same key
    import hashlib, hmac, os
    expect = hmac.new(os.environ["SECRET_KEY"].encode(), exp["chain_head"].encode(), hashlib.sha256).hexdigest()
    assert exp["signature"] == expect
    # exported rows are in chain order (each prev_hash == previous entry_hash)
    rows = exp["events"]
    for a, b in zip(rows, rows[1:]):
        assert b["prev_hash"] == a["entry_hash"]


def test_events_csv_has_header_rows_and_filters():
    conn, s = sink()
    s.write(Record.of(recipe="transition", actor="a", owner="a", inputs={}, output="x", subject="w1"))
    s.write(Record.of(recipe="invoke", actor="b", owner="b", inputs={}, output="y", subject="w2"))
    csv_all = events_csv(conn)
    lines = [l for l in csv_all.splitlines() if l]
    assert lines[0].startswith("created_at,recipe,actor")
    assert len(lines) == 3  # header + 2 events
    # filter by recipe
    only_invoke = events_csv(conn, recipe="invoke")
    assert len([l for l in only_invoke.splitlines() if l]) == 2 and "invoke" in only_invoke
