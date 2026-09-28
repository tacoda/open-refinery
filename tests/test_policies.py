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


def make_policy(effect, role="*", action="*", resource="*", strict=False, kind="rule",
                layer="charter", namespace=""):
    return Policy(effect=effect, role=role, action=action, resource=resource,
                  strict=strict, kind=kind, layer=layer, namespace=namespace, owner_id="x")


def test_layer_axis_breaks_ties_when_ranks_equal():
    # same author rank (flat 0), different artifact layer → factory beats charter
    ps = [make_policy("allow", strict=True, layer="factory"),
          make_policy("deny", strict=True, layer="charter")]
    assert decide(ps, "developer", "transition", "done") is True   # factory strict allow wins
    ps = [make_policy("deny", strict=True, layer="factory"),
          make_policy("allow", strict=True, layer="harness")]
    assert decide(ps, "developer", "transition", "done") is False  # factory deny wins over harness


def test_role_rank_dominates_layer():
    rank = {"plat": 2, "dev": 1}
    rank_of = lambda p: rank.get(p.owner_id, 0)
    # developer at factory layer vs platform at charter layer → role rank dominates
    dev_factory = Policy(effect="deny", strict=True, kind="rule", layer="factory", owner_id="dev")
    plat_charter = Policy(effect="allow", strict=True, kind="rule", layer="charter", owner_id="plat")
    assert decide([dev_factory, plat_charter], "developer", "t", "d", rank_of=rank_of) is True


def test_strict_rule_cannot_be_overridden():
    # a non-strict deny would normally win (deny-overrides)...
    ps = [make_policy("allow", strict=True), make_policy("deny")]
    assert decide(ps, "developer", "transition", "done") is True   # strict allow decides alone
    # a strict deny stays denied against a non-strict allow
    ps = [make_policy("deny", strict=True), make_policy("allow")]
    assert decide(ps, "developer", "transition", "done") is False
    # among strict rules, deny still overrides
    ps = [make_policy("allow", strict=True), make_policy("deny", strict=True)]
    assert decide(ps, "developer", "transition", "done") is False


def test_layer_graph_higher_author_strict_wins():
    # rank by author: platform(2) outranks developer(1)
    rank = {"plat": 2, "dev": 1}
    rank_of = lambda p: rank.get(p.owner_id, 0)
    plat_allow = Policy(effect="allow", strict=True, kind="rule", owner_id="plat")
    dev_deny = Policy(effect="deny", strict=True, kind="rule", owner_id="dev")
    ps = [plat_allow, dev_deny]
    # higher layer's strict allow locks; developer's strict deny cannot override
    assert decide(ps, "developer", "transition", "done", rank_of=rank_of) is True
    # flip: developer strict allow can't override platform strict deny
    ps = [Policy(effect="deny", strict=True, kind="rule", owner_id="plat"),
          Policy(effect="allow", strict=True, kind="rule", owner_id="dev")]
    assert decide(ps, "developer", "transition", "done", rank_of=rank_of) is False


def test_enforce_resolves_author_layers(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    conn = connect("sqlite:///:memory:")
    dev, _ = create_user(conn, "dev@x.dev", "pw", "developer")
    plat, _ = create_user(conn, "plat@x.dev", "pw", "platform")
    # developer strict-denies; platform strict-allows the same action → platform wins
    create_policy(conn, "deny", dev.id, action="transition", resource="done", strict=True)
    create_policy(conn, "allow", plat.id, action="transition", resource="done", strict=True)
    from open_refinery.policies import enforce
    enforce(conn, "developer", "transition", "done")  # no raise: higher layer allows


def test_non_rule_kinds_do_not_gate():
    # a skill/command/agent policy is a governed artifact, not an allow/deny gate
    ps = [make_policy("deny", kind="skill")]
    assert decide(ps, "developer", "transition", "done") is True


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
    assert decide([], "developer", "transition", "done") is True
    ps = [make_policy("deny", role="developer", action="transition", resource="done")]
    assert decide(ps, "developer", "transition", "done") is False
    assert decide(ps, "platform", "transition", "done") is True   # role doesn't match
    assert decide(ps, "developer", "transition", "review") is True  # resource doesn't match


def test_wildcards_match():
    ps = [make_policy("deny", role="developer", action="transition", resource="*")]
    assert decide(ps, "developer", "transition", "anything") is False


def test_namespaced_policy_gates_only_its_namespace():
    ps = [make_policy("deny", action="egress", resource="*", namespace="payments")]
    # gates a request in that namespace, not others, and not an unscoped request
    assert decide(ps, "developer", "egress", "api.stripe.com", namespace="payments") is False
    assert decide(ps, "developer", "egress", "api.stripe.com", namespace="marketing") is True
    assert decide(ps, "developer", "egress", "api.stripe.com") is True
    # a blank-namespace (global) policy gates every namespace
    g = [make_policy("deny", action="egress", resource="*")]
    assert decide(g, "developer", "egress", "x", namespace="payments") is False


def test_per_namespace_whitelist_under_default_deny():
    # strict/default-deny: only an explicit allow in the namespace lets it through
    ps = [make_policy("allow", action="tool", resource="search", namespace="research")]
    assert decide(ps, "developer", "tool", "search", namespace="research", default_allow=False) is True
    assert decide(ps, "developer", "tool", "search", namespace="ops", default_allow=False) is False
    assert decide(ps, "developer", "tool", "delete", namespace="research", default_allow=False) is False


def setup():
    conn = connect("sqlite:///:memory:")
    ian, _ = create_user(conn, "ian@x.dev", "pw", "developer")
    boss, _ = create_user(conn, "boss@x.dev", "pw", "platform")
    return conn, ian, boss


def test_policy_blocks_an_action_by_role():
    """`enforce` is what the harness middleware and `POST /authorize` both call.
    It gated kanban transitions too, until those went in 3.0."""
    conn, ian, boss = setup()
    create_policy(conn, "deny", boss.id, role="developer", action="tool", resource="write")
    audit = SqliteSink(conn)
    with pytest.raises(PolicyDenied):
        enforce(conn, ian.role, "tool", "write", audit=audit, actor_id=ian.id)
    enforce(conn, boss.role, "tool", "write", audit=audit, actor_id=boss.id)  # not denied


def test_a_refusal_is_audited():
    conn, ian, boss = setup()
    create_policy(conn, "deny", boss.id, role="developer", action="tool", resource="write")
    audit = SqliteSink(conn)
    with pytest.raises(PolicyDenied):
        enforce(conn, ian.role, "tool", "write", audit=audit, actor_id=ian.id, subject="run-1")
    denials = [e for e in query_events(conn, subject="run-1") if e.recipe == "denied"]
    assert len(denials) == 1


def test_policies_are_fleet_wide():
    conn, ian, boss = setup()
    create_policy(conn, "deny", boss.id, action="tool", resource="write")
    assert len(list_policies(conn)) == 1
