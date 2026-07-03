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

KINDS = ("github",)  # gitlab / jira / linear to follow

register_schema(
    """
    CREATE TABLE IF NOT EXISTS integrations (
        id         TEXT PRIMARY KEY,
        kind       TEXT NOT NULL,
        name       TEXT NOT NULL,
        owner_id   TEXT NOT NULL REFERENCES users(id),
        secret     TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS ix_integrations_owner ON integrations(owner_id);
    """
)


@dataclass(frozen=True)
class Integration:
    id: str
    kind: str
    name: str
    owner_id: str
    created_at: str


def _row(row: sqlite3.Row) -> Integration:
    return Integration(id=row["id"], kind=row["kind"], name=row["name"],
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


ADAPTERS = {
    "github": {"verify": github_verify, "list_repos": github_list_repos},
}


# --- service layer --------------------------------------------------------

def create_integration(
    conn: sqlite3.Connection, kind: str, name: str, token: str, owner_id: str
) -> Integration:
    if kind not in KINDS:
        raise ValueError(f"unknown integration kind: {kind!r} (expected {KINDS})")
    if conn.execute("SELECT 1 FROM users WHERE id = ?", (owner_id,)).fetchone() is None:
        raise ValueError(f"unknown owner: {owner_id!r}")

    integ = Integration(
        id=uuid.uuid4().hex, kind=kind, name=name, owner_id=owner_id,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    conn.execute(
        "INSERT INTO integrations (id, kind, name, owner_id, secret, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (integ.id, kind, name, owner_id, encrypt(token), integ.created_at),
    )
    conn.commit()
    return integ


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
