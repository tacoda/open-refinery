from open_refinery import (
    connect,
    create_policy,
    create_user,
    delete_policy,
    list_policy_versions,
    policies_in_effect_at,
)
from open_refinery.models import now_iso


def setup():
    conn = connect("sqlite:///:memory:")
    admin, _ = create_user(conn, "a@x.dev", "pw", "admin")
    return conn, admin


def test_create_and_delete_are_versioned_with_who_and_why():
    conn, admin = setup()
    p = create_policy(conn, "deny", admin.id, role="developer", action="egress",
                      resource="*", note="lock down egress")
    vs = list_policy_versions(conn, policy_id=p.id)
    assert len(vs) == 1 and vs[0].change == "created"
    assert vs[0].changed_by == admin.id and vs[0].note == "lock down egress"
    assert vs[0].effect == "deny" and vs[0].action == "egress"

    delete_policy(conn, p.id, changed_by=admin.id, note="no longer needed")
    vs = list_policy_versions(conn, policy_id=p.id)
    assert [v.change for v in vs] == ["deleted", "created"]  # newest first
    assert vs[0].note == "no longer needed"


def test_point_in_time_reconstruction():
    conn, admin = setup()
    p = create_policy(conn, "deny", admin.id, role="developer", action="invoke", resource="*")
    t_mid = now_iso()                       # snapshot: policy is live here
    delete_policy(conn, p.id, changed_by=admin.id)

    at_mid = policies_in_effect_at(conn, t_mid)
    assert any(x["policy_id"] == p.id for x in at_mid)     # in effect at t_mid
    at_now = policies_in_effect_at(conn, now_iso())
    assert not any(x["policy_id"] == p.id for x in at_now)  # deleted by now


def test_history_spans_all_policies():
    conn, admin = setup()
    create_policy(conn, "allow", admin.id, action="tool", resource="search")
    create_policy(conn, "deny", admin.id, action="command", resource="rm")
    assert len(list_policy_versions(conn)) == 2
