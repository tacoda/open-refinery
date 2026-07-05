import pytest

from open_refinery import (
    Policy,
    PolicyDenied,
    SqliteSink,
    connect,
    create_policy,
    create_user,
    decide,
    enforce,
    enforcement_mode,
    query_events,
)
from open_refinery.settings import set_setting


def rule(effect, role="*", action="*", resource="*"):
    return Policy(effect=effect, role=role, action=action, resource=resource, owner_id="x")


def test_decide_default_deny_needs_explicit_allow():
    # whitelist mode: no matching rule → denied
    assert decide([], "developer", "invoke", "model", default_allow=False) is False
    # an explicit allow permits it
    ps = [rule("allow", action="invoke", resource="model")]
    assert decide(ps, "developer", "invoke", "model", default_allow=False) is True
    # a deny still blocks even with an allow present
    ps = [rule("allow", action="invoke", resource="model"), rule("deny", action="invoke", resource="model")]
    assert decide(ps, "developer", "invoke", "model", default_allow=False) is False


def test_audit_mode_is_default_allow():
    assert decide([], "developer", "invoke", "model", default_allow=True) is True


def _conn(monkeypatch, mode):
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    conn = connect("sqlite:///:memory:")
    admin, _ = create_user(conn, "a@x.dev", "pw", "admin")
    if mode:
        set_setting(conn, "policy.enforcement", mode, admin.id)
    return conn, admin


def test_enforcement_mode_setting(monkeypatch):
    conn, admin = _conn(monkeypatch, None)
    assert enforcement_mode(conn) == "audit"          # default
    set_setting(conn, "policy.enforcement", "strict", admin.id)
    assert enforcement_mode(conn) == "strict"


def test_strict_mode_blocks_and_audits_refusal(monkeypatch):
    conn, admin = _conn(monkeypatch, "strict")
    audit = SqliteSink(conn)
    # no allow rule → whitelist denies, and the refusal is audited
    with pytest.raises(PolicyDenied):
        enforce(conn, "developer", "invoke", "model", audit=audit, actor_id=admin.id, subject="w1")
    denied = [e for e in query_events(conn) if e.recipe == "denied"]
    assert len(denied) == 1 and denied[0].subject == "w1"

    # add an explicit allow → now permitted (no raise, no new denial)
    create_policy(conn, "allow", admin.id, action="invoke", resource="model")
    enforce(conn, "developer", "invoke", "model", audit=audit, actor_id=admin.id)
    assert len([e for e in query_events(conn) if e.recipe == "denied"]) == 1


def test_audit_mode_allows_unlisted(monkeypatch):
    conn, admin = _conn(monkeypatch, "audit")
    enforce(conn, "developer", "invoke", "model", audit=SqliteSink(conn), actor_id=admin.id)  # no raise


def test_egress_gate_scoped_by_namespace_records_intent(monkeypatch):
    # v2: gate a host-egress action, deny only in one namespace, capture intent
    conn, admin = _conn(monkeypatch, "audit")
    create_policy(conn, "deny", admin.id, action="egress", resource="*", namespace="payments")
    audit = SqliteSink(conn)
    with pytest.raises(PolicyDenied):
        enforce(conn, "developer", "egress", "evil.example.com", audit=audit,
                actor_id=admin.id, namespace="payments", intent="exfiltrate")
    denied = [e for e in query_events(conn) if e.recipe == "denied"]
    assert len(denied) == 1
    # a different namespace is not gated by the payments rule
    enforce(conn, "developer", "egress", "evil.example.com", audit=audit,
            actor_id=admin.id, namespace="research", intent="fetch docs")  # no raise
    assert len([e for e in query_events(conn) if e.recipe == "denied"]) == 1
