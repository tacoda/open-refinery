import pytest
from fastapi.testclient import TestClient

from open_refinery import connect, create_user
from open_refinery import oauth
from open_refinery.users import create_session, session_user
from open_refinery.web import create_app


@pytest.fixture
def ctx(monkeypatch):
    monkeypatch.setenv("GITHUB_CLIENT_ID", "cid")
    monkeypatch.setenv("GITHUB_CLIENT_SECRET", "csecret")
    conn = connect("sqlite:///:memory:", check_same_thread=False)
    user, _ = create_user(conn, "dev@x.dev", "pw", "developer")
    # TestClient with redirects off so we can inspect Location headers
    client = TestClient(create_app(conn), follow_redirects=False)
    return conn, client, user


def test_session_token_authenticates(ctx):
    conn, client, user = ctx
    sess = create_session(conn, user.id)
    assert session_user(conn, sess) == user
    assert client.get("/me", headers={"Authorization": f"Bearer {sess}"}).json()["email"] == "dev@x.dev"


def test_providers_reports_github_enabled(ctx):
    _, client, _ = ctx
    assert client.get("/auth/providers").json() == {"github": True}


def test_login_redirects_to_github_with_state_cookie(ctx):
    _, client, _ = ctx
    r = client.get("/auth/github/login")
    assert r.status_code == 307
    assert r.headers["location"].startswith("https://github.com/login/oauth/authorize")
    assert "or_oauth_state" in r.cookies


def test_callback_rejects_state_mismatch(ctx):
    _, client, _ = ctx
    r = client.get("/auth/github/callback?code=x&state=nope")
    assert r.status_code == 400


def test_callback_known_email_issues_session(ctx, monkeypatch):
    conn, client, user = ctx
    monkeypatch.setattr(oauth, "exchange_code", lambda code, uri: "gh-token")
    monkeypatch.setattr(oauth, "primary_email", lambda tok: "dev@x.dev")
    client.cookies.set("or_oauth_state", "s1")
    r = client.get("/auth/github/callback?code=abc&state=s1")
    assert r.status_code == 307
    loc = r.headers["location"]
    assert "#token=" in loc
    token = loc.split("#token=")[1]
    assert session_user(conn, token) == user


def test_callback_unknown_email_denied(ctx, monkeypatch):
    _, client, _ = ctx
    monkeypatch.setattr(oauth, "exchange_code", lambda code, uri: "gh-token")
    monkeypatch.setattr(oauth, "primary_email", lambda tok: "stranger@x.dev")
    client.cookies.set("or_oauth_state", "s1")
    r = client.get("/auth/github/callback?code=abc&state=s1")
    assert r.status_code == 307
    assert "#oauth_error=no-account" in r.headers["location"]
