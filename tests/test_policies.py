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
    list_policies,
    query_events,
    scan_content,
)


def make_policy(effect, applies_to="*", action="*", resource="*", strict=False,
                kind="rule", layer="charter", namespace=""):
    return Policy(effect=effect, applies_to=applies_to, action=action, resource=resource,
                  strict=strict, kind=kind, layer=layer, namespace=namespace, owner_id="x")


# Permissions an ordinary developer holds, for the `decide` cases below.
DEV = ["approve:code", "propose:code", "run:factory"]


def test_precedence_is_the_layer_axis_alone():
    """It used to be a lattice of (author's role rank, layer), which made a
    rule's weight depend on who wrote it. Role rank is ordering, not authority."""
    ps = [make_policy("allow", strict=True, layer="factory"),
          make_policy("deny", strict=True, layer="charter")]
    assert decide(ps, DEV, "transition", "done") is True    # factory strict allow wins
    ps = [make_policy("deny", strict=True, layer="factory"),
          make_policy("allow", strict=True, layer="harness")]
    assert decide(ps, DEV, "transition", "done") is False   # factory deny beats harness


def test_who_wrote_a_rule_no_longer_changes_its_weight():
    """The same two rules, authored by anybody, decide the same way."""
    dev_factory = Policy(effect="deny", strict=True, kind="rule", layer="factory", owner_id="dev")
    plat_charter = Policy(effect="allow", strict=True, kind="rule", layer="charter", owner_id="plat")
    assert decide([dev_factory, plat_charter], DEV, "t", "d") is False   # factory wins, whoever wrote it


def test_a_rule_applies_to_a_permission_not_a_preset_name():
    """The bug this replaces: edit somebody's permissions away from the preset
    they were created from and the policy engine still judged them by the name."""
    ps = [make_policy("deny", applies_to="run:factory", action="tool")]
    assert decide(ps, ["run:factory"], "tool", "x") is False       # holds it → gated
    assert decide(ps, ["read:audit"], "tool", "x") is True         # does not → not gated
    assert decide(ps, [], "tool", "x") is True


def test_strict_rule_cannot_be_overridden():
    # a non-strict deny would normally win (deny-overrides)...
    ps = [make_policy("allow", strict=True), make_policy("deny")]
    assert decide(ps, DEV, "transition", "done") is True   # strict allow decides alone
    # a strict deny stays denied against a non-strict allow
    ps = [make_policy("deny", strict=True), make_policy("allow")]
    assert decide(ps, DEV, "transition", "done") is False
    # among strict rules, deny still overrides
    ps = [make_policy("allow", strict=True), make_policy("deny", strict=True)]
    assert decide(ps, DEV, "transition", "done") is False


def test_two_strict_rules_at_the_same_layer_deny_override():
    """With the role axis gone, a tie is broken the way a tie should be."""
    ps = [Policy(effect="allow", strict=True, kind="rule", layer="charter", owner_id="a"),
          Policy(effect="deny", strict=True, kind="rule", layer="charter", owner_id="b")]
    assert decide(ps, DEV, "transition", "done") is False


def test_enforce_judges_the_permissions_a_person_holds(monkeypatch):
    """Not the preset they were created from. A person whose permissions were
    edited is judged by what they now hold."""
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    conn = connect("sqlite:///:memory:")
    dev, _ = create_user(conn, "dev@x.dev", "pw", "developer")
    plat, _ = create_user(conn, "plat@x.dev", "pw", "platform")
    create_policy(conn, "deny", plat.id, applies_to="run:factory",
                  action="egress", resource="*")

    from open_refinery.policies import enforce
    with pytest.raises(PolicyDenied):
        enforce(conn, dev, "egress", "api.example.com")     # holds run:factory

    # take the permission away — the preset name on the row does not change
    dev.permissions = [p for p in dev.permissions if p != "run:factory"]
    conn.add(dev); conn.commit()
    assert dev.role == "developer"                          # the label is still there
    enforce(conn, dev, "egress", "api.example.com")         # and no longer decides


def test_non_rule_kinds_do_not_gate():
    # a skill/command/agent policy is a governed artifact, not an allow/deny gate
    ps = [make_policy("deny", kind="skill")]
    assert decide(ps, DEV, "transition", "done") is True


def test_strict_default_is_admin_setting(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    from open_refinery.policies import strict_default
    from open_refinery.settings import set_setting

    conn = connect("sqlite:///:memory:")
    admin, _ = create_user(conn, "a@x.dev", "pw", "admin")
    assert strict_default(conn) is False                       # off unless set
    p1 = create_policy(conn, "deny", admin.id)
    assert p1.strict is False
    set_setting(conn, "policy.strict_default", "true", admin.id)
    assert strict_default(conn) is True
    p2 = create_policy(conn, "deny", admin.id)
    assert p2.strict is True                                   # inherits the admin default


def test_decide_default_allow_and_deny_overrides():
    assert decide([], DEV, "transition", "done") is True
    ps = [make_policy("deny", applies_to="run:factory", action="transition", resource="done")]
    assert decide(ps, DEV, "transition", "done") is False
    assert decide(ps, ["read:audit"], "transition", "done") is True   # does not hold it
    assert decide(ps, DEV, "transition", "review") is True  # resource doesn't match


def test_wildcards_match():
    ps = [make_policy("deny", applies_to="run:factory", action="transition", resource="*")]
    assert decide(ps, DEV, "transition", "anything") is False


def test_namespaced_policy_gates_only_its_namespace():
    ps = [make_policy("deny", action="egress", resource="*", namespace="payments")]
    # gates a request in that namespace, not others, and not an unscoped request
    assert decide(ps, DEV, "egress", "api.stripe.com", namespace="payments") is False
    assert decide(ps, DEV, "egress", "api.stripe.com", namespace="marketing") is True
    assert decide(ps, DEV, "egress", "api.stripe.com") is True
    # a blank-namespace (global) policy gates every namespace
    g = [make_policy("deny", action="egress", resource="*")]
    assert decide(g, "developer", "egress", "x", namespace="payments") is False


def test_per_namespace_whitelist_under_default_deny():
    # strict/default-deny: only an explicit allow in the namespace lets it through
    ps = [make_policy("allow", action="tool", resource="search", namespace="research")]
    assert decide(ps, DEV, "tool", "search", namespace="research", default_allow=False) is True
    assert decide(ps, DEV, "tool", "search", namespace="ops", default_allow=False) is False
    assert decide(ps, DEV, "tool", "delete", namespace="research", default_allow=False) is False


def setup():
    conn = connect("sqlite:///:memory:")
    ian, _ = create_user(conn, "ian@x.dev", "pw", "developer")
    boss, _ = create_user(conn, "boss@x.dev", "pw", "platform")
    return conn, ian, boss


def test_a_policy_gates_whoever_holds_the_permission():
    """`approve:code` is a developer's and not platform's, so it separates them
    — where the old `role` selector separated them by a label that could be
    edited out from under it."""
    conn, ian, boss = setup()
    create_policy(conn, "deny", boss.id, applies_to="approve:code",
                  action="tool", resource="write")
    audit = SqliteSink(conn)
    with pytest.raises(PolicyDenied):
        enforce(conn, ian, "tool", "write", audit=audit)     # developer holds it
    enforce(conn, boss, "tool", "write", audit=audit)        # platform does not


def test_a_refusal_is_audited():
    conn, ian, boss = setup()
    create_policy(conn, "deny", boss.id, applies_to="approve:code",
                  action="tool", resource="write")
    audit = SqliteSink(conn)
    with pytest.raises(PolicyDenied):
        enforce(conn, ian, "tool", "write", audit=audit, subject="run-1")
    denials = [e for e in query_events(conn, subject="run-1") if e.recipe == "denied"]
    assert len(denials) == 1


def test_policies_are_fleet_wide():
    conn, ian, boss = setup()
    create_policy(conn, "deny", boss.id, action="tool", resource="write")
    assert len(list_policies(conn)) == 1
