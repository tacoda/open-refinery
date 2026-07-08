from datetime import datetime, timedelta

import pytest

from open_refinery import (
    PolicyDenied,
    SqliteSink,
    approve,
    connect,
    create_process,
    create_repository,
    create_user,
    create_work_item,
    escalate_overdue,
    overdue_approvals,
    query_events,
    request_approval,
)
from open_refinery.models import now_iso


def fixture(**process_kw):
    conn = connect("sqlite:///:memory:")
    dev, _ = create_user(conn, "dev@x.dev", "pw", "developer")
    dev2, _ = create_user(conn, "dev2@x.dev", "pw", "developer")
    platform, _ = create_user(conn, "plat@x.dev", "pw", "platform")
    repo = create_repository(conn, "or", "git@x:or.git", dev.id)
    proc = create_process(conn, "flow", "board", ["todo", "done"], dev.id,
                          oversight="assisted", **process_kw)
    item = create_work_item(conn, repo.id, proc.id, "T", dev.id)
    return conn, dev, dev2, platform, item


def test_requester_cannot_approve_own_request():
    # segregation of duties: even a role-eligible requester may not self-approve
    conn, dev, dev2, platform, item = fixture(approval_chain=["developer"])
    audit = SqliteSink(conn)
    req = request_approval(conn, item.id, "done", dev.id, audit)
    with pytest.raises(PolicyDenied, match="segregation of duties"):
        approve(conn, req.id, dev.id, audit)
    # a different eligible person can sign
    assert approve(conn, req.id, dev2.id, audit).status == "applied"


def test_sla_sets_due_at_and_no_sla_leaves_it_blank():
    conn, dev, dev2, platform, item = fixture(approval_sla_hours=24)
    req = request_approval(conn, item.id, "done", dev.id, SqliteSink(conn))
    assert req.due_at and datetime.fromisoformat(req.due_at) > datetime.fromisoformat(now_iso())

    conn2, dev, dev2, platform, item2 = fixture()  # no SLA
    req2 = request_approval(conn2, item2.id, "done", dev.id, SqliteSink(conn2))
    assert req2.due_at == ""


def test_overdue_sweep_emits_once_and_dedups():
    conn, dev, dev2, platform, item = fixture(approval_sla_hours=1)
    audit = SqliteSink(conn)
    req = request_approval(conn, item.id, "done", dev.id, audit)
    later = (datetime.fromisoformat(now_iso()) + timedelta(hours=2)).isoformat()

    assert [r.id for r in overdue_approvals(conn, later)] == [req.id]
    assert escalate_overdue(conn, audit, later) == [req.id]
    assert any(e.recipe == "approval-overdue" for e in query_events(conn))
    # already escalated → no second event
    assert overdue_approvals(conn, later) == []
    assert escalate_overdue(conn, audit, later) == []


def test_not_overdue_before_deadline():
    conn, dev, dev2, platform, item = fixture(approval_sla_hours=48)
    request_approval(conn, item.id, "done", dev.id, SqliteSink(conn))
    assert overdue_approvals(conn, now_iso()) == []
