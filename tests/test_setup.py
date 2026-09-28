from fastapi.testclient import TestClient

from open_refinery import connect
from open_refinery.web import create_app


def client():
    return TestClient(create_app(connect("sqlite:///:memory:", check_same_thread=False)))


def test_fresh_instance_needs_setup():
    c = client()
    assert c.get("/setup/status").json() == {"needs_setup": True}


def test_setup_creates_admin_then_locks():
    c = client()
    r = c.post("/setup", json={"email": "boss@x.dev", "password": "pw"})
    assert r.status_code == 201
    body = r.json()
    assert body["user"]["role"] == "admin" and body["token"]

    # setup is now closed
    assert c.get("/setup/status").json() == {"needs_setup": False}
    assert c.post("/setup", json={"email": "x@x.dev", "password": "pw"}).status_code == 409

    # the returned token works
    assert c.get("/me", headers={"Authorization": f"Bearer {body['token']}"}).status_code == 200


def test_a_fresh_install_has_a_workflow_to_run():
    """"Defaults to build from" has to mean the defaults are there.

    Without this, an install had no pipeline at all: `POST /runs` failed on
    `ship-a-ticket`, a name nobody had typed, and autostart silently did
    nothing.
    """
    c = client()
    token = c.post("/setup", json={"email": "boss@x.dev", "password": "pw"}).json()["token"]
    auth = {"Authorization": f"Bearer {token}"}

    pipelines = c.get("/pipelines", headers=auth).json()
    assert [p["name"] for p in pipelines] == ["ship-a-ticket"]
    assert pipelines[0]["stages"], "the default workflow has stages"


def test_the_first_account_can_actually_do_something(client_=None):
    """The `admin` preset is narrow on purpose — add people, read the trail. On
    a fresh install that is a dead end: there is nobody else, and nobody may
    change their own permissions. The owner of the installation holds
    everything and delegates from there.
    """
    from open_refinery.authority import PERMISSIONS

    c = client()
    boss = c.post("/setup", json={"email": "boss@x.dev", "password": "pw"}).json()
    auth = {"Authorization": f"Bearer {boss['token']}"}

    assert set(boss["user"]["permissions"]) == set(PERMISSIONS)

    # the thing that was impossible before: standing up the machinery
    made = c.post("/processes", headers=auth,
                  json={"name": "flow", "archetype": "board", "stages": ["todo", "done"]})
    assert made.status_code == 201, made.json()

    # and the next admin is still narrow — this is the owner, not the preset
    other = c.post("/users", headers=auth,
                   json={"email": "admin2@x.dev", "password": "pw", "role": "admin"}).json()
    assert set(other["user"]["permissions"]) == {"manage:users", "read:audit"}


def test_nobody_may_change_their_own_permissions(monkeypatch):
    """Including the owner. Separation of duties does not have an exception for
    the person who finds it inconvenient."""
    c = client()
    boss = c.post("/setup", json={"email": "boss@x.dev", "password": "pw"}).json()
    auth = {"Authorization": f"Bearer {boss['token']}"}
    r = c.put(f"/users/{boss['user']['id']}/permissions", headers=auth,
              json={"permissions": ["read:audit"]})
    assert r.status_code == 403 and "your own" in r.json()["detail"]
