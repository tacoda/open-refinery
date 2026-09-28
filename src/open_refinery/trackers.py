"""Trackers — where tickets come from.

The loosest of the seams before this file: `integrations.ADAPTERS` was a dict of
dicts, so "does this connector list issues?" was a key lookup and a new tracker
meant remembering which keys to add. It is a protocol now, and a tracker either
answers the three questions or it does not compile.

- **`verify`** — who does this credential belong to? (so a stored key is legible)
- **`issues`** — what work is waiting?
- **`workflow`** — what columns does this board have? (a process can adopt them)

`workflow` is optional, because some trackers have no columns worth importing.
Everything else is required, which is the point of a protocol over a dict.
"""

from __future__ import annotations

import base64
import json
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class Issue:
    """One piece of waiting work, however the tracker spells it."""

    key: str
    title: str
    url: str = ""
    state: str = ""
    body: str = ""


@runtime_checkable
class Tracker(Protocol):
    name: str

    def verify(self, cred: dict) -> dict: ...
    def issues(self, cred: dict) -> list[Issue]: ...


def _get(url: str, headers: dict, data: bytes | None = None):
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.load(r)


# --- GitHub Issues ----------------------------------------------------------

class GitHubIssues:
    name = "github-issues"

    def _api(self, cred, path):
        return _get("https://api.github.com" + path, {
            "Authorization": f"Bearer {cred['token']}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "open-refinery"})

    def verify(self, cred):
        return {"account": self._api(cred, "/user")["login"]}

    def issues(self, cred):
        repo = cred.get("repo")
        path = (f"/repos/{repo}/issues?state=open&per_page=50" if repo
                else "/issues?filter=assigned&state=open&per_page=50")
        return [Issue(key=f"#{i['number']}", title=i["title"], url=i["html_url"],
                      state=i["state"], body=i.get("body") or "")
                for i in self._api(cred, path) if "pull_request" not in i]

    def workflow(self, cred):
        """A repo's `status:` labels are its columns; else open/closed."""
        repo = cred.get("repo")
        if repo:
            columns = [l["name"].split(":", 1)[1].strip()
                       for l in self._api(cred, f"/repos/{repo}/labels?per_page=100")
                       if l["name"].lower().startswith("status:")]
            if columns:
                return columns
        return ["open", "closed"]


# --- GitLab Issues ----------------------------------------------------------

class GitLabIssues:
    name = "gitlab-issues"

    def _api(self, cred, path):
        base = (cred.get("base_url") or "https://gitlab.com").rstrip("/")
        return _get(f"{base}/api/v4{path}",
                    {"Authorization": f"Bearer {cred['token']}"})

    def verify(self, cred):
        return {"account": self._api(cred, "/user")["username"]}

    def issues(self, cred):
        project = cred.get("repo")
        path = (f"/projects/{urllib.parse.quote(project, safe='')}/issues?state=opened"
                if project else "/issues?scope=assigned_to_me&state=opened")
        return [Issue(key=f"#{i['iid']}", title=i["title"], url=i["web_url"],
                      state=i["state"], body=i.get("description") or "")
                for i in self._api(cred, path)]

    def workflow(self, cred):
        project = cred.get("repo")
        if not project:
            return ["opened", "closed"]
        pid = urllib.parse.quote(project, safe="")
        labels = self._api(cred, f"/projects/{pid}/labels?per_page=100")
        columns = [l["name"].split("::", 1)[1] for l in labels if "::" in l["name"]]
        return columns or ["opened", "closed"]


# --- Jira -------------------------------------------------------------------

class Jira:
    name = "jira"

    def _api(self, cred, path):
        auth = base64.b64encode(f"{cred['email']}:{cred['token']}".encode()).decode()
        return _get(f"https://{cred['site']}{path}",
                    {"Authorization": f"Basic {auth}", "Accept": "application/json"})

    def verify(self, cred):
        return {"account": self._api(cred, "/rest/api/3/myself")["displayName"]}

    def issues(self, cred):
        jql = cred.get("jql") or "assignee=currentUser() AND resolution=Unresolved"
        data = self._api(cred, "/rest/api/3/search?jql="
                         f"{urllib.parse.quote(jql)}&maxResults=50")
        return [Issue(key=i["key"], title=i["fields"]["summary"],
                      url=f"https://{cred['site']}/browse/{i['key']}",
                      state=i["fields"]["status"]["name"])
                for i in data.get("issues", [])]

    def workflow(self, cred):
        seen, out = set(), []
        for status in self._api(cred, "/rest/api/3/status"):
            name = status.get("name")
            if name and name not in seen:
                seen.add(name)
                out.append(name)
        return out


# --- Linear -----------------------------------------------------------------

class Linear:
    name = "linear"

    def _query(self, cred, query):
        return _get("https://api.linear.app/graphql",
                    {"Authorization": cred["token"],
                     "Content-Type": "application/json"},
                    json.dumps({"query": query}).encode())

    def verify(self, cred):
        return {"account": self._query(cred, "{ viewer { name } }")["data"]["viewer"]["name"]}

    def issues(self, cred):
        q = ("{ issues(first: 50, filter: {state: {type: {neq: \"completed\"}}}) "
             "{ nodes { identifier title url description state { name } } } }")
        nodes = self._query(cred, q)["data"]["issues"]["nodes"]
        return [Issue(key=n["identifier"], title=n["title"], url=n["url"],
                      state=n["state"]["name"], body=n.get("description") or "")
                for n in nodes]

    def workflow(self, cred):
        q = "{ workflowStates(first: 50) { nodes { name position } } }"
        nodes = self._query(cred, q)["data"]["workflowStates"]["nodes"]
        return [n["name"] for n in sorted(nodes, key=lambda n: n["position"])]


# --- Shortcut ---------------------------------------------------------------

class Shortcut:
    name = "shortcut"

    def _api(self, cred, path, data=None):
        body = json.dumps(data).encode() if data is not None else None
        headers = {"Shortcut-Token": cred["token"], "Content-Type": "application/json"}
        return _get("https://api.app.shortcut.com/api/v3" + path, headers, body)

    def verify(self, cred):
        return {"account": self._api(cred, "/member")["mention_name"]}

    def issues(self, cred):
        me = self._api(cred, "/member")["id"]
        found = self._api(cred, "/search/stories?query="
                          + urllib.parse.quote(f"owner:{me} !is:done"))
        return [Issue(key=f"sc-{s['id']}", title=s["name"],
                      url=s.get("app_url", ""), state=str(s.get("workflow_state_id", "")),
                      body=s.get("description") or "")
                for s in found.get("data", [])]

    def workflow(self, cred):
        flows = self._api(cred, "/workflows")
        return [state["name"] for flow in flows for state in flow.get("states", [])]


TRACKERS: dict[str, Tracker] = {
    "github-issues": GitHubIssues(),
    "gitlab-issues": GitLabIssues(),
    "jira": Jira(),
    "linear": Linear(),
    "shortcut": Shortcut(),
}


def get(name: str) -> Tracker:
    tracker = TRACKERS.get(name)
    if tracker is None:
        raise LookupError(f"unknown tracker: {name!r} (have {', '.join(TRACKERS)})")
    return tracker


def has_workflow(name: str) -> bool:
    """Whether this tracker can hand over its columns for a process to adopt."""
    return hasattr(TRACKERS.get(name), "workflow")
