"""Integrations — connections to external services (GitHub first).

A team connects a service in the UI by pasting a token; it is encrypted at rest
and used by a per-kind **adapter** to talk to the service (verify the token,
list repositories, …). Tokens are never returned by the API. GitLab, Jira, and
Linear adapters follow the same shape.
"""

from __future__ import annotations

import json
import sqlite3
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from .crypto import decrypt, encrypt
from .store import register_schema

KINDS = ("github", "gitlab")  # source hosts; jira / linear arrive with work-item sync

register_schema(
    """
    CREATE TABLE IF NOT EXISTS integrations (
        id         TEXT PRIMARY KEY,
        kind       TEXT NOT NULL,
        account    TEXT NOT NULL,
        owner_id   TEXT NOT NULL REFERENCES users(id),
        secret     TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS ix_integrations_owner ON integrations(owner_id);
    -- short-lived state binding an OAuth connect flow back to the logged-in user
    CREATE TABLE IF NOT EXISTS connect_states (
        state      TEXT PRIMARY KEY,
        user_id    TEXT NOT NULL REFERENCES users(id),
        kind       TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    """
)


@dataclass(frozen=True)
class Integration:
    id: str
    kind: str
    account: str  # the connected external account (e.g. GitHub login)
    owner_id: str
    created_at: str


def _row(row: sqlite3.Row) -> Integration:
    return Integration(id=row["id"], kind=row["kind"], account=row["account"],
                       owner_id=row["owner_id"], created_at=row["created_at"])


# --- GitHub adapter -------------------------------------------------------

def _github_get(token: str, path: str):
    req = urllib.request.Request("https://api.github.com" + path, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "open-refinery",
    })
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.load(r)


def github_verify(token: str) -> dict:
    return {"account": _github_get(token, "/user")["login"]}


def github_list_repos(token: str) -> list[dict]:
    repos = _github_get(token, "/user/repos?per_page=100&sort=updated")
    return [{"name": r["name"], "full_name": r["full_name"],
             "ssh_url": r["ssh_url"], "private": r["private"]} for r in repos]


# --- GitLab adapter -------------------------------------------------------

def _gitlab_get(token: str, path: str):
    req = urllib.request.Request("https://gitlab.com/api/v4" + path,
                                 headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.load(r)


def gitlab_verify(token: str) -> dict:
    return {"account": _gitlab_get(token, "/user")["username"]}


def gitlab_list_repos(token: str) -> list[dict]:
    projects = _gitlab_get(token, "/projects?membership=true&per_page=100&order_by=updated_at")
    return [{"name": p["path"], "full_name": p["path_with_namespace"],
             "ssh_url": p["ssh_url_to_repo"], "private": p["visibility"] != "public"}
            for p in projects]


ADAPTERS = {
    "github": {"verify": github_verify, "list_repos": github_list_repos},
    "gitlab": {"verify": gitlab_verify, "list_repos": gitlab_list_repos},
}


# --- service layer --------------------------------------------------------

def create_integration(
    conn: sqlite3.Connection, kind: str, token: str, owner_id: str
) -> Integration:
    """Verify the token to label the integration by its account, then store it."""
    if kind not in KINDS:
        raise ValueError(f"unknown integration kind: {kind!r} (expected {KINDS})")
    if conn.execute("SELECT 1 FROM users WHERE id = ?", (owner_id,)).fetchone() is None:
        raise ValueError(f"unknown owner: {owner_id!r}")

    account = ADAPTERS[kind]["verify"](token)["account"]  # validates the token too
    integ = Integration(
        id=uuid.uuid4().hex, kind=kind, account=account, owner_id=owner_id,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    conn.execute(
        "INSERT INTO integrations (id, kind, account, owner_id, secret, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (integ.id, kind, account, owner_id, encrypt(token), integ.created_at),
    )
    conn.commit()
    return integ


def create_connect_state(conn: sqlite3.Connection, user_id: str, kind: str) -> str:
    """Mint a state token binding an OAuth connect flow to the logged-in user."""
    state = uuid.uuid4().hex
    conn.execute(
        "INSERT INTO connect_states (state, user_id, kind, created_at) VALUES (?, ?, ?, ?)",
        (state, user_id, kind, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    return state


def pop_connect_state(conn: sqlite3.Connection, state: str) -> str | None:
    """Return the user_id for a connect state and consume it (one-time use)."""
    row = conn.execute("SELECT user_id FROM connect_states WHERE state = ?", (state,)).fetchone()
    if row is None:
        return None
    conn.execute("DELETE FROM connect_states WHERE state = ?", (state,))
    conn.commit()
    return row["user_id"]


def get_integration(conn: sqlite3.Connection, integ_id: str) -> Integration | None:
    row = conn.execute("SELECT * FROM integrations WHERE id = ?", (integ_id,)).fetchone()
    return _row(row) if row else None


def list_integrations(
    conn: sqlite3.Connection, *, owner_id: str | None = None
) -> list[Integration]:
    if owner_id is None:
        rows = conn.execute("SELECT * FROM integrations ORDER BY created_at DESC")
    else:
        rows = conn.execute(
            "SELECT * FROM integrations WHERE owner_id = ? ORDER BY created_at DESC",
            (owner_id,),
        )
    return [_row(r) for r in rows]


def _token(conn: sqlite3.Connection, integ_id: str) -> str:
    row = conn.execute("SELECT secret FROM integrations WHERE id = ?", (integ_id,)).fetchone()
    if row is None:
        raise ValueError(f"unknown integration: {integ_id!r}")
    return decrypt(row["secret"])


def verify(conn: sqlite3.Connection, integ_id: str) -> dict:
    integ = get_integration(conn, integ_id)
    if integ is None:
        raise ValueError(f"unknown integration: {integ_id!r}")
    return ADAPTERS[integ.kind]["verify"](_token(conn, integ_id))


def list_remote_repos(conn: sqlite3.Connection, integ_id: str) -> list[dict]:
    integ = get_integration(conn, integ_id)
    if integ is None:
        raise ValueError(f"unknown integration: {integ_id!r}")
    return ADAPTERS[integ.kind]["list_repos"](_token(conn, integ_id))
