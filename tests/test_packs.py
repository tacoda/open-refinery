import pytest

from open_refinery import (
    PolicyDenied,
    connect,
    create_user,
    disable_pack,
    enable_pack,
    list_packs,
    list_standards,
)


def setup():
    conn = connect("sqlite:///:memory:")
    dev, _ = create_user(conn, "dev@x.dev", "pw", "developer")
    platform, _ = create_user(conn, "plat@x.dev", "pw", "platform")
    admin, _ = create_user(conn, "admin@x.dev", "pw", "admin")
    return conn, dev, platform, admin


def test_catalog_lists_packs_disabled_by_default():
    conn, *_ = setup()
    packs = {p["key"]: p for p in list_packs(conn)}
    assert "software-general" in packs and packs["software-general"]["enabled"] is False
    assert packs["org-policy"]["role"] == "admin"


def test_enable_seeds_standards_idempotently():
    conn, dev, *_ = setup()
    enable_pack(conn, "software-general", dev)
    stds = list_standards(conn, pack="software-general")
    assert {s.title for s in stds} >= {"Software design", "Testing"}
    enable_pack(conn, "software-general", dev)  # again → no duplicates
    assert len(list_standards(conn, pack="software-general")) == len(stds)
    assert next(p for p in list_packs(conn) if p["key"] == "software-general")["enabled"]


def test_disable_removes_standards():
    conn, dev, *_ = setup()
    enable_pack(conn, "charter", dev)
    assert list_standards(conn, pack="charter")
    disable_pack(conn, "charter", dev)
    assert list_standards(conn, pack="charter") == []
    assert not next(p for p in list_packs(conn) if p["key"] == "charter")["enabled"]


def test_enable_is_role_gated():
    conn, dev, platform, admin = setup()
    with pytest.raises(PolicyDenied):
        enable_pack(conn, "infrastructure", dev)     # platform-layer pack
    enable_pack(conn, "infrastructure", platform)    # platform may
    with pytest.raises(PolicyDenied):
        enable_pack(conn, "org-policy", platform)    # admin-layer pack
    enable_pack(conn, "org-policy", admin)           # admin may


def test_unknown_pack():
    conn, dev, *_ = setup()
    with pytest.raises(ValueError):
        enable_pack(conn, "nope", dev)
