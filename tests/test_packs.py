import pytest

from open_refinery import (
    PolicyDenied,
    connect,
    create_user,
    disable_pack,
    enable_pack,
    list_packs,
    list_standards,
    pack_detail,
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


def test_pack_detail_exposes_contents_and_enabled_state():
    conn, dev, *_ = setup()
    d = pack_detail(conn, "software-general")
    assert d and d["title"] and d["enabled"] is False
    assert len(d["standards"]) > 0 and all({"topic", "title", "body"} <= set(s) for s in d["standards"])
    enable_pack(conn, "software-general", dev)
    assert pack_detail(conn, "software-general")["enabled"] is True
    assert pack_detail(conn, "nope") is None


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


def test_pack_seeds_and_removes_example_processes():
    from open_refinery import list_processes
    conn, dev, *_ = setup()
    enable_pack(conn, "workflows", dev)
    names = {p.name for p in list_processes(conn)}
    assert {"Bug Fix", "Feature", "Spec-driven Delivery"} <= names
    bug = next(p for p in list_processes(conn) if p.name == "Bug Fix")
    assert bug.archetype == "doctrine" and "close" in bug.gates and bug.pack == "workflows"
    disable_pack(conn, "workflows", dev)
    assert not any(p.pack == "workflows" for p in list_processes(conn))


def test_pack_seeds_and_removes_artifacts():
    from open_refinery import list_policies
    conn, dev, *_ = setup()
    enable_pack(conn, "tdd", dev)
    arts = [p for p in list_policies(conn) if p.pack == "tdd"]
    assert len(arts) == 1 and arts[0].kind == "command" and arts[0].namespace == "canon/tdd"
    assert "red" in arts[0].content
    disable_pack(conn, "tdd", dev)
    assert not any(p.pack == "tdd" for p in list_policies(conn))
