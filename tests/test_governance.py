from open_refinery import (
    connect,
    create_policy,
    create_user,
    landscape,
)


def setup():
    conn = connect("sqlite:///:memory:")
    dev, _ = create_user(conn, "dev@x.dev", "pw", "developer")
    plat, _ = create_user(conn, "plat@x.dev", "pw", "platform")
    return conn, dev, plat


def test_landscape_reports_roles_and_layers():
    conn, dev, plat = setup()
    create_policy(conn, "allow", plat.id, action="invoke", resource="*", strict=True)
    create_policy(conn, "deny", dev.id, action="transition", resource="done")
    land = landscape(conn)

    roles = {r["name"]: r for r in land["roles"]}
    assert roles["developer"]["users"] == 1 and roles["platform"]["rank"] == 2
    ranks = [layer["rank"] for layer in land["layers"]]
    assert ranks == sorted(ranks, reverse=True)  # highest layer first


def test_landscape_reports_overrides():
    conn, dev, plat = setup()
    # platform strict-allows what developer denies on the same action/resource
    create_policy(conn, "allow", plat.id, action="transition", resource="done", strict=True)
    create_policy(conn, "deny", dev.id, action="transition", resource="done")
    land = landscape(conn)

    assert len(land["overrides"]) == 1
    ov = land["overrides"][0]
    assert ov["winner"]["author_role"] == "platform" and ov["winner"]["strict"]
    assert ov["shadowed"]["author_role"] == "developer"
