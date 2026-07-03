"""Integrations — connections to external services.

A team connects a service in the UI; its **credential** (a small dict — a token,
or site/email/token for Jira) is encrypted at rest and used by a per-kind
**adapter**. Source hosts (GitHub, GitLab) list repositories; trackers (Jira,
Linear) list issues to sync as work items. Credentials are never returned.
"""

from __future__ import annotations

import base64
import json
import sqlite3
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from .crypto import decrypt, encrypt
from .store import register_schema

SOURCE_KINDS = ("github", "gitlab")   # list_repos
TRACKER_KINDS = ("jira", "linear")    # list_issues
KINDS = SOURCE_KINDS + TRACKER_KINDS

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


def _get_json(url: str, headers: dict, data: bytes | None = None):
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.load(r)


# --- GitHub (source) ------------------------------------------------------

def _gh(cred, path):
    return _get_json("https://api.github.com" + path, {
        "Authorization": f"Bearer {cred['token']}",
        "Accept": "application/vnd.github+json", "User-Agent": "open-refinery"})


def github_verify(cred): return {"account": _gh(cred, "/user")["login"]}


def github_list_repos(cred):
    return [{"name": r["name"], "full_name": r["full_name"], "ssh_url": r["ssh_url"],
             "private": r["private"]}
            for r in _gh(cred, "/user/repos?per_page=100&sort=updated")]


# --- GitLab (source) ------------------------------------------------------

def _gl(cred, path):
    return _get_json("https://gitlab.com/api/v4" + path,
                     {"Authorization": f"Bearer {cred['token']}"})


def gitlab_verify(cred): return {"account": _gl(cred, "/user")["username"]}


def gitlab_list_repos(cred):
    return [{"name": p["path"], "full_name": p["path_with_namespace"],
             "ssh_url": p["ssh_url_to_repo"], "private": p["visibility"] != "public"}
            for p in _gl(cred, "/projects?membership=true&per_page=100&order_by=updated_at")]


# --- Linear (tracker) -----------------------------------------------------

def _linear(cred, query):
    return _get_json("https://api.linear.app/graphql",
                     {"Authorization": cred["token"], "Content-Type": "application/json"},
                     json.dumps({"query": query}).encode())


def linear_verify(cred):
    return {"account": _linear(cred, "{ viewer { name } }")["data"]["viewer"]["name"]}


def linear_list_issues(cred):
    q = "{ issues(first: 50) { nodes { identifier title url state { name } } } }"
    nodes = _linear(cred, q)["data"]["issues"]["nodes"]
    return [{"key": n["identifier"], "title": n["title"], "url": n["url"],
             "state": n["state"]["name"]} for n in nodes]


# --- Jira (tracker) -------------------------------------------------------

def _jira(cred, path):
    auth = base64.b64encode(f"{cred['email']}:{cred['token']}".encode()).decode()
    return _get_json(f"https://{cred['site']}{path}",
                     {"Authorization": f"Basic {auth}", "Accept": "application/json"})


def jira_verify(cred):
    return {"account": _jira(cred, "/rest/api/3/myself")["displayName"]}


def jira_list_issues(cred):
    data = _jira(cred, "/rest/api/3/search?jql=assignee=currentUser()&maxResults=50")
    return [{"key": i["key"], "title": i["fields"]["summary"],
             "url": f"https://{cred['site']}/browse/{i['key']}",
             "state": i["fields"]["status"]["name"]} for i in data["issues"]]


ADAPTERS = {
    "github": {"verify": github_verify, "list_repos": github_list_repos},
    "gitlab": {"verify": gitlab_verify, "list_repos": gitlab_list_repos},
    "linear": {"verify": linear_verify, "list_issues": linear_list_issues},
    "jira":   {"verify": jira_verify, "list_issues": jira_list_issues},
}


# --- service layer --------------------------------------------------------

def create_integration(
    conn: sqlite3.Connection, kind: str, credential: dict, owner_id: str
) -> Integration:
    """Verify the credential (labelling by account), then store it encrypted."""
    if kind not in KINDS:
        raise ValueError(f"unknown integration kind: {kind!r} (expected {KINDS})")
    if conn.execute("SELECT 1 FROM users WHERE id = ?", (owner_id,)).fetchone() is None:
        raise ValueError(f"unknown owner: {owner_id!r}")

    account = ADAPTERS[kind]["verify"](credential)["account"]  # validates too
    integ = Integration(
        id=uuid.uuid4().hex, kind=kind, account=account, owner_id=owner_id,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    conn.execute(
        "INSERT INTO integrations (id, kind, account, owner_id, secret, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (integ.id, kind, account, owner_id, encrypt(json.dumps(credential)), integ.created_at),
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


def delete_integration(conn: sqlite3.Connection, integ_id: str) -> None:
    conn.execute("DELETE FROM integrations WHERE id = ?", (integ_id,))
    conn.commit()


def _credential(conn: sqlite3.Connection, integ_id: str) -> dict:
    row = conn.execute("SELECT secret FROM integrations WHERE id = ?", (integ_id,)).fetchone()
    if row is None:
        raise ValueError(f"unknown integration: {integ_id!r}")
    return json.loads(decrypt(row["secret"]))


def _adapter_call(conn: sqlite3.Connection, integ_id: str, op: str):
    integ = get_integration(conn, integ_id)
    if integ is None:
        raise ValueError(f"unknown integration: {integ_id!r}")
    fn = ADAPTERS[integ.kind].get(op)
    if fn is None:
        raise ValueError(f"{integ.kind} does not support {op}")
    return fn(_credential(conn, integ_id))


def verify(conn: sqlite3.Connection, integ_id: str) -> dict:
    return _adapter_call(conn, integ_id, "verify")


def list_remote_repos(conn: sqlite3.Connection, integ_id: str) -> list[dict]:
    return _adapter_call(conn, integ_id, "list_repos")


def list_issues(conn: sqlite3.Connection, integ_id: str) -> list[dict]:
    return _adapter_call(conn, integ_id, "list_issues")
