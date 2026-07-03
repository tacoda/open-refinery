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
    get_work_item,
    list_approvals,
    query_events,
    reject,
    request_approval,
)


def fixture(oversight="assisted", **process_kw):
    conn = connect("sqlite:///:memory:")
    dev, _ = create_user(conn, "dev@x.dev", "pw", "developer")
    senior, _ = create_user(conn, "senior@x.dev", "pw", "senior")
    platform, _ = create_user(conn, "plat@x.dev", "pw", "platform")
    repo = create_repository(conn, "or", "git@x:or.git", dev.id)
    proc = create_process(conn, "flow", "board", ["todo", "done"], dev.id,
                          oversight=oversight, **process_kw)
    item = create_work_item(conn, repo.id, proc.id, "T", dev.id)
    return conn, dev, senior, platform, item


def test_single_slot_chain_defaults_to_min_approver():
    conn, dev, senior, platform, item = fixture()  # default chain = [min_approver_role=senior]
    audit = SqliteSink(conn)
    req = request_approval(conn, item.id, "done", dev.id, audit)
    assert req.status == "pending" and req.required_roles == ["senior"]
    assert len(list_approvals(conn, status="pending")) == 1

    done = approve(conn, req.id, senior.id, audit)
    assert done.status == "applied"
    assert get_work_item(conn, item.id).current_stage == "done"  # move applied


def test_chained_senior_then_platform():
    conn, dev, senior, platform, item = fixture(approval_chain=["senior", "platform"])
    audit = SqliteSink(conn)
    req = request_approval(conn, item.id, "done", dev.id, audit)

    # developer can't sign the senior slot
    with pytest.raises(PolicyDenied):
        approve(conn, req.id, dev.id, audit)

    r1 = approve(conn, req.id, senior.id, audit)   # slot 0: senior
    assert r1.status == "pending" and len(r1.approvals) == 1
    assert get_work_item(conn, item.id).current_stage == "todo"  # not applied yet

    r2 = approve(conn, req.id, platform.id, audit)  # slot 1: platform
    assert r2.status == "applied"
    assert get_work_item(conn, item.id).current_stage == "done"


def test_same_user_cannot_sign_twice():
    conn, dev, senior, platform, item = fixture(approval_chain=["senior", "senior"])
    audit = SqliteSink(conn)
    req = request_approval(conn, item.id, "done", dev.id, audit)
    approve(conn, req.id, senior.id, audit)          # slot 0
    with pytest.raises(PolicyDenied):
        approve(conn, req.id, senior.id, audit)      # same user, slot 1 → rejected


def test_reject_stops_the_request():
    conn, dev, senior, platform, item = fixture()
    audit = SqliteSink(conn)
    req = request_approval(conn, item.id, "done", dev.id, audit)
    rej = reject(conn, req.id, senior.id, audit)
    assert rej.status == "rejected"
    with pytest.raises(ValueError):
        approve(conn, req.id, senior.id, audit)      # can't approve a rejected request
    assert any(e.recipe == "approval-rejected" for e in query_events(conn))


def test_request_needs_a_gated_move():
    conn, dev, senior, platform, item = fixture(oversight="dark")  # nothing needs approval
    with pytest.raises(ValueError):
        request_approval(conn, item.id, "done", dev.id, SqliteSink(conn))
