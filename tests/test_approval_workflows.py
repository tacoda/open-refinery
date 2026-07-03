import pytest

from open_refinery import (
    PolicyDenied,
    SqliteSink,
    connect,
    create_user,
    list_policies,
    list_proposals,
    propose,
    resubmit,
    review,
    set_workflow,
)


def setup(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    conn = connect("sqlite:///:memory:")
    dev, _ = create_user(conn, "dev@x.dev", "pw", "developer")
    plat, _ = create_user(conn, "plat@x.dev", "pw", "platform")
    admin, _ = create_user(conn, "admin@x.dev", "pw", "admin")
    return conn, dev, plat, admin


POLICY = {"effect": "deny", "action": "invoke", "resource": "*", "strict": True}


def test_full_accept_applies_the_change(monkeypatch):
    conn, dev, plat, admin = setup(monkeypatch)
    audit = SqliteSink(conn)
    set_workflow(conn, "developer", ["platform", "admin"], admin.id)
    prop = propose(conn, "policy", "create", POLICY, "developer", dev.id)
    assert prop.chain == ["platform", "admin"] and prop.status == "pending"

    # developer can't sign the platform slot
    with pytest.raises(PolicyDenied):
        review(conn, prop.id, dev.id, "accept", audit)

    r1 = review(conn, prop.id, plat.id, "accept", audit)   # slot 0
    assert r1.status == "pending" and r1.current == 1
    assert len(list_policies(conn)) == 0                   # not applied yet

    r2 = review(conn, prop.id, admin.id, "accept", audit)  # slot 1 → apply
    assert r2.status == "accepted" and r2.applied_ref
    pols = list_policies(conn)
    assert len(pols) == 1 and pols[0].strict and pols[0].owner_id == dev.id  # authored at proposer layer


def test_deny_stops(monkeypatch):
    conn, dev, plat, admin = setup(monkeypatch)
    audit = SqliteSink(conn)
    set_workflow(conn, "developer", ["platform"], admin.id)
    prop = propose(conn, "policy", "create", POLICY, "developer", dev.id)
    r = review(conn, prop.id, plat.id, "deny", audit, note="no")
    assert r.status == "denied"
    assert list_policies(conn) == []
    with pytest.raises(ValueError):
        review(conn, prop.id, admin.id, "accept", audit)   # closed


def test_feedback_then_resubmit(monkeypatch):
    conn, dev, plat, admin = setup(monkeypatch)
    audit = SqliteSink(conn)
    set_workflow(conn, "developer", ["platform"], admin.id)
    prop = propose(conn, "policy", "create", POLICY, "developer", dev.id)
    review(conn, prop.id, plat.id, "feedback", audit, note="tighten resource")
    assert prop.status == "revising"

    with pytest.raises(PolicyDenied):
        resubmit(conn, prop.id, plat.id)                   # only proposer resubmits
    again = resubmit(conn, prop.id, dev.id, payload={**POLICY, "resource": "model"})
    assert again.status == "pending" and again.current == 0 and again.decisions == []

    review(conn, again.id, plat.id, "accept", audit)       # re-review, applies
    assert list_policies(conn)[0].resource == "model"


def test_default_chain_when_unconfigured(monkeypatch):
    conn, dev, plat, admin = setup(monkeypatch)
    prop = propose(conn, "policy", "create", POLICY, "platform", dev.id)
    assert prop.chain == ["platform"]                      # defaults to [layer]


def test_distinct_signer_per_slot(monkeypatch):
    conn, dev, plat, admin = setup(monkeypatch)
    audit = SqliteSink(conn)
    set_workflow(conn, "developer", ["platform", "platform"], admin.id)
    prop = propose(conn, "policy", "create", POLICY, "developer", dev.id)
    review(conn, prop.id, plat.id, "accept", audit)
    with pytest.raises(PolicyDenied):
        review(conn, prop.id, plat.id, "accept", audit)    # same signer twice
