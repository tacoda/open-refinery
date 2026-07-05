import pytest

from open_refinery import (
    SqliteSink,
    connect,
    create_process,
    create_repository,
    create_user,
    create_work_item,
    postmortem,
    transition,
)
from open_refinery.provenance import Record


def setup():
    conn = connect("sqlite:///:memory:")
    dev, _ = create_user(conn, "dev@x.dev", "pw", "developer")
    repo = create_repository(conn, "app", "git@github.com:acme/app.git", dev.id)
    proc = create_process(conn, "flow", "board", ["a", "b"], dev.id)
    item = create_work_item(conn, repo.id, proc.id, "T", dev.id)
    return conn, dev, item


def test_clean_run_has_no_root_cause():
    conn, dev, item = setup()
    audit = SqliteSink(conn)
    transition(conn, item.id, "b", dev.id, audit)
    pm = postmortem(conn, item.id)
    assert pm["findings"] == []
    assert "cleanly" in pm["root_cause"]
    assert any(t["recipe"] == "transition" for t in pm["timeline"])


def test_denial_is_root_cause_and_suggests_policy_review():
    conn, dev, item = setup()
    audit = SqliteSink(conn)
    # simulate a recorded refusal on this run
    audit.write(Record.of(recipe="denied", actor=dev.id, owner=dev.id,
                          inputs={"action": "invoke"}, output="policy denies", subject=item.id))
    pm = postmortem(conn, item.id)
    assert pm["findings"][0]["type"] == "policy_denial"
    assert "policy" in pm["root_cause"].lower()
    assert any("rule" in s.lower() or "policy" in s.lower() for s in pm["suggestions"])


def test_target_failure_detected():
    conn, dev, item = setup()
    audit = SqliteSink(conn)
    audit.write(Record.of(recipe="invoke-failed", actor=dev.id, owner=dev.id,
                          inputs={"target": "t"}, output="boom", subject=item.id))
    pm = postmortem(conn, item.id)
    assert any(f["type"] == "target_failure" for f in pm["findings"])
    assert pm["counts"].get("invoke-failed") == 1


def test_unknown_item():
    conn, dev, item = setup()
    with pytest.raises(ValueError):
        postmortem(conn, "nope")
