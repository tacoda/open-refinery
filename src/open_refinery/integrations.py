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

# Connector catalog — the single source of truth for the UI and the wizard:
# each kind's display label, its capabilities, and the credential fields to ask
# for. Capabilities: source (list_repos) · tracker (list_issues) · workflow
# (discover the tool's columns/statuses, for process-from-columns).
# (Docs/notify connectors — Confluence, Slack, Notion — are informational and
# come later; today we connect code hosts and issue trackers.)
CONNECTORS: dict[str, dict] = {
    "github":        {"label": "GitHub",        "caps": ["source"],
                      "fields": ["token"]},
    "gitlab":        {"label": "GitLab",        "caps": ["source"],
                      "fields": ["token"]},
    "github-issues": {"label": "GitHub Issues", "caps": ["tracker", "workflow"],
                      "fields": ["token", "repo"]},
    "jira":          {"label": "Jira",          "caps": ["tracker", "workflow"],
                      "fields": ["site", "email", "token"]},
    "linear":        {"label": "Linear",        "caps": ["tracker", "workflow"],
                      "fields": ["token"]},
}
KINDS = tuple(CONNECTORS)
SOURCE_KINDS = tuple(k for k, c in CONNECTORS.items() if "source" in c["caps"])
TRACKER_KINDS = tuple(k for k, c in CONNECTORS.items() if "tracker" in c["caps"])
WORKFLOW_KINDS = tuple(k for k, c in CONNECTORS.items() if "workflow" in c["caps"])


def connectors() -> list[dict]:
    """Catalog for the UI/wizard: kind + label + capabilities + credential fields."""
    return [{"kind": k, **v} for k, v in CONNECTORS.items()]


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


# --- GitHub Issues (tracker + workflow) -----------------------------------
# Reuses the GitHub token. `repo` (owner/name) scopes to one repo's issues and
# lets us discover its status-labels as columns; without it, assigned issues.

def ghi_list_issues(cred):
    repo = cred.get("repo")
    path = (f"/repos/{repo}/issues?state=all&per_page=50" if repo
            else "/issues?filter=assigned&state=all&per_page=50")
    return [{"key": f"#{i['number']}", "title": i["title"], "url": i["html_url"],
             "state": "closed" if i["state"] == "closed" else "open"}
            for i in _gh(cred, path) if "pull_request" not in i]  # skip PRs


def ghi_workflow(cred):
    """A repo's `status:`-prefixed labels are its columns; else issue open/closed."""
    repo = cred.get("repo")
    if repo:
        cols = [l["name"].split(":", 1)[1].strip()
                for l in _gh(cred, f"/repos/{repo}/labels?per_page=100")
                if l["name"].lower().startswith("status:")]
        if cols:
            return cols
    return ["open", "closed"]


# --- workflow discovery for the existing trackers -------------------------

def jira_workflow(cred):
    seen, out = set(), []
    for s in _jira(cred, "/rest/api/3/status"):
        name = s.get("name")
        if name and name not in seen:
            seen.add(name)
            out.append(name)
    return out


def linear_workflow(cred):
    q = "{ workflowStates(first: 50) { nodes { name position } } }"
    nodes = _linear(cred, q)["data"]["workflowStates"]["nodes"]
    return [n["name"] for n in sorted(nodes, key=lambda n: n["position"])]


ADAPTERS = {
    "github": {"verify": github_verify, "list_repos": github_list_repos},
    "gitlab": {"verify": gitlab_verify, "list_repos": gitlab_list_repos},
    "github-issues": {"verify": github_verify, "list_issues": ghi_list_issues,
                      "workflow": ghi_workflow},
    "linear": {"verify": linear_verify, "list_issues": linear_list_issues,
               "workflow": linear_workflow},
    "jira":   {"verify": jira_verify, "list_issues": jira_list_issues,
               "workflow": jira_workflow},
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


def list_workflow(session: Session, integ_id: str) -> list[str]:
    """The tracker's ordered columns/statuses — the stages a process can adopt."""
    return _adapter_call(session, integ_id, "workflow")
