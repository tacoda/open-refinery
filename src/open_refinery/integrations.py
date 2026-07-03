"""Integrations — connections to external services.

A team connects a service in the UI; its **credential** (a dict — a token, or
site/email/token for Jira) is encrypted at rest and used by a per-kind
**adapter**. Source hosts (GitHub, GitLab) list repositories; trackers (Jira,
Linear) list issues to sync as work items. Credentials are never returned.
"""

from __future__ import annotations

import base64
import json
import urllib.request
import uuid

from sqlmodel import Session, select

from .crypto import decrypt, encrypt
from .models import ConnectState, Integration, User

SOURCE_KINDS = ("github", "gitlab")   # list_repos
TRACKER_KINDS = ("jira", "linear")    # list_issues
KINDS = SOURCE_KINDS + TRACKER_KINDS


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

def create_integration(session: Session, kind: str, credential: dict, owner_id: str) -> Integration:
    """Verify the credential (labelling by account), then store it encrypted."""
    if kind not in KINDS:
        raise ValueError(f"unknown integration kind: {kind!r} (expected {KINDS})")
    if session.get(User, owner_id) is None:
        raise ValueError(f"unknown owner: {owner_id!r}")

    account = ADAPTERS[kind]["verify"](credential)["account"]  # validates too
    integ = Integration(kind=kind, account=account, owner_id=owner_id,
                        secret=encrypt(json.dumps(credential)))
    session.add(integ)
    session.commit()
    session.refresh(integ)
    return integ


def create_connect_state(session: Session, user_id: str, kind: str) -> str:
    """Mint a state token binding an OAuth connect flow to the logged-in user."""
    row = ConnectState(state=uuid.uuid4().hex, user_id=user_id, kind=kind)
    session.add(row)
    session.commit()
    return row.state


def pop_connect_state(session: Session, state: str) -> str | None:
    """Return the user_id for a connect state and consume it (one-time use)."""
    row = session.get(ConnectState, state)
    if row is None:
        return None
    user_id = row.user_id
    session.delete(row)
    session.commit()
    return user_id


def get_integration(session: Session, integ_id: str) -> Integration | None:
    return session.get(Integration, integ_id)


def list_integrations(session: Session, *, owner_id: str | None = None) -> list[Integration]:
    stmt = select(Integration)
    if owner_id is not None:
        stmt = stmt.where(Integration.owner_id == owner_id)
    return list(session.exec(stmt.order_by(Integration.created_at.desc())))


def delete_integration(session: Session, integ_id: str) -> None:
    integ = session.get(Integration, integ_id)
    if integ is not None:
        session.delete(integ)
        session.commit()


def _credential(session: Session, integ_id: str) -> dict:
    integ = session.get(Integration, integ_id)
    if integ is None:
        raise ValueError(f"unknown integration: {integ_id!r}")
    return json.loads(decrypt(integ.secret))


def _adapter_call(session: Session, integ_id: str, op: str):
    integ = get_integration(session, integ_id)
    if integ is None:
        raise ValueError(f"unknown integration: {integ_id!r}")
    fn = ADAPTERS[integ.kind].get(op)
    if fn is None:
        raise ValueError(f"{integ.kind} does not support {op}")
    return fn(_credential(session, integ_id))


def verify(session: Session, integ_id: str) -> dict:
    return _adapter_call(session, integ_id, "verify")


def list_remote_repos(session: Session, integ_id: str) -> list[dict]:
    return _adapter_call(session, integ_id, "list_repos")


def list_issues(session: Session, integ_id: str) -> list[dict]:
    return _adapter_call(session, integ_id, "list_issues")
