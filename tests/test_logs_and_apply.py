import pytest

from open_refinery import (
    SqliteSink,
    append_log,
    connect,
    create_process,
    create_repository,
    create_user,
    create_work_item,
    query_events,
    recent_logs,
    record_rollback_applied,
    stage_history,
    transition,
)


def setup(monkeypatch=None):
    if monkeypatch:
        monkeypatch.setenv("SECRET_KEY", "test-secret")
    conn = connect("sqlite:///:memory:")
    dev, _ = create_user(conn, "dev@x.dev", "pw", "developer")
    repo = create_repository(conn, "app", "git@x:app.git", dev.id)
    proc = create_process(conn, "flow", "board", ["a", "b"], dev.id)
    item = create_work_item(conn, repo.id, proc.id, "T", dev.id)
    return conn, dev, item


def test_logs_buffer_keeps_recent_lines_per_item():
    conn, dev, item = setup()
    append_log(item.id, "starting run")
    append_log(item.id, "oops", level="error")
    append_log("other-item", "unrelated")
    lines = recent_logs(item.id)
    assert [l["line"] for l in lines] == ["starting run", "oops"]
    assert lines[1]["level"] == "error"
    assert recent_logs("other-item")[0]["line"] == "unrelated"  # buffered per item


def test_log_level_defaults_to_info_on_unknown():
    conn, dev, item = setup()
    entry = append_log(item.id, "hi", level="bogus")
    assert entry["level"] == "info"


def test_rollback_applied_records_outcome_in_history_and_audit():
    conn, dev, item = setup()
    audit = SqliteSink(conn)
    transition(conn, item.id, "b", dev.id, audit)
    record_rollback_applied(conn, item.id, dev.id, "applied", audit, detail="reverted 2 migrations")
    hist = stage_history(conn, item.id)
    assert hist[-1].kind == "rollback-applied" and hist[-1].changes["status"] == "applied"
    applied = [e for e in query_events(conn, subject=item.id) if e.recipe == "rollback-applied"]
    assert len(applied) == 1


def test_rollback_applied_rejects_bad_status():
    conn, dev, item = setup()
    with pytest.raises(ValueError):
        record_rollback_applied(conn, item.id, dev.id, "maybe", SqliteSink(conn))
