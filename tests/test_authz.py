"""Authorization comes from permissions, never from a role name.

Until 2.16.0 a regex table in `web.py` matched paths to role *names* and ran as
middleware on top of the per-route dependencies. Two authorization systems that
could disagree — and they did, the moment permissions moved onto the user: a
grant took effect in `/me` and was still refused by the middleware.

These tests pin the replacement: one guard per route, reading the caller's own
permission set.
"""

import pytest
from fastapi.testclient import TestClient

from open_refinery.store import connect
from open_refinery.users import create_session, create_user, ensure_presets
from open_refinery.web import create_app


@pytest.fixture
def ctx():
    session = connect("sqlite:///:memory:", check_same_thread=False)
    ensure_presets(session)
    people = {p: create_user(session, f"{p}@x.io", "pw", p)[0]
              for p in ("developer", "lead", "platform", "admin")}
    client = TestClient(create_app(session))

    def hdr(who):
        return {"Authorization": f"Bearer {create_session(session, people[who].id)}"}

    return session, client, hdr, people


# --- the same permission, granted directly, works ---------------------------

def test_a_permission_granted_directly_is_enough(ctx):
    """No role required — the set is the authorization."""
    session, client, hdr, people = ctx
    odd, _ = create_user(session, "odd@x.io", "pw", "developer",
                         permissions=["see:operations"])
    token = create_session(session, odd.id)

    r = client.get("/settings", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200


def test_a_permission_revoked_takes_effect_at_once(ctx):
    """The failure the old middleware caused: a grant landing in /me and still
    being refused on the route."""
    session, client, hdr, people = ctx
    ops = people["platform"]
    assert client.get("/settings", headers=hdr("platform")).status_code == 200

    client.put(f"/users/{ops.id}/permissions", headers=hdr("admin"),
               json={"permissions": []})
    assert client.get("/settings", headers=hdr("platform")).status_code == 403


def test_the_name_of_the_preset_grants_nothing_by_itself(ctx):
    """Someone started from `platform` but stripped of its permissions is not
    platform in any way that matters."""
    session, client, hdr, people = ctx
    bare, _ = create_user(session, "bare@x.io", "pw", "platform", permissions=[])
    token = create_session(session, bare.id)

    assert bare.role == "platform"
    assert client.get("/settings",
                      headers={"Authorization": f"Bearer {token}"}).status_code == 403


# --- who can reach what -----------------------------------------------------

@pytest.mark.parametrize("who,expected", [
    ("platform", 200), ("developer", 403), ("lead", 403), ("admin", 403)])
def test_operations_surfaces_need_see_operations(ctx, who, expected):
    _, client, hdr, _ = ctx
    assert client.get("/settings", headers=hdr(who)).status_code == expected


@pytest.mark.parametrize("who,expected", [
    ("admin", 200), ("developer", 403), ("lead", 403), ("platform", 403)])
def test_the_audit_trail_needs_read_audit(ctx, who, expected):
    _, client, hdr, _ = ctx
    assert client.get("/events", headers=hdr(who)).status_code == expected


@pytest.mark.parametrize("who,expected", [
    ("admin", 201), ("developer", 403), ("lead", 403), ("platform", 403)])
def test_adding_people_needs_manage_users(ctx, who, expected):
    _, client, hdr, _ = ctx
    r = client.post("/users", headers=hdr(who),
                    json={"email": f"new-{who}@x.io", "password": "pw",
                          "role": "developer"})
    assert r.status_code == expected


@pytest.mark.parametrize("who,expected", [
    ("platform", 201), ("developer", 403), ("lead", 403), ("admin", 403)])
def test_factory_configuration_needs_approve_factory(ctx, who, expected):
    """A pipeline is the stage graph — factory configuration, which is
    platform's. A developer proposes one; they do not sign it off."""
    _, client, hdr, _ = ctx
    r = client.post("/pipelines", headers=hdr(who),
                    json={"name": f"flow-{who}", "first": "a", "terminal": ["done"],
                          "stages": {"a": {"action": "prepare_workspace", "next": "done"}}})
    assert r.status_code == expected


def test_admin_cannot_configure_the_factory(ctx):
    """The account that grants access does not shape what ships."""
    _, client, hdr, _ = ctx
    r = client.post("/pipelines", headers=hdr("admin"),
                    json={"name": "flow", "first": "a", "terminal": ["done"],
                          "stages": {"a": {"action": "prepare_workspace", "next": "done"}}})
    assert r.status_code == 403


def test_a_refusal_names_who_can_actually_sign_it(ctx):
    """What somebody blocked needs is a person, not the rule they hit."""
    _, client, hdr, _ = ctx
    r = client.post("/pipelines", headers=hdr("developer"),
                    json={"name": "flow", "first": "a",
                          "stages": {"a": {"kind": "action", "action": "prepare"}}})
    assert r.status_code == 403
    assert "platform@x.io" in r.json()["detail"]


# --- the auditor grant ------------------------------------------------------

def test_an_auditor_grant_reads_the_trail_and_writes_nothing(ctx):
    from open_refinery.auditors import mint_auditor

    session, client, hdr, people = ctx
    _, token = mint_auditor(session, "external review", people["admin"].id, ttl_days=1)
    h = {"Authorization": f"Bearer {token}"}

    assert client.get("/events", headers=h).status_code == 200
    assert client.post("/pipelines", headers=h,
                       json={"name": "x", "first": "a", "terminal": ["done"],
                             "stages": {"a": {"action": "prepare_workspace", "next": "done"}}}
                       ).status_code == 403
    assert client.post("/users", headers=h,
                       json={"email": "x@x.io", "password": "pw",
                             "role": "developer"}).status_code == 403
