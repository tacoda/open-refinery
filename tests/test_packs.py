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
    lead, _ = create_user(conn, "lead@x.dev", "pw", "lead")        # holds approve:charter
    admin, _ = create_user(conn, "admin@x.dev", "pw", "admin")
    return conn, dev, lead, admin


def test_catalog_lists_packs_disabled_by_default():
    conn, *_ = setup()
    packs = {p["key"]: p for p in list_packs(conn)}
    assert "software-general" in packs and packs["software-general"]["enabled"] is False
    assert packs["org-policy"]["role"] == "admin"


def test_pack_detail_exposes_contents_and_enabled_state():
    conn, _dev, lead, _admin = setup()
    d = pack_detail(conn, "software-general")
    assert d and d["title"] and d["enabled"] is False
    assert len(d["standards"]) > 0 and all({"topic", "title", "body"} <= set(s) for s in d["standards"])
    enable_pack(conn, "software-general", lead)
    assert pack_detail(conn, "software-general")["enabled"] is True
    assert pack_detail(conn, "nope") is None


def test_enable_seeds_standards_idempotently():
    conn, _dev, lead, _admin = setup()
    enable_pack(conn, "software-general", lead)
    stds = list_standards(conn, pack="software-general")
    assert {s.title for s in stds} >= {"Software design", "Testing"}
    enable_pack(conn, "software-general", lead)  # again → no duplicates
    assert len(list_standards(conn, pack="software-general")) == len(stds)
    assert next(p for p in list_packs(conn) if p["key"] == "software-general")["enabled"]


def test_disable_removes_standards():
    conn, _dev, lead, _admin = setup()
    enable_pack(conn, "charter", lead)
    assert list_standards(conn, pack="charter")
    disable_pack(conn, "charter", lead)
    assert list_standards(conn, pack="charter") == []
    assert not next(p for p in list_packs(conn) if p["key"] == "charter")["enabled"]


def test_enabling_a_pack_needs_approve_charter():
    """A pack seeds standards and governed artifacts, so turning one on is a
    charter change — and the standards are the lead's. It was a role-rank
    comparison, which tiered packs by an ordering the rest of the product had
    stopped treating as authority."""
    conn, dev, lead, admin = setup()
    for who in (dev, admin):                        # neither holds approve:charter
        with pytest.raises(PolicyDenied, match="approve:charter"):
            enable_pack(conn, "infrastructure", who)
    enable_pack(conn, "infrastructure", lead)
    enable_pack(conn, "org-policy", lead)


def test_unknown_pack():
    conn, _dev, lead, _admin = setup()
    with pytest.raises(ValueError):
        enable_pack(conn, "nope", lead)


def test_pack_seeds_and_removes_artifacts():
    from open_refinery import list_policies
    conn, _dev, lead, _admin = setup()
    enable_pack(conn, "tdd", lead)
    arts = [p for p in list_policies(conn) if p.pack == "tdd"]
    assert len(arts) == 1 and arts[0].kind == "command" and arts[0].namespace == "canon/tdd"
    assert "red" in arts[0].content
    disable_pack(conn, "tdd", lead)
    assert not any(p.pack == "tdd" for p in list_policies(conn))
