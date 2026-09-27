"""Defining roles — the surface that makes the built-ins a default, not a limit."""

import pytest
from fastapi.testclient import TestClient

from open_refinery.store import connect
from open_refinery.users import create_session, create_user, ensure_default_roles
from open_refinery.web import create_app


@pytest.fixture
def ctx():
    session = connect("sqlite:///:memory:", check_same_thread=False)
    ensure_default_roles(session)
    boss, _ = create_user(session, "boss@x.io", "pw", "admin")
    ops, _ = create_user(session, "ops@x.io", "pw", "platform")
    dev, _ = create_user(session, "dev@x.io", "pw", "developer")
    client = TestClient(create_app(session))

    def hdr(user):
        return {"Authorization": f"Bearer {create_session(session, user.id)}"}

    return session, client, hdr, boss, ops, dev


# --- reading ----------------------------------------------------------------

def test_anyone_can_read_the_roles_and_their_powers(ctx):
    """"Who approves a harness change" is a question everyone needs answered;
    hiding it only means asking a person instead."""
    _, client, hdr, _, _, dev = ctx
    rows = {r["name"]: r for r in client.get("/roles", headers=hdr(dev)).json()}

    assert rows["lead"]["approves"] == ["harness", "charter"]
    assert rows["platform"]["approves"] == ["factory"]
    assert rows["admin"]["approves"] == []


def test_layers_are_listed_for_the_role_editor(ctx):
    _, client, hdr, _, _, dev = ctx
    layers = client.get("/roles/layers", headers=hdr(dev)).json()["layers"]
    assert set(layers) == {"code", "harness", "factory", "charter"}


# --- defining ---------------------------------------------------------------

def test_admin_can_define_a_custom_role(ctx):
    _, client, hdr, boss, _, _ = ctx
    r = client.put("/roles/reviewer", headers=hdr(boss),
                   json={"rank": 1, "approves": ["code"], "proposes": ["code"]})

    assert r.status_code == 200
    body = r.json()
    assert body["approves"] == ["code"] and body["builtin"] is False


def test_a_custom_role_actually_grants_authority(ctx):
    """The role editor is not cosmetic — a role defined here is checked by the
    same `authority` the route guards use."""
    from open_refinery.authority import may_approve

    session, client, hdr, boss, _, _ = ctx
    client.put("/roles/reviewer", headers=hdr(boss),
               json={"rank": 1, "approves": ["harness"]})

    assert may_approve(session, "reviewer", "harness")
    assert not may_approve(session, "reviewer", "factory")


def test_omitted_powers_are_left_alone(ctx):
    """Setting a rank must not silently clear what a role may approve."""
    _, client, hdr, boss, _, _ = ctx
    client.put("/roles/reviewer", headers=hdr(boss),
               json={"rank": 1, "approves": ["code"]})
    body = client.put("/roles/reviewer", headers=hdr(boss), json={"rank": 2}).json()

    assert body["rank"] == 2 and body["approves"] == ["code"]


def test_an_unknown_layer_is_rejected(ctx):
    _, client, hdr, boss, _, _ = ctx
    r = client.put("/roles/reviewer", headers=hdr(boss),
                   json={"rank": 1, "approves": ["not-a-layer"]})
    assert r.status_code == 400


# --- the guardrails ---------------------------------------------------------

def test_you_cannot_edit_the_role_you_hold(ctx):
    """Otherwise the one thing every authority model must prevent — granting
    yourself more authority — is a single PUT away."""
    _, client, hdr, boss, _, _ = ctx
    r = client.put("/roles/admin", headers=hdr(boss),
                   json={"rank": 9, "approves": ["code", "harness", "factory"]})

    assert r.status_code == 403
    assert "role you hold" in r.json()["detail"]


def test_built_in_roles_cannot_be_changed(ctx):
    _, client, hdr, boss, _, _ = ctx
    for name in ("developer", "lead", "platform", "auditor"):
        r = client.put(f"/roles/{name}", headers=hdr(boss), json={"rank": 9})
        assert r.status_code == 403, name


def test_built_in_roles_cannot_be_deleted(ctx):
    _, client, hdr, boss, _, _ = ctx
    assert client.delete("/roles/lead", headers=hdr(boss)).status_code == 403


def test_a_role_still_assigned_to_someone_cannot_be_deleted(ctx):
    session, client, hdr, boss, _, _ = ctx
    client.put("/roles/reviewer", headers=hdr(boss), json={"rank": 1})
    create_user(session, "rev@x.io", "pw", "reviewer")

    r = client.delete("/roles/reviewer", headers=hdr(boss))
    assert r.status_code == 409


def test_an_unused_custom_role_can_be_deleted(ctx):
    _, client, hdr, boss, _, _ = ctx
    client.put("/roles/reviewer", headers=hdr(boss), json={"rank": 1})
    assert client.delete("/roles/reviewer", headers=hdr(boss)).status_code == 200


# --- who may do this --------------------------------------------------------

def test_defining_roles_is_user_management_not_operations(ctx):
    """Platform runs the factory; it does not decide who may approve what."""
    _, client, hdr, _, ops, dev = ctx
    for h in (hdr(ops), hdr(dev)):
        assert client.put("/roles/reviewer", headers=h, json={"rank": 1}).status_code == 403
        assert client.delete("/roles/reviewer", headers=h).status_code == 403


def test_role_changes_are_audited(ctx):
    _, client, hdr, boss, _, _ = ctx
    client.put("/roles/reviewer", headers=hdr(boss),
               json={"rank": 1, "approves": ["code"]})
    client.delete("/roles/reviewer", headers=hdr(boss))

    recipes = [e["recipe"] for e in client.get("/events", headers=hdr(boss)).json()]
    assert "role-changed" in recipes and "role-removed" in recipes
