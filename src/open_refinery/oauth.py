"""OAuth — a small provider registry for sign-in and service connections.

Each provider is gated independently on its client-id/secret env vars: the
button only appears when that provider is configured. GitHub also backs user
login; the same exchange powers connecting any provider's service account.
Stdlib only.
"""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request

PROVIDERS: dict[str, dict] = {
    "github": {
        "authorize": "https://github.com/login/oauth/authorize",
        "token": "https://github.com/login/oauth/access_token",
        "login_scope": "read:user user:email",
        "connect_scope": "repo read:user",
        "id_env": "GITHUB_CLIENT_ID",
        "secret_env": "GITHUB_CLIENT_SECRET",
    },
    "gitlab": {
        "authorize": "https://gitlab.com/oauth/authorize",
        "token": "https://gitlab.com/oauth/token",
        "login_scope": "read_user",
        "connect_scope": "api read_user",
        "id_env": "GITLAB_CLIENT_ID",
        "secret_env": "GITLAB_CLIENT_SECRET",
    },
}


def is_enabled(kind: str = "github") -> bool:
    p = PROVIDERS.get(kind)
    return bool(p and os.environ.get(p["id_env"]) and os.environ.get(p["secret_env"]))


def enabled_providers() -> dict[str, bool]:
    return {kind: is_enabled(kind) for kind in PROVIDERS}


def authorize_url(kind: str, state: str, redirect_uri: str, scope: str) -> str:
    p = PROVIDERS[kind]
    params = urllib.parse.urlencode({
        "client_id": os.environ[p["id_env"]],
        "redirect_uri": redirect_uri,
        "scope": scope,
        "state": state,
        "response_type": "code",  # required by gitlab; accepted by github
    })
    return f"{p['authorize']}?{params}"


def exchange_code(kind: str, code: str, redirect_uri: str) -> str:
    """Trade an authorization code for an access token."""
    p = PROVIDERS[kind]
    fields = {
        "client_id": os.environ[p["id_env"]],
        "client_secret": os.environ[p["secret_env"]],
        "code": code,
        "redirect_uri": redirect_uri,
    }
    if kind == "gitlab":
        fields["grant_type"] = "authorization_code"
    req = urllib.request.Request(
        p["token"], data=urllib.parse.urlencode(fields).encode(),
        headers={"Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        body = json.load(r)
    token = body.get("access_token")
    if not token:
        raise ValueError(f"{kind} token exchange failed: {body.get('error', 'no token')}")
    return token


def primary_email(access_token: str) -> str | None:
    """GitHub verified primary email (used for user login)."""
    req = urllib.request.Request("https://api.github.com/user/emails", headers={
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "open-refinery",
    })
    with urllib.request.urlopen(req, timeout=10) as r:
        emails = json.load(r)
    return next((e["email"] for e in emails if e.get("primary") and e.get("verified")), None)
