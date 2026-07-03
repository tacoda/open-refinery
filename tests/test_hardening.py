from fastapi.testclient import TestClient

from open_refinery import connect, create_user
from open_refinery.web import create_app


def test_fresh_instance_has_no_seeded_data():
    """A fresh instance is empty and needs setup — seeds are opt-in, never automatic."""
    conn = connect("sqlite:///:memory:", check_same_thread=False)
    client = TestClient(create_app(conn))
    assert client.get("/setup/status").json() == {"needs_setup": True}
    # create the admin (as the wizard would) and confirm nothing else was seeded
    tok = client.post("/setup", json={"email": "a@x.dev", "password": "pw"}).json()["token"]
    h = {"Authorization": f"Bearer {tok}"}
    assert client.get("/repositories", headers=h).json() == []
    assert client.get("/processes", headers=h).json() == []
    assert client.get("/targets", headers=h).json() == []


def test_token_rotation_invalidates_old_token():
    conn = connect("sqlite:///:memory:", check_same_thread=False)
    user, old = create_user(conn, "ian@x.dev", "pw", "admin")
    client = TestClient(create_app(conn))

    old_h = {"Authorization": f"Bearer {old}"}
    assert client.get("/me", headers=old_h).status_code == 200
    new = client.post("/me/token/rotate", headers=old_h).json()["token"]

    assert new != old
    assert client.get("/me", headers=old_h).status_code == 401  # old token dead
    assert client.get("/me", headers={"Authorization": f"Bearer {new}"}).status_code == 200
