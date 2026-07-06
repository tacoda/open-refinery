from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from open_refinery import (
    connect,
    create_target,
    create_user,
    oauth,
    set_target_credential,
    target_credential,
)
from open_refinery.users import create_session
from open_refinery.web import create_app


def test_set_target_credential_round_trip(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    conn = connect("sqlite:///:memory:")
    dev, _ = create_user(conn, "dev@x.dev", "pw", "developer")
    t = create_target(conn, "mcp", "mcp", "https://mcp/x", dev.id)
    assert target_credential(conn, t.id) == {}
    set_target_credential(conn, t.id, {"provider": "github", "access_token": "tok"})
    assert target_credential(conn, t.id) == {"provider": "github", "access_token": "tok"}


@pytest.fixture
def ctx(monkeypatch):
    monkeypatch.setenv("GITHUB_CLIENT_ID", "cid")
    monkeypatch.setenv("GITHUB_CLIENT_SECRET", "csecret")
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    conn = connect("sqlite:///:memory:", check_same_thread=False)
    dev, _ = create_user(conn, "plat@x.dev", "pw", "platform")  # targets are platform-managed
    client = TestClient(create_app(conn), follow_redirects=False)
    return conn, client, dev


def test_target_oauth_handshake_stores_token(ctx, monkeypatch):
    conn, client, dev = ctx
    monkeypatch.setattr(oauth, "exchange_code", lambda kind, code, uri, cid, sec: "oauth-tok")
    t = create_target(conn, "mcp", "mcp", "https://mcp/x", dev.id)
    sess = create_session(conn, dev.id)

    start = client.post(f"/targets/{t.id}/oauth/github/start",
                        headers={"Authorization": f"Bearer {sess}"})
    assert start.status_code == 200
    url = start.json()["authorize_url"]
    assert url.startswith("https://github.com/login/oauth/authorize")
    q = parse_qs(urlparse(url).query)
    assert q["redirect_uri"][0].endswith(f"/targets/{t.id}/oauth/github/callback")
    state = q["state"][0]

    cb = client.get(f"/targets/{t.id}/oauth/github/callback?code=abc&state={state}")
    assert cb.status_code == 307 and "#connected=github" in cb.headers["location"]
    conn.expire_all()  # the callback wrote via its own session; drop the stale identity-map copy
    assert target_credential(conn, t.id) == {"provider": "github", "access_token": "oauth-tok"}


def test_target_oauth_bad_state_redirects_error(ctx):
    conn, client, dev = ctx
    t = create_target(conn, "mcp", "mcp", "https://mcp/x", dev.id)
    cb = client.get(f"/targets/{t.id}/oauth/github/callback?code=abc&state=bogus")
    assert cb.status_code == 307 and "#target_error=state" in cb.headers["location"]
    assert target_credential(conn, t.id) == {}  # nothing stored
