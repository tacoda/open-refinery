"""The Connections API — personal scope, and no secret ever crosses the wire."""

import pytest
from fastapi.testclient import TestClient

from open_refinery import credentials as creds
from open_refinery.store import connect
from open_refinery.users import create_session, create_user, ensure_default_roles
from open_refinery.web import create_app


@pytest.fixture
def ctx(monkeypatch):
    monkeypatch.setattr(creds, "verify_credential",
                        lambda key, cred: {"account": f"{key}-account"})
    session = connect("sqlite:///:memory:", check_same_thread=False)
    ensure_default_roles(session)
    dana, _ = create_user(session, "dana@example.com", "pw", "developer")
    sam, _ = create_user(session, "sam@example.com", "pw", "developer")
    boss, _ = create_user(session, "boss@example.com", "pw", "admin")
    ops, _ = create_user(session, "ops@example.com", "pw", "platform")
    client = TestClient(create_app(session))

    def hdr(user):
        return {"Authorization": f"Bearer {create_session(session, user.id)}"}

    return client, hdr, dana, sam, boss, ops


def _add(client, hdr, user, provider, credential, **kw):
    return client.post("/credentials", headers=hdr(user),
                       json={"provider": provider, "credential": credential, **kw})


# --- catalog ----------------------------------------------------------------

def test_catalog_lists_providers_with_what_each_key_needs(ctx):
    client, hdr, dana, *_ = ctx
    body = client.get("/credentials/catalog", headers=hdr(dana)).json()
    github = next(p for p in body if p["key"] == "github")

    assert github["family"] == "forge"
    assert "Pull requests" in github["needs"]
    assert github["mint_url"].startswith("https://github.com/settings/tokens")


def test_catalog_filters_by_family(ctx):
    client, hdr, dana, *_ = ctx
    body = client.get("/credentials/catalog?family=model", headers=hdr(dana)).json()
    assert {p["family"] for p in body} == {"model"}


def test_catalog_needs_authentication(ctx):
    client, *_ = ctx
    assert client.get("/credentials/catalog").status_code == 401


# --- connecting -------------------------------------------------------------

def test_connecting_returns_the_account_and_never_the_secret(ctx):
    client, hdr, dana, *_ = ctx
    r = _add(client, hdr, dana, "github", {"token": "ghp_secret_value"})

    assert r.status_code == 201
    assert r.json()["account"] == "github-account"
    assert "ghp_secret_value" not in r.text
    assert "secret" not in r.json()


def test_a_credential_that_does_not_authenticate_is_a_400_with_the_reason(ctx, monkeypatch):
    client, hdr, dana, *_ = ctx

    def boom(key, cred):
        raise RuntimeError("401 Unauthorized")
    monkeypatch.setattr(creds, "verify_credential", boom)

    r = _add(client, hdr, dana, "github", {"token": "bad"})
    assert r.status_code == 400
    assert "401" in r.json()["detail"]


def test_a_missing_required_field_is_a_400(ctx):
    client, hdr, dana, *_ = ctx
    assert _add(client, hdr, dana, "github", {}).status_code == 400


def test_an_unknown_provider_is_a_404(ctx):
    client, hdr, dana, *_ = ctx
    assert _add(client, hdr, dana, "not-a-service", {"token": "t"}).status_code == 404


def test_connecting_is_audited(ctx):
    """Read as admin: the audit trail is oversight-only, which is itself the
    point — a developer cannot check what was recorded about them."""
    client, hdr, dana, _, boss, _ = ctx
    _add(client, hdr, dana, "github", {"token": "t"})

    events = client.get("/events", headers=hdr(boss)).json()
    assert any(e["recipe"] == "credential-connected" and e["actor"] == dana.id
               for e in events)


# --- scoping: credentials are personal --------------------------------------

def test_a_user_sees_only_their_own(ctx):
    client, hdr, dana, sam, *_ = ctx
    _add(client, hdr, dana, "github", {"token": "dana"})
    _add(client, hdr, sam, "github", {"token": "sam"})

    assert len(client.get("/credentials", headers=hdr(dana)).json()) == 1
    assert len(client.get("/credentials", headers=hdr(sam)).json()) == 1


def test_a_developer_cannot_list_another_users_credentials(ctx):
    client, hdr, dana, sam, *_ = ctx
    r = client.get(f"/credentials?owner={sam.id}", headers=hdr(dana))
    assert r.status_code == 403


def test_admin_may_list_another_users_for_oversight_but_gets_no_secret(ctx):
    client, hdr, dana, _, boss, _ = ctx
    _add(client, hdr, dana, "jira",
         {"site": "acme.atlassian.net", "email": "d@x.io", "token": "super-secret"})

    r = client.get(f"/credentials?owner={dana.id}", headers=hdr(boss))
    assert r.status_code == 200 and len(r.json()) == 1
    assert "super-secret" not in r.text


def test_a_developer_cannot_touch_someone_elses_credential(ctx):
    """404 rather than 403 — a distinct 403 would confirm the id exists."""
    client, hdr, dana, sam, *_ = ctx
    cid = _add(client, hdr, dana, "github", {"token": "dana"}).json()["id"]

    assert client.delete(f"/credentials/{cid}", headers=hdr(sam)).status_code == 404
    assert client.post(f"/credentials/{cid}/verify", headers=hdr(sam)).status_code == 404


# --- sharing ----------------------------------------------------------------

def test_a_developer_cannot_publish_an_org_wide_credential(ctx):
    client, hdr, dana, *_ = ctx
    r = _add(client, hdr, dana, "anthropic", {"api_key": "sk"}, shared=True)
    assert r.status_code == 403


def test_platform_may_publish_a_shared_model_key(ctx):
    """Operations decision, so platform's."""
    client, hdr, _, _, _, ops = ctx
    r = _add(client, hdr, ops, "anthropic", {"api_key": "sk"}, shared=True)
    assert r.status_code == 201 and r.json()["shared"] is True


def test_admin_cannot_publish_an_org_wide_credential(ctx):
    """Admin manages users and reads audit. Handing the account-granting role a
    billing key too would collapse the separation of duties."""
    client, hdr, _, _, boss, _ = ctx
    assert _add(client, hdr, boss, "anthropic", {"api_key": "sk"}, shared=True).status_code == 403


def test_not_even_platform_can_share_a_forge_token(ctx):
    """A forge token is an identity — sharing it would attribute everyone's
    pull requests to one person."""
    client, hdr, _, _, _, ops = ctx
    r = _add(client, hdr, ops, "github", {"token": "t"}, shared=True)
    assert r.status_code == 400
    assert "personal" in r.json()["detail"]


# --- lifecycle --------------------------------------------------------------

def test_verify_reports_a_key_that_has_stopped_working(ctx, monkeypatch):
    client, hdr, dana, *_ = ctx
    cid = _add(client, hdr, dana, "github", {"token": "t"}).json()["id"]

    def revoked(key, cred):
        raise RuntimeError("401 Unauthorized")
    monkeypatch.setattr(creds, "verify_credential", revoked)

    body = client.post(f"/credentials/{cid}/verify", headers=hdr(dana)).json()
    assert body["status"] == "failing" and "401" in body["status_detail"]


def test_rotating_keeps_the_id_and_is_audited(ctx):
    client, hdr, dana, _, boss, _ = ctx
    cid = _add(client, hdr, dana, "github", {"token": "old"}).json()["id"]

    r = client.put(f"/credentials/{cid}", headers=hdr(dana),
                   json={"credential": {"token": "new"}})
    assert r.status_code == 200 and r.json()["id"] == cid
    assert "new" not in r.text

    events = client.get("/events", headers=hdr(boss)).json()
    assert any(e["recipe"] == "credential-rotated" for e in events)


def test_revoking_removes_it_and_is_audited(ctx):
    client, hdr, dana, _, boss, _ = ctx
    cid = _add(client, hdr, dana, "github", {"token": "t"}).json()["id"]

    assert client.delete(f"/credentials/{cid}", headers=hdr(dana)).status_code == 200
    assert client.get("/credentials", headers=hdr(dana)).json() == []

    events = client.get("/events", headers=hdr(boss)).json()
    assert any(e["recipe"] == "credential-revoked" for e in events)


# --- the flows that no longer exist -----------------------------------------

@pytest.mark.parametrize("path", [
    "/auth/github/login",
    "/auth/github/callback",
    "/auth/sso/login",
    "/auth/sso/callback",
    "/auth/sso/config",
    "/integrations/github/oauth/start",
    "/integrations/github/oauth/callback",
])
def test_every_authorization_code_route_is_gone(ctx, path):
    """3.0 has no authorization-code flow anywhere. These must 404, not linger
    as dead routes that still accept a redirect."""
    client, hdr, dana, *_ = ctx
    assert client.get(path, headers=hdr(dana)).status_code == 404


def test_auth_providers_reports_only_what_remains(ctx):
    client, *_ = ctx
    body = client.get("/auth/providers").json()
    assert body == {"password": True, "mfa": True}
    assert "github" not in body and "sso" not in body
