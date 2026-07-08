import pytest
from fastapi.testclient import TestClient

from open_refinery import connect, create_user
from open_refinery.web import create_app


@pytest.fixture
def ctx():
    conn = connect("sqlite:///:memory:", check_same_thread=False)
    admin, admin_token = create_user(conn, "admin@x.dev", "pw", "admin")
    client = TestClient(create_app(conn))
    return conn, client, admin, admin_token


def auth(t):
    return {"Authorization": f"Bearer {t}"}


def _setup(client, admin_token):
    tok = client.post("/scim/token", headers=auth(admin_token)).json()["token"]
    client.post("/scim/group-map", headers=auth(admin_token),
                json={"map": {"eng": "developer", "platform-team": "platform"},
                      "default_role": "developer"})
    return tok


def test_config_and_token_are_admin_only(ctx):
    conn, client, admin, token = ctx
    dev = client.post("/users", headers=auth(token),
                      json={"email": "d@x.dev", "password": "pw", "role": "developer"}).json()["token"]
    assert client.get("/scim/config", headers=auth(dev)).status_code == 403
    assert client.post("/scim/token", headers=auth(dev)).status_code == 403


def test_scim_requires_provisioning_token(ctx):
    conn, client, admin, token = ctx
    _setup(client, token)
    assert client.get("/scim/v2/Users").status_code == 401                 # no token
    assert client.get("/scim/v2/Users", headers=auth("bogus")).status_code == 401


def test_provision_maps_highest_group_to_role(ctx):
    conn, client, admin, token = ctx
    scim_tok = _setup(client, token)
    r = client.post("/scim/v2/Users", headers=auth(scim_tok),
                    json={"userName": "new@acme.test",
                          "groups": [{"display": "eng"}, {"display": "platform-team"}]})
    assert r.status_code == 201 and r.json()["active"] is True
    users = {u["email"]: u["role"] for u in client.get("/users", headers=auth(token)).json()}
    assert users["new@acme.test"] == "platform"  # most-privileged mapped group wins


def test_unmapped_groups_get_default_role(ctx):
    conn, client, admin, token = ctx
    scim_tok = _setup(client, token)
    client.post("/scim/v2/Users", headers=auth(scim_tok),
                json={"userName": "u2@acme.test", "groups": [{"display": "unknown"}]})
    users = {u["email"]: u["role"] for u in client.get("/users", headers=auth(token)).json()}
    assert users["u2@acme.test"] == "developer"


def test_list_filter_by_username(ctx):
    conn, client, admin, token = ctx
    scim_tok = _setup(client, token)
    client.post("/scim/v2/Users", headers=auth(scim_tok), json={"userName": "f@acme.test"})
    r = client.get('/scim/v2/Users?filter=userName eq "f@acme.test"', headers=auth(scim_tok)).json()
    assert r["totalResults"] == 1 and r["Resources"][0]["userName"] == "f@acme.test"


def test_deprovision_deactivates_and_blocks_login(ctx):
    conn, client, admin, token = ctx
    scim_tok = _setup(client, token)
    # a local user who can log in with a password
    made = client.post("/users", headers=auth(token),
                       json={"email": "leaver@x.dev", "password": "pw", "role": "developer"}).json()
    assert client.post("/auth/login", json={"email": "leaver@x.dev", "password": "pw"}).status_code == 200

    # IdP deprovisions via PATCH active:false
    r = client.patch(f"/scim/v2/Users/{made['user']['id']}", headers=auth(scim_tok),
                     json={"Operations": [{"op": "replace", "value": {"active": False}}]})
    assert r.status_code == 200 and r.json()["active"] is False
    assert client.post("/auth/login", json={"email": "leaver@x.dev", "password": "pw"}).status_code == 401


def test_delete_soft_deactivates(ctx):
    conn, client, admin, token = ctx
    scim_tok = _setup(client, token)
    created = client.post("/scim/v2/Users", headers=auth(scim_tok),
                          json={"userName": "gone@acme.test"}).json()
    assert client.delete(f"/scim/v2/Users/{created['id']}", headers=auth(scim_tok)).status_code == 204
    assert client.get(f"/scim/v2/Users/{created['id']}", headers=auth(scim_tok)).json()["active"] is False
