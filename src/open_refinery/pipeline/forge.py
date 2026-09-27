"""Where a request for review goes, and how the factory hears back.

A driver answers four questions and nothing else: how to open a request, how to
read its state, what people said on it, and how to say something back. Adding
GitLab or Gitea is an entry in `FORGES`, not a change anywhere else — which is
the point of the seam.

**`local` is no forge at all.** The request is a markdown file in the
repository, and a merge is a merge. It needs no account and no token, it is the
shortest path to seeing the factory work end to end, and it is the proof the
seam is a seam rather than a rename.

Comments the factory wrote carry a marker, because it pushes with the operator's
credentials and *is* the request's author — telling its own comments from a
reviewer's by author would find none.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Protocol

MARKER = "<!-- open-refinery -->"

OPEN, MERGED, CLOSED = "open", "merged", "closed"


class ForgeError(RuntimeError):
    """The forge refused, or could not be reached."""


@dataclass(frozen=True)
class PullRequest:
    number: str
    url: str
    state: str = OPEN


@dataclass(frozen=True)
class Comment:
    author: str
    body: str
    ours: bool = False       # written by the factory, not by a person


class Forge(Protocol):
    """One place code goes to be reviewed."""

    name: str
    # Where the branch has to be before anyone can look at it. Empty means
    # nowhere: a repo with no forge has no remote, and the branch is already in
    # the checkout a reviewer will open.
    remote: str

    def open_pr(self, cred: dict, repo: str, *, branch: str, base: str,
                title: str, body: str) -> PullRequest: ...

    def pr_state(self, cred: dict, repo: str, number: str) -> PullRequest: ...

    def comments(self, cred: dict, repo: str, number: str) -> list[Comment]: ...

    def say(self, cred: dict, repo: str, number: str, text: str) -> None: ...


# --- helpers ---------------------------------------------------------------

def _request(url: str, headers: dict, *, data: dict | None = None,
             method: str = "GET") -> dict | list:
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            text = r.read().decode("utf-8", "replace")
            return json.loads(text) if text else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        raise ForgeError(f"{method} {url} → HTTP {exc.code}: {detail}") from None
    except urllib.error.URLError as exc:
        raise ForgeError(f"cannot reach {url}: {exc.reason}") from None


# --- GitHub ----------------------------------------------------------------

class GitHub:
    name = "github"
    remote = "origin"
    api = "https://api.github.com"

    def _headers(self, cred: dict) -> dict:
        return {"Authorization": f"Bearer {cred.get('token', '')}",
                "Accept": "application/vnd.github+json",
                "Content-Type": "application/json",
                "User-Agent": "open-refinery"}

    def open_pr(self, cred, repo, *, branch, base, title, body) -> PullRequest:
        data = _request(f"{self.api}/repos/{repo}/pulls", self._headers(cred),
                        data={"title": title, "body": body, "head": branch, "base": base},
                        method="POST")
        return PullRequest(number=str(data["number"]), url=data["html_url"])

    def pr_state(self, cred, repo, number) -> PullRequest:
        data = _request(f"{self.api}/repos/{repo}/pulls/{number}", self._headers(cred))
        # GitHub reports a merged request as `closed`, so the two have to be
        # told apart explicitly or every merge reads as an abandonment.
        state = MERGED if data.get("merged_at") else (
            CLOSED if data.get("state") == "closed" else OPEN)
        return PullRequest(number=str(number), url=data["html_url"], state=state)

    def comments(self, cred, repo, number) -> list[Comment]:
        rows = _request(f"{self.api}/repos/{repo}/issues/{number}/comments",
                        self._headers(cred))
        return [Comment(author=(c.get("user") or {}).get("login", ""),
                        body=c.get("body", ""),
                        ours=MARKER in (c.get("body") or ""))
                for c in rows]

    def say(self, cred, repo, number, text) -> None:
        _request(f"{self.api}/repos/{repo}/issues/{number}/comments",
                 self._headers(cred), data={"body": f"{MARKER}\n\n{text}"},
                 method="POST")


# --- GitLab ----------------------------------------------------------------

class GitLab:
    name = "gitlab"
    remote = "origin"
    api = "https://gitlab.com/api/v4"

    def _headers(self, cred: dict) -> dict:
        return {"Authorization": f"Bearer {cred.get('token', '')}",
                "Content-Type": "application/json"}

    def _project(self, repo: str) -> str:
        import urllib.parse
        return urllib.parse.quote(repo, safe="")

    def open_pr(self, cred, repo, *, branch, base, title, body) -> PullRequest:
        data = _request(f"{self.api}/projects/{self._project(repo)}/merge_requests",
                        self._headers(cred),
                        data={"source_branch": branch, "target_branch": base,
                              "title": title, "description": body},
                        method="POST")
        return PullRequest(number=str(data["iid"]), url=data["web_url"])

    def pr_state(self, cred, repo, number) -> PullRequest:
        data = _request(
            f"{self.api}/projects/{self._project(repo)}/merge_requests/{number}",
            self._headers(cred))
        state = {"merged": MERGED, "closed": CLOSED}.get(data.get("state", ""), OPEN)
        return PullRequest(number=str(number), url=data["web_url"], state=state)

    def comments(self, cred, repo, number) -> list[Comment]:
        rows = _request(
            f"{self.api}/projects/{self._project(repo)}/merge_requests/{number}/notes",
            self._headers(cred))
        return [Comment(author=(c.get("author") or {}).get("username", ""),
                        body=c.get("body", ""),
                        ours=MARKER in (c.get("body") or ""))
                for c in rows
                if not c.get("system")]      # skip GitLab's own activity notes

    def say(self, cred, repo, number, text) -> None:
        _request(f"{self.api}/projects/{self._project(repo)}/merge_requests/{number}/notes",
                 self._headers(cred), data={"body": f"{MARKER}\n\n{text}"},
                 method="POST")


# --- local: no forge at all -------------------------------------------------

class Local:
    """The request is a file in the repository.

    No account, no token, no network — which makes it the shortest path to
    seeing a run reach a pull request, and the thing that proves the seam is
    real rather than a rename of "GitHub".

    State lives beside the file: a reviewer merges the branch themselves, and
    `pr_state` reports what git says rather than what anybody claimed.
    """

    name = "local"
    remote = ""              # nothing to push to; the branch is already here

    DIR = ".open-refinery/requests"

    def _path(self, cred: dict, repo: str, number: str):
        from pathlib import Path
        root = Path(cred.get("workspace") or repo)
        return root / self.DIR / f"{number}.md"

    def open_pr(self, cred, repo, *, branch, base, title, body) -> PullRequest:
        from pathlib import Path
        root = Path(cred.get("workspace") or repo)
        folder = root / self.DIR
        folder.mkdir(parents=True, exist_ok=True)
        # The branch name is the id: unique per run, and it is what a reviewer
        # checks out.
        number = branch.replace("/", "-")
        path = folder / f"{number}.md"
        path.write_text(
            f"{MARKER}\n\n# {title}\n\n"
            f"- branch: `{branch}`\n- onto: `{base}`\n\n---\n\n{body}\n")
        return PullRequest(number=number, url=str(path))

    def pr_state(self, cred, repo, number) -> PullRequest:
        """Merged means git says the branch is an ancestor of the base — not
        that a file was ticked."""
        from pathlib import Path

        path = self._path(cred, repo, number)
        if not path.exists():
            return PullRequest(number=number, url=str(path), state=CLOSED)
        state = OPEN
        base, branch = cred.get("base", "main"), cred.get("branch", number)
        root = cred.get("workspace") or repo
        from .workspace import git
        merged = git(root, "merge-base", "--is-ancestor", branch, base, check=False)
        if merged.ok:
            state = MERGED
        return PullRequest(number=number, url=str(path), state=state)

    def comments(self, cred, repo, number) -> list[Comment]:
        """Anything appended under the `## Comments` heading."""
        path = self._path(cred, repo, number)
        if not path.exists():
            return []
        text = path.read_text()
        if "## Comments" not in text:
            return []
        tail = text.split("## Comments", 1)[1]
        return [Comment(author="local", body=block.strip(),
                        ours=MARKER in block)
                for block in tail.split("\n---\n") if block.strip()]

    def say(self, cred, repo, number, text) -> None:
        path = self._path(cred, repo, number)
        if not path.exists():
            raise ForgeError(f"no request at {path}")
        body = path.read_text()
        if "## Comments" not in body:
            body += "\n\n## Comments\n"
        path.write_text(f"{body}\n---\n{MARKER}\n\n{text}\n")


FORGES: dict[str, Forge] = {"github": GitHub(), "gitlab": GitLab(), "local": Local()}


def for_repo(git_url: str, configured: str = "") -> Forge:
    """The forge for this repository — what it configured, else its git URL.

    A repo that says nothing and has no recognisable host gets `local`, so the
    factory still works against a checkout with no account behind it.
    """
    if configured:
        driver = FORGES.get(configured)
        if driver is None:
            raise ForgeError(f"unknown forge: {configured!r} "
                             f"(have {', '.join(FORGES)})")
        return driver
    url = (git_url or "").lower()
    if "github.com" in url:
        return FORGES["github"]
    if "gitlab.com" in url:
        return FORGES["gitlab"]
    return FORGES["local"]


def slug(git_url: str) -> str:
    """`owner/name` from a git URL, which is what the forge APIs address."""
    url = (git_url or "").strip()
    for host in ("github.com", "gitlab.com"):
        if host in url:
            tail = url.split(host, 1)[1].lstrip(":/")
            return tail[:-4] if tail.endswith(".git") else tail
    return url
