import pytest
from fastapi.testclient import TestClient

from open_refinery import (
    connect,
    create_user,
    get_setting,
    list_setting_keys,
    set_setting,
)
from open_refinery.models import Setting
from open_refinery.web import create_app


@pytest.fixture(autouse=True)
def secret(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "test-secret")


def test_setting_encrypted_and_readable():
    conn = connect("sqlite:///:memory:")
    admin, _ = create_user(conn, "a@x.dev", "pw", "admin")
    set_setting(conn, "github.client_secret", "shhh", admin.id)
    stored = conn.get(Setting, "github.client_secret").value
    assert "shhh" not in stored                       # encrypted at rest
    assert get_setting(conn, "github.client_secret") == "shhh"  # decrypts
    assert list_setting_keys(conn) == ["github.client_secret"]  # keys only


def test_settings_api_never_returns_values_and_is_role_gated(monkeypatch):
    conn = connect("sqlite:///:memory:", check_same_thread=False)
    admin, admin_tok = create_user(conn, "admin@x.dev", "pw", "admin")
    ops, ops_tok = create_user(conn, "ops@x.dev", "pw", "platform")
    dev, dev_tok = create_user(conn, "dev@x.dev", "pw", "developer")
    c = TestClient(create_app(conn))

    ah = {"Authorization": f"Bearer {ops_tok}"}   # settings are operations
    assert c.put("/settings", headers=ah,
                 json={"key": "github.client_id", "value": "cid123"}).status_code == 200
    body = c.get("/settings", headers=ah).json()
    assert body["keys"] == ["github.client_id"]       # keys only, no values
    assert "cid123" not in c.get("/settings", headers=ah).text

    # neither developers nor admin touch settings: one has no operational
    # authority, the other manages users and reads audit.
    for tok in (dev_tok, admin_tok):
        h = {"Authorization": f"Bearer {tok}"}
        assert c.get("/settings", headers=h).status_code == 403
        assert c.put("/settings", headers=h, json={"key": "x", "value": "y"}).status_code == 403


def test_providers_reports_only_password_auth():
    """OAuth client id/secret were product configuration wearing a server
    variable's clothes. 2.14.0 removed the flow, so there is nothing to enable:
    humans sign in with a password, machines with a token, services with a key."""
    conn = connect("sqlite:///:memory:", check_same_thread=False)
    create_user(conn, "admin@x.dev", "pw", "admin")
    c = TestClient(create_app(conn))
    assert c.get("/auth/providers").json() == {"password": True, "mfa": True}
