import pytest

from open_refinery import (
    Record,
    SqliteSink,
    connect,
    create_rule,
    create_user,
    delete_rule,
    list_rules,
)
from open_refinery import notifications


def setup(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    conn = connect("sqlite:///:memory:")
    admin, _ = create_user(conn, "a@x.dev", "pw", "admin")
    return conn, admin


def test_rule_crud_and_channel_validation(monkeypatch):
    conn, admin = setup(monkeypatch)
    r = create_rule(conn, "deny alerts", "slack", "https://hooks.slack/x",
                    recipe="denied", created_by=admin.id)
    assert r in list_rules(conn) and r.channel == "slack"
    with pytest.raises(ValueError):
        create_rule(conn, "bad", "carrier-pigeon", "x")
    delete_rule(conn, r.id)
    assert not list_rules(conn)


def test_dispatch_fires_only_matching_rules(monkeypatch):
    conn, admin = setup(monkeypatch)
    sent = []
    monkeypatch.setattr(notifications, "send", lambda rule, text, payload: sent.append((rule.recipe, text)))
    create_rule(conn, "denials", "slack", "u", recipe="denied", created_by=admin.id)
    create_rule(conn, "all", "webhook", "u", recipe="", created_by=admin.id)

    audit = SqliteSink(conn)  # writing an event triggers dispatch
    audit.write(Record.of(recipe="denied", actor="a", owner="a", inputs={}, output="no", subject="w1"))
    audit.write(Record.of(recipe="transition", actor="a", owner="a", inputs={}, output="done", subject="w1"))
    # "denied" event → both rules; "transition" → only the catch-all
    fired = [r for r, _ in sent]
    assert fired.count("denied") == 1 and fired.count("") == 2


def test_broken_channel_never_blocks_the_write(monkeypatch):
    conn, admin = setup(monkeypatch)
    def boom(*a, **k):
        raise RuntimeError("channel down")
    monkeypatch.setattr(notifications, "send", boom)
    create_rule(conn, "any", "slack", "u", created_by=admin.id)
    # the audit write must still succeed despite the failing channel
    SqliteSink(conn).write(Record.of(recipe="denied", actor="a", owner="a", inputs={}, output="x"))
    from open_refinery import query_events
    assert len(query_events(conn)) == 1
