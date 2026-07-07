import pytest

from open_refinery import (
    FRAMEWORKS,
    SqliteSink,
    Record,
    connect,
    create_policy,
    create_user,
    evidence_pack,
    list_auditors,
    mint_auditor,
    resolve_auditor,
    revoke_auditor,
)


def setup(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    conn = connect("sqlite:///:memory:")
    admin, _ = create_user(conn, "a@x.dev", "pw", "admin")
    return conn, admin


def test_evidence_pack_maps_controls_with_status(monkeypatch):
    conn, admin = setup(monkeypatch)
    create_policy(conn, "deny", admin.id, role="developer", action="egress", resource="*")
    SqliteSink(conn).write(Record.of(recipe="transition", actor="a", owner="a", inputs={}, output="x"))
    pack = evidence_pack(conn, "soc2")
    assert pack["framework"] == "soc2"
    ids = {c["id"] for c in pack["controls"]}
    assert {"access-control", "audit-logging", "change-management"} <= ids
    ac = next(c for c in pack["controls"] if c["id"] == "access-control")
    assert ac["status"] == "met" and ac["evidence"]["rules"] == 1
    al = next(c for c in pack["controls"] if c["id"] == "audit-logging")
    assert al["evidence"]["chain_intact"] is True  # ties to the tamper-evident chain
    assert pack["summary"]["coverage_pct"] >= 0


def test_all_frameworks_produce_a_pack(monkeypatch):
    conn, _ = setup(monkeypatch)
    for f in FRAMEWORKS:
        assert evidence_pack(conn, f)["framework"] == f
    with pytest.raises(ValueError):
        evidence_pack(conn, "nope")


def test_auditor_grant_resolves_until_expiry_then_revoke(monkeypatch):
    conn, admin = setup(monkeypatch)
    grant, token = mint_auditor(conn, "Ernst & Young", admin.id, ttl_days=7)
    assert resolve_auditor(conn, token).id == grant.id
    assert resolve_auditor(conn, "wrong-token") is None
    assert [a.id for a in list_auditors(conn)] == [grant.id]
    revoke_auditor(conn, grant.id)
    assert resolve_auditor(conn, token) is None


def test_expired_grant_does_not_resolve(monkeypatch):
    conn, admin = setup(monkeypatch)
    grant, token = mint_auditor(conn, "past", admin.id, ttl_days=-1)  # already expired
    assert resolve_auditor(conn, token) is None
