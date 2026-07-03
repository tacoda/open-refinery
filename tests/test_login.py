from fastapi.testclient import TestClient

from open_refinery import connect, create_user
from open_refinery.web import create_app


def ctx():
    conn = connect("sqlite:///:memory:", check_same_thread=False)
    create_user(conn, "ian@x.dev", "s3cret", "admin")
    return TestClient(create_app(conn))


def test_login_with_password_returns_working_session():
    c = ctx()
    r = c.post("/auth/login", json={"email": "ian@x.dev", "password": "s3cret"})
    assert r.status_code == 200
    token = r.json()["token"]
    me = c.get("/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200 and me.json()["email"] == "ian@x.dev"


def test_login_rejects_bad_credentials():
    c = ctx()
    assert c.post("/auth/login", json={"email": "ian@x.dev", "password": "wrong"}).status_code == 401
    assert c.post("/auth/login", json={"email": "nobody@x.dev", "password": "s3cret"}).status_code == 401
