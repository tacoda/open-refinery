"""OIDC single sign-on — log in via the org's IdP (Okta, Entra, Google, Auth0…).

Standards-only, stdlib-only: OIDC discovery → authorization-code flow → the
UserInfo endpoint for the verified email. We read the email from UserInfo (an
access-token call over TLS) rather than verifying the id_token JWT signature, so
no crypto dependency is pulled into the core. The IdP is the authentication
authority (and MFA authority for SSO logins); we only map its verified email to
an **existing** user — provisioning + group→role mapping is a later phase.

Config lives in encrypted settings (`oidc.issuer|client_id|client_secret|name`).
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request

from sqlmodel import Session

from .settings import get_setting

SCOPE = "openid email profile"
_KEYS = ("issuer", "client_id", "client_secret", "name")


_REQUIRED = ("issuer", "client_id", "client_secret")


def config(session: Session) -> dict | None:
    """The configured OIDC provider, or None if SSO isn't set up."""
    vals = {k: get_setting(session, f"oidc.{k}") or "" for k in _KEYS}
    if not all(vals[k] for k in _REQUIRED):
        return None
    return vals


def _get(url: str, headers: dict | None = None) -> dict:
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.load(r)


def discover(issuer: str) -> dict:
    """Fetch the IdP's endpoints from its .well-known discovery document."""
    doc = _get(issuer.rstrip("/") + "/.well-known/openid-configuration")
    return {"authorization_endpoint": doc["authorization_endpoint"],
            "token_endpoint": doc["token_endpoint"],
            "userinfo_endpoint": doc["userinfo_endpoint"]}


def authorize_url(endpoints: dict, client_id: str, redirect_uri: str, state: str) -> str:
    params = urllib.parse.urlencode({
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": SCOPE,
        "state": state,
    })
    return f"{endpoints['authorization_endpoint']}?{params}"


def exchange_code(endpoints: dict, code: str, redirect_uri: str, creds: dict) -> str:
    """Trade the authorization code for an access token (creds: client_id/secret)."""
    fields = urllib.parse.urlencode({
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": creds["client_id"],
        "client_secret": creds["client_secret"],
    }).encode()
    req = urllib.request.Request(endpoints["token_endpoint"], data=fields,
                                 headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        body = json.load(r)
    token = body.get("access_token")
    if not token:
        raise ValueError(f"oidc token exchange failed: {body.get('error', 'no token')}")
    return token


def userinfo_email(endpoints: dict, access_token: str) -> str | None:
    """The IdP's verified email claim for the signed-in principal."""
    info = _get(endpoints["userinfo_endpoint"], {"Authorization": f"Bearer {access_token}"})
    if info.get("email_verified") is False:  # explicit false only; absent = trust IdP
        return None
    return info.get("email") or info.get("preferred_username")
