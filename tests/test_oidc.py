import pytest
from fastapi.testclient import TestClient

from open_refinery import connect, create_user
from open_refinery import oidc
from open_refinery.web import create_app

ENDPOINTS = {"authorization_endpoint": "https://idp.test/authorize",
             "token_endpoint": "https://idp.test/token",
             "userinfo_endpoint": "https://idp.test/userinfo"}


@pytest.fixture
def ctx():
    conn = connect("sqlite:///:memory:", check_same_thread=False)
    admin, admin_token = create_user(conn, "admin@x.dev", "pw", "admin")
    client = TestClient(create_app(conn), follow_redirects=False)
    return conn, client, admin, admin_token


def auth(t):
    return {"Authorization": f"Bearer {t}"}


def _configure(client, admin_token):
    r = client.post("/auth/sso/config", headers=auth(admin_token),
                    json={"issuer": "https://idp.test", "client_id": "cid",
                          "client_secret": "csec", "name": "Acme IdP"})
    assert r.json() == {"enabled": True}


def test_authorize_url_is_well_formed():
    url = oidc.authorize_url(ENDPOINTS, "cid", "https://app/cb", "st8")
    assert url.startswith("https://idp.test/authorize?")
    assert "response_type=code" in url and "scope=openid" in url and "state=st8" in url


def test_config_none_until_set(ctx):
    conn, client, admin, token = ctx
    assert oidc.config(conn) is None
    _configure(client, token)
    cfg = oidc.config(conn)
    assert cfg["issuer"] == "https://idp.test" and cfg["client_secret"] == "csec"


def test_config_endpoint_never_returns_secret(ctx):
    conn, client, admin, token = ctx
    _configure(client, token)
    body = client.get("/auth/sso/config", headers=auth(token)).json()
    assert body == {"enabled": True, "issuer": "https://idp.test", "name": "Acme IdP"}


def test_providers_reports_sso(ctx):
    conn, client, admin, token = ctx
    assert client.get("/auth/providers").json()["sso"] is False
    _configure(client, token)
    out = client.get("/auth/providers").json()
    assert out["sso"] is True and out["sso_name"] == "Acme IdP"


def test_config_is_admin_only(ctx):
    conn, client, admin, token = ctx
    dev_tok = client.post("/users", headers=auth(token),
                          json={"email": "d@x.dev", "password": "pw", "role": "developer"}
                          ).json()["token"]
    assert client.get("/auth/sso/config", headers=auth(dev_tok)).status_code == 403


def test_callback_matches_existing_user(ctx, monkeypatch):
    conn, client, admin, token = ctx
    _configure(client, token)
    create_user(conn, "sso.user@acme.test", "pw", "developer")
    monkeypatch.setattr(oidc, "discover", lambda issuer: ENDPOINTS)
    monkeypatch.setattr(oidc, "exchange_code", lambda *a, **k: "access-tok")
    monkeypatch.setattr(oidc, "userinfo_email", lambda *a, **k: "sso.user@acme.test")

    r = client.get("/auth/sso/callback?code=abc&state=s1", cookies={"or_sso_state": "s1"})
    assert r.status_code == 307 and "#token=" in r.headers["location"]


def test_callback_rejects_state_mismatch(ctx):
    conn, client, admin, token = ctx
    _configure(client, token)
    r = client.get("/auth/sso/callback?code=abc&state=evil", cookies={"or_sso_state": "s1"})
    assert r.status_code == 400


def test_callback_unknown_email_denied(ctx, monkeypatch):
    conn, client, admin, token = ctx
    _configure(client, token)
    monkeypatch.setattr(oidc, "discover", lambda issuer: ENDPOINTS)
    monkeypatch.setattr(oidc, "exchange_code", lambda *a, **k: "access-tok")
    monkeypatch.setattr(oidc, "userinfo_email", lambda *a, **k: "stranger@nowhere.test")

    r = client.get("/auth/sso/callback?code=abc&state=s1", cookies={"or_sso_state": "s1"})
    assert r.status_code == 307 and "sso_error=no-account" in r.headers["location"]
