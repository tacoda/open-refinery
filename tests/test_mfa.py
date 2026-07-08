import pytest
from fastapi.testclient import TestClient

from open_refinery import connect, create_user, totp
from open_refinery.web import create_app


@pytest.fixture
def ctx():
    conn = connect("sqlite:///:memory:", check_same_thread=False)
    admin, admin_token = create_user(conn, "admin@x.dev", "pw", "admin")
    client = TestClient(create_app(conn))
    return conn, client, admin, admin_token


def auth(t):
    return {"Authorization": f"Bearer {t}"}


# --- TOTP primitive ---

def test_totp_verifies_current_code_and_rejects_wrong():
    secret = totp.generate_secret()
    code = totp._code_at(secret, int(1_000_000 // totp.STEP))
    assert totp.verify(secret, code, now=1_000_000)
    assert not totp.verify(secret, "000000", now=1_000_000 + 10_000)  # far-off code
    assert not totp.verify(secret, "abc", now=1_000_000)              # non-numeric


def test_totp_tolerates_one_step_skew():
    secret = totp.generate_secret()
    prev = totp._code_at(secret, int(1_000_000 // totp.STEP) - 1)
    assert totp.verify(secret, prev, now=1_000_000)  # previous step still accepted


# --- enrollment + login gate over HTTP ---

def _enroll(client, token):
    secret = client.post("/auth/mfa/enroll", headers=auth(token)).json()["secret"]
    code = totp._code_at(secret, int(__import__("time").time() // totp.STEP))
    assert client.post("/auth/mfa/confirm", headers=auth(token), json={"code": code}
                       ).json() == {"enabled": True}
    return secret


def test_enroll_confirm_then_login_requires_code(ctx):
    conn, client, admin, token = ctx
    assert client.get("/auth/mfa/status", headers=auth(token)).json() == {"enabled": False}
    secret = _enroll(client, token)
    assert client.get("/auth/mfa/status", headers=auth(token)).json() == {"enabled": True}

    # password alone is now rejected
    r = client.post("/auth/login", json={"email": "admin@x.dev", "password": "pw"})
    assert r.status_code == 401 and r.json()["detail"] == "mfa_required"

    # password + valid TOTP succeeds
    code = totp._code_at(secret, int(__import__("time").time() // totp.STEP))
    ok = client.post("/auth/login", json={"email": "admin@x.dev", "password": "pw", "code": code})
    assert ok.status_code == 200 and ok.json()["token"]


def test_confirm_rejects_bad_code(ctx):
    conn, client, admin, token = ctx
    client.post("/auth/mfa/enroll", headers=auth(token))
    r = client.post("/auth/mfa/confirm", headers=auth(token), json={"code": "000000"})
    assert r.status_code == 400
    assert client.get("/auth/mfa/status", headers=auth(token)).json() == {"enabled": False}


def test_disable_requires_valid_code_then_login_open(ctx):
    conn, client, admin, token = ctx
    secret = _enroll(client, token)
    import time
    assert client.post("/auth/mfa/disable", headers=auth(token), json={"code": "000000"}).status_code == 400
    code = totp._code_at(secret, int(time.time() // totp.STEP))
    assert client.post("/auth/mfa/disable", headers=auth(token), json={"code": code}
                       ).json() == {"enabled": False}
    # password alone works again
    assert client.post("/auth/login", json={"email": "admin@x.dev", "password": "pw"}).status_code == 200
