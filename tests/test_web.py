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


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_health_needs_no_auth(ctx):
    _, client, *_ = ctx
    assert client.get("/health").json() == {"status": "ok"}


def test_me_requires_valid_token(ctx):
    _, client, admin, token = ctx
    assert client.get("/me").status_code == 401
    assert client.get("/me", headers=auth("bogus")).status_code == 401
    assert client.get("/me", headers=auth(token)).json()["email"] == "admin@x.dev"


def test_only_admin_creates_users(ctx):
    _, client, _, admin_token = ctx
    # admin creates a developer, gets a show-once token back
    r = client.post("/users", headers=auth(admin_token),
                    json={"email": "dev@x.dev", "password": "pw", "role": "developer"})
    assert r.status_code == 201
    dev_token = r.json()["token"]

    # developer cannot create users
    r2 = client.post("/users", headers=auth(dev_token),
                     json={"email": "x@x.dev", "password": "pw", "role": "developer"})
    assert r2.status_code == 403


def test_roles_are_admin_configurable(ctx):
    _, client, _, admin_token = ctx
    dev_token = client.post("/users", headers=auth(admin_token),
                            json={"email": "dev@x.dev", "password": "pw", "role": "developer"}
                            ).json()["token"]

    # default ladder is seeded and any authed user can read it
    names = [r["name"] for r in client.get("/roles", headers=auth(dev_token)).json()]
    assert names == ["developer", "platform", "admin"]

    # only admin adds roles
    assert client.post("/roles", headers=auth(dev_token),
                       json={"name": "senior", "rank": 15}).status_code == 403
    assert client.post("/roles", headers=auth(admin_token),
                       json={"name": "senior", "rank": 15}).status_code == 201
    assert "senior" in [r["name"] for r in client.get("/roles", headers=auth(admin_token)).json()]

    # the admin role is protected
    assert client.delete("/roles/admin", headers=auth(admin_token)).status_code == 400
    assert client.delete("/roles/senior", headers=auth(admin_token)).status_code == 200


def test_ownership_scoping_on_repos(ctx):
    _, client, _, admin_token = ctx
    dev_token = client.post("/users", headers=auth(admin_token),
                            json={"email": "dev@x.dev", "password": "pw", "role": "developer"}
                            ).json()["token"]

    client.post("/repositories", headers=auth(dev_token),
                json={"name": "a", "git_url": "git@x:a.git"})
    client.post("/repositories", headers=auth(admin_token),
                json={"name": "b", "git_url": "git@x:b.git"})

    # developer sees only their own; admin sees all
    assert len(client.get("/repositories", headers=auth(dev_token)).json()) == 1
    assert len(client.get("/repositories", headers=auth(admin_token)).json()) == 2


def test_end_to_end_transition_and_audit(ctx):
    _, client, admin, admin_token = ctx
    h = auth(admin_token)
    repo = client.post("/repositories", headers=h,
                       json={"name": "or", "git_url": "git@x:or.git"}).json()
    proc = client.post("/processes", headers=h,
                       json={"name": "flow", "archetype": "doctrine",
                             "stages": ["todo", "doing", "done"]}).json()
    item = client.post("/work-items", headers=h,
                       json={"repo_id": repo["id"], "process_id": proc["id"],
                             "title": "T"}).json()
    assert item["current_stage"] == "todo"

    moved = client.post(f"/work-items/{item['id']}/transition", headers=h,
                        json={"to": "doing"})
    assert moved.status_code == 200 and moved.json()["current_stage"] == "doing"

    # illegal move rejected
    bad = client.post(f"/work-items/{item['id']}/transition", headers=h,
                      json={"to": "todo"})  # doing -> todo not allowed (doctrine)
    assert bad.status_code == 409

    # audit trail records the one valid transition, subject = the item
    events = client.get(f"/events?subject={item['id']}", headers=h).json()
    assert len(events) == 1 and events[0]["recipe"] == "transition"


def test_oversight_approval_flow(ctx):
    _, client, _, admin_token = ctx
    h = auth(admin_token)
    repo = client.post("/repositories", headers=h,
                       json={"name": "or", "git_url": "git@x:or.git"}).json()
    proc = client.post("/processes", headers=h,
                       json={"name": "flow", "archetype": "board",
                             "stages": ["todo", "doing"], "oversight": "assisted"}).json()
    item = client.post("/work-items", headers=h,
                       json={"repo_id": repo["id"], "process_id": proc["id"],
                             "title": "T"}).json()

    # without approval → 409
    blocked = client.post(f"/work-items/{item['id']}/transition", headers=h,
                          json={"to": "doing"})
    assert blocked.status_code == 409

    # with approve=true → applies
    ok = client.post(f"/work-items/{item['id']}/transition", headers=h,
                     json={"to": "doing", "approve": True})
    assert ok.status_code == 200 and ok.json()["current_stage"] == "doing"

    events = client.get(f"/events?subject={item['id']}", headers=h).json()
    assert {e["recipe"] for e in events} == {"transition", "approval"}


def test_duplicate_repo_conflicts(ctx):
    _, client, _, admin_token = ctx
    h = auth(admin_token)
    client.post("/repositories", headers=h, json={"name": "a", "git_url": "git@x:a.git"})
    dup = client.post("/repositories", headers=h, json={"name": "b", "git_url": "git@x:a.git"})
    assert dup.status_code == 409
