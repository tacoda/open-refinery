"""Adding people and giving them permissions — the surface Phase P exists for."""

import pytest
from fastapi.testclient import TestClient

from open_refinery.store import connect
from open_refinery.users import create_session, create_user, ensure_presets
from open_refinery.web import create_app


@pytest.fixture
def ctx():
    session = connect("sqlite:///:memory:", check_same_thread=False)
    ensure_presets(session)
    boss, _ = create_user(session, "boss@x.io", "pw", "admin")
    dev, _ = create_user(session, "dev@x.io", "pw", "developer")
    client = TestClient(create_app(session))

    def hdr(user):
        return {"Authorization": f"Bearer {create_session(session, user.id)}"}

    return session, client, hdr, boss, dev


# --- the vocabulary ---------------------------------------------------------

def test_every_permission_is_listed_with_what_it_means(ctx):
    _, client, hdr, _, dev = ctx
    body = client.get("/permissions", headers=hdr(dev)).json()

    assert {"code", "harness", "factory", "charter"} == set(body["layers"])
    assert all(p["description"] for p in body["permissions"])


def test_who_can_approve_a_layer_names_people(ctx):
    """What somebody blocked needs is a person, not a rule."""
    session, client, hdr, _, dev = ctx
    lead, _ = create_user(session, "lead@x.io", "pw", "lead")

    body = client.get("/permissions/approvers/harness", headers=hdr(dev)).json()
    assert body["approvers"] == ["lead@x.io"]


# --- adding a person --------------------------------------------------------

def test_adding_someone_from_a_preset_gives_them_its_permissions(ctx):
    _, client, hdr, boss, _ = ctx
    r = client.post("/users", headers=hdr(boss),
                    json={"email": "new@x.io", "password": "pw", "role": "lead"})

    assert r.status_code == 201
    assert "approve:harness" in r.json()["user"]["permissions"]


def test_a_person_can_be_added_with_permissions_no_preset_offers(ctx):
    """Two people doing similar jobs can differ without inventing a role."""
    _, client, hdr, boss, _ = ctx
    r = client.post("/users", headers=hdr(boss),
                    json={"email": "odd@x.io", "password": "pw", "role": "developer",
                          "permissions": ["approve:code", "approve:harness"]})

    assert r.json()["user"]["permissions"] == ["approve:code", "approve:harness"]


def test_adding_someone_is_audited_with_what_they_were_given(ctx):
    _, client, hdr, boss, _ = ctx
    client.post("/users", headers=hdr(boss),
                json={"email": "new@x.io", "password": "pw", "role": "developer"})

    events = client.get("/events", headers=hdr(boss)).json()
    assert any(e["recipe"] == "user-added" for e in events)


def test_a_duplicate_email_is_a_conflict_not_a_crash(ctx):
    _, client, hdr, boss, _ = ctx
    body = {"email": "dev@x.io", "password": "pw", "role": "developer"}
    assert client.post("/users", headers=hdr(boss), json=body).status_code == 409


def test_only_someone_who_manages_users_can_add_one(ctx):
    _, client, hdr, _, dev = ctx
    r = client.post("/users", headers=hdr(dev),
                    json={"email": "x@x.io", "password": "pw", "role": "developer"})
    assert r.status_code == 403


def test_a_created_user_never_leaks_secret_fields(ctx):
    _, client, hdr, boss, _ = ctx
    r = client.post("/users", headers=hdr(boss),
                    json={"email": "new@x.io", "password": "pw", "role": "developer"})
    assert {"pw_hash", "pw_salt", "token_hash"}.isdisjoint(r.json()["user"])


# --- changing what someone may do -------------------------------------------

def test_permissions_can_be_edited_after_the_fact(ctx):
    _, client, hdr, boss, dev = ctx
    r = client.put(f"/users/{dev.id}/permissions", headers=hdr(boss),
                   json={"permissions": ["approve:code", "read:audit"]})

    assert r.status_code == 200
    assert r.json()["permissions"] == ["approve:code", "read:audit"]


def test_a_preset_can_seed_the_edit(ctx):
    _, client, hdr, boss, dev = ctx
    r = client.put(f"/users/{dev.id}/permissions", headers=hdr(boss),
                   json={"preset": "platform", "permissions": ["read:audit"]})

    held = r.json()["permissions"]
    assert "approve:factory" in held and "read:audit" in held


def test_editing_permissions_takes_effect_immediately(ctx):
    """The set is what is checked — not a cached role."""
    _, client, hdr, boss, dev = ctx
    assert client.get("/settings", headers=hdr(dev)).status_code == 403

    client.put(f"/users/{dev.id}/permissions", headers=hdr(boss),
               json={"permissions": ["see:operations"]})
    assert client.get("/settings", headers=hdr(dev)).status_code == 200


def test_you_cannot_change_your_own_permissions(ctx):
    """The one thing any permission model must make impossible."""
    _, client, hdr, boss, _ = ctx
    r = client.put(f"/users/{boss.id}/permissions", headers=hdr(boss),
                   json={"permissions": ["approve:factory"]})

    assert r.status_code == 403
    assert "your own" in r.json()["detail"]


def test_managing_users_does_not_imply_granting_yourself_more(ctx):
    """`manage:users` lets you set other people's permissions, and is not a
    back door to holding them."""
    from open_refinery import authority

    session, client, hdr, boss, _ = ctx
    client.put(f"/users/{boss.id}/permissions", headers=hdr(boss),
               json={"permissions": ["approve:factory"]})
    session.refresh(boss)
    assert not authority.may_approve(boss, "factory")


def test_an_unknown_permission_is_rejected(ctx):
    _, client, hdr, boss, dev = ctx
    r = client.put(f"/users/{dev.id}/permissions", headers=hdr(boss),
                   json={"permissions": ["approve:everything"]})
    assert r.status_code == 400


def test_a_permission_change_is_audited_with_before_and_after(ctx):
    _, client, hdr, boss, dev = ctx
    client.put(f"/users/{dev.id}/permissions", headers=hdr(boss),
               json={"permissions": ["read:audit"]})

    events = client.get("/events", headers=hdr(boss)).json()
    assert any(e["recipe"] == "permissions-changed" for e in events)


def test_anyone_can_see_what_they_themselves_hold(ctx):
    """Being unable to answer "what am I allowed to do" is its own problem."""
    _, client, hdr, _, dev = ctx
    r = client.get(f"/users/{dev.id}/permissions", headers=hdr(dev))
    assert r.status_code == 200 and "approve:code" in r.json()["permissions"]


def test_a_developer_cannot_read_someone_elses_permissions(ctx):
    _, client, hdr, boss, dev = ctx
    assert client.get(f"/users/{boss.id}/permissions", headers=hdr(dev)).status_code == 403


# --- presets ----------------------------------------------------------------

def test_a_custom_preset_can_be_defined_and_used(ctx):
    _, client, hdr, boss, _ = ctx
    client.put("/presets/reviewer", headers=hdr(boss),
               json={"rank": 1, "permissions": ["approve:code"]})

    r = client.post("/users", headers=hdr(boss),
                    json={"email": "rev@x.io", "password": "pw", "role": "reviewer"})
    assert r.json()["user"]["permissions"] == ["approve:code"]


def test_shipped_presets_cannot_be_changed(ctx):
    _, client, hdr, boss, _ = ctx
    r = client.put("/presets/developer", headers=hdr(boss),
                   json={"rank": 1, "permissions": []})
    assert r.status_code == 403


def test_editing_a_preset_does_not_change_people_already_created_from_it(ctx):
    """A preset is a starting point, not a role. The UI says so."""
    _, client, hdr, boss, _ = ctx
    client.put("/presets/reviewer", headers=hdr(boss),
               json={"rank": 1, "permissions": ["approve:code"]})
    created = client.post("/users", headers=hdr(boss),
                          json={"email": "rev@x.io", "password": "pw",
                                "role": "reviewer"}).json()["user"]

    client.put("/presets/reviewer", headers=hdr(boss),
               json={"rank": 1, "permissions": ["read:audit"]})

    still = client.get(f"/users/{created['id']}/permissions", headers=hdr(boss)).json()
    assert still["permissions"] == ["approve:code"]
