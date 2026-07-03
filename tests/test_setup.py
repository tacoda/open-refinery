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
