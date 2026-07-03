"""GitHub OAuth — interactive sign-in for human accounts.

Single-tenant: a GitHub login is accepted only if its verified primary email
matches an existing user (admins provision accounts first). The app's OAuth
client id/secret are the one piece of config that must come from the
environment — they are needed before anyone can log in. Stdlib only.
"""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request

_AUTHORIZE = "https://github.com/login/oauth/authorize"
_TOKEN = "https://github.com/login/oauth/access_token"
_EMAILS = "https://api.github.com/user/emails"
_SCOPE = "read:user user:email"


def is_enabled() -> bool:
    return bool(os.environ.get("GITHUB_CLIENT_ID") and os.environ.get("GITHUB_CLIENT_SECRET"))


def authorize_url(state: str, redirect_uri: str, scope: str = _SCOPE) -> str:
    params = urllib.parse.urlencode({
        "client_id": os.environ["GITHUB_CLIENT_ID"],
        "redirect_uri": redirect_uri,
        "scope": scope,
        "state": state,
    })
    return f"{_AUTHORIZE}?{params}"


def exchange_code(code: str, redirect_uri: str) -> str:
    """Trade an authorization code for a GitHub access token."""
    data = urllib.parse.urlencode({
        "client_id": os.environ["GITHUB_CLIENT_ID"],
        "client_secret": os.environ["GITHUB_CLIENT_SECRET"],
        "code": code,
        "redirect_uri": redirect_uri,
    }).encode()
    req = urllib.request.Request(_TOKEN, data=data, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        body = json.load(r)
    token = body.get("access_token")
    if not token:
        raise ValueError(f"github token exchange failed: {body.get('error', 'no token')}")
    return token


def primary_email(access_token: str) -> str | None:
    """Return the user's verified primary email, or None."""
    req = urllib.request.Request(_EMAILS, headers={
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "open-refinery",
    })
    with urllib.request.urlopen(req, timeout=10) as r:
        emails = json.load(r)
    return next((e["email"] for e in emails if e.get("primary") and e.get("verified")), None)
