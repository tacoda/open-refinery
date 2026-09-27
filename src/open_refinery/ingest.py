"""Repo surfaces — what a repository says about how work is done there.

`charter(repo)` reads a repository's actual surfaces via a **reader** (default:
GitHub, using a connected integration's credential):

- **charter** ← `.agents/` docs (headings / bullet lines)
- **harness** ← the repo's agent config: `AGENTS.md`
- **code**    ← structural signals (tests present, CI workflow present)

Those two are the default because they are tool-neutral. **Any agent is
supported**: a repo whose rules live in `.claude/`, `.cursorrules`,
`.github/copilot-instructions.md` or anywhere else sets `charter_paths`, and
`AGENT_PRESETS` turns that into a pick rather than research.

The reader is injectable, so extraction is fully testable offline; the live
GitHub path is best-effort and returns nothing on any error rather than failing
the call.
"""

from __future__ import annotations

import base64

from sqlmodel import Session, select

from .models import Repository


def _norm(text: str) -> str:
    return " ".join(text.lower().split())


def _extract(markdown: str, *, cap: int = 40) -> list[str]:
    """Pull claim-like lines from markdown: headings and bullets, deduped."""
    out, seen = [], set()
    for raw in markdown.splitlines():
        line = raw.strip()
        if line.startswith("#"):
            line = line.lstrip("#").strip()
        elif line[:2] in ("- ", "* "):
            line = line[2:].strip()
        else:
            continue
        if len(line) < 4 or _norm(line) in seen:
            continue
        seen.add(_norm(line))
        out.append(line)
        if len(out) >= cap:
            break
    return out


# --- readers ---------------------------------------------------------------

def _host(git_url: str) -> str:
    for h in ("github.com", "gitlab.com"):
        if h in git_url:
            return h
    return ""


def _parse_repo(git_url: str) -> tuple[str, str] | None:
    """owner, repo from a GitHub/GitLab git URL (ssh or https)."""
    u = git_url.strip()
    host = _host(u)
    if not host:
        return None
    tail = u.split(host, 1)[1].lstrip(":/")
    tail = tail[:-4] if tail.endswith(".git") else tail
    parts = tail.split("/")
    return (parts[0], parts[1]) if len(parts) >= 2 else None


# root entries → code-surface signals
_CODE_SIGNALS = {
    "tests": "Has a tests directory", "test": "Has a tests directory",
    ".github": "Has CI configuration (GitHub Actions)",
    ".gitlab-ci.yml": "Has CI configuration (GitLab CI)",
    "Dockerfile": "Has a Dockerfile", "Makefile": "Has a Makefile",
    "docs": "Has a docs directory", ".pre-commit-config.yaml": "Has pre-commit hooks",
}


# The default, and only the default: `.agents/` and `AGENTS.md`. Tool-neutral,
# because the charter belongs to the repository rather than to whichever agent
# reads it this year.
DEFAULT_CHARTER_DIRS = (".agents",)
DEFAULT_CHARTER_FILES = ("AGENTS.md",)

# Any agent is supported — a repo that keeps its rules elsewhere overrides the
# default with `Repository.charter_paths`. These presets exist so that override
# is a pick rather than an afternoon of research, and adding one is a line here.
AGENT_PRESETS: dict[str, tuple[str, ...]] = {
    "agents":   (".agents", "AGENTS.md"),               # the default, named
    "claude":   (".claude", "CLAUDE.md"),
    "cursor":   (".cursor/rules", ".cursorrules"),
    "copilot":  (".github/copilot-instructions.md",),
    "windsurf": (".windsurf/rules", ".windsurfrules"),
    "aider":    ("CONVENTIONS.md",),
    "cline":    (".clinerules",),
    "gemini":   ("GEMINI.md",),
}


def preset(name: str) -> tuple[str, ...]:
    """The paths a known agent uses, for the repo settings picker."""
    return AGENT_PRESETS.get(name, ())


def charter_paths(repo=None) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """(directories, files) to read for this repo — its override, or the default.

    An override **replaces** the default rather than adding to it: a team that
    says where their charter lives means *there*, not there plus a guess.

    A configured path with no extension is a directory and one with an extension
    is a file, so a team writes `docs/agent` or `RULES.md` without having to say
    which kind it is.
    """
    configured = list(getattr(repo, "charter_paths", None) or ())
    if not configured:
        return DEFAULT_CHARTER_DIRS, DEFAULT_CHARTER_FILES
    dirs = tuple(p.rstrip("/") for p in configured if "." not in p.rsplit("/", 1)[-1])
    files = tuple(p for p in configured if "." in p.rsplit("/", 1)[-1])
    return dirs, files


def _surfaces_from(list_dir, read_text, repo=None) -> dict:
    """Extract the three surfaces given a dir-lister and a file-reader (per host)."""
    dirs, files = charter_paths(repo)
    charter: list[str] = []
    for folder in dirs:
        try:
            for entry in list_dir(folder):
                if entry.endswith(".md"):
                    charter += _extract(read_text(f"{folder}/{entry}"))
        except Exception:
            continue
    harness: list[str] = []
    for cfg in files:
        try:
            harness += _extract(read_text(cfg))
        except Exception:
            continue
    code: list[str] = []
    try:
        root = set(list_dir(""))
        for name, label in _CODE_SIGNALS.items():
            if name in root and label not in code:
                code.append(label)
    except Exception:
        pass
    return {"charter": charter, "harness": harness, "code": code}


def _github_surfaces(cred: dict, owner: str, name: str, repo=None) -> dict:
    from .integrations import _gh
    base = f"/repos/{owner}/{name}/contents"

    def ld(path):
        return [e.get("name", "") for e in _gh(cred, f"{base}/{path}" if path else base)]

    def rt(path):
        item = _gh(cred, f"{base}/{path}")
        return base64.b64decode(item.get("content", "")).decode("utf-8", "replace")

    return _surfaces_from(ld, rt, repo)


def _gitlab_surfaces(cred: dict, owner: str, name: str, repo=None) -> dict:
    import urllib.parse
    from .integrations import _gl
    pid = urllib.parse.quote(f"{owner}/{name}", safe="")

    def ld(path):
        q = f"/projects/{pid}/repository/tree?ref=main"
        if path:
            q += "&path=" + urllib.parse.quote(path)
        return [e.get("name", "") for e in _gl(cred, q)]

    def rt(path):
        fp = urllib.parse.quote(path, safe="")
        item = _gl(cred, f"/projects/{pid}/repository/files/{fp}?ref=main")
        return base64.b64decode(item.get("content", "")).decode("utf-8", "replace")

    return _surfaces_from(ld, rt, repo)


READERS = {"github": _github_surfaces, "gitlab": _gitlab_surfaces}


def _integration_for(session: Session, repo: Repository):
    """The repo's linked integration, else the owner's first integration matching
    the repo's host (GitHub/GitLab)."""
    from .integrations import get_integration, list_integrations
    if repo.integration_id:
        integ = get_integration(session, repo.integration_id)
        if integ is not None:
            return integ
    kind = "gitlab" if _host(repo.git_url) == "gitlab.com" else "github"
    return next((i for i in list_integrations(session, owner_id=repo.owner_id) if i.kind == kind), None)


def default_reader(session: Session, repo: Repository) -> dict:
    """Best-effort surface read via the repo's source integration (GitHub or GitLab)."""
    from .integrations import _credential
    try:
        integ = _integration_for(session, repo)
        parsed = _parse_repo(repo.git_url)
        surfaces = READERS.get(integ.kind) if integ else None
        if integ is None or parsed is None or surfaces is None:
            return {}
        owner, name = parsed
        return surfaces(_credential(session, integ.id), owner, name, repo)
    except Exception:
        return {}  # ingest is best-effort — never fail the request on a read error


# --- pipeline --------------------------------------------------------------

def charter(session: Session, repo_id: str, *, reader=None) -> dict:
    """The repository's own instructions, for the harness to be handed.

    Returns the three surfaces as text. It used to turn them into `Claim` rows
    and score "coverage", which nobody acted on; what the surfaces are actually
    for is telling the agent the house style — deepagents `memory=` and
    `skills=` (see PLAN-3.0 §9.1).
    """
    repo = session.get(Repository, repo_id)
    if repo is None:
        raise ValueError(f"unknown repository: {repo_id!r}")
    surfaces = (reader or default_reader)(session, repo)
    return {"repo_id": repo_id,
            "charter": surfaces.get("charter", []),
            "harness": surfaces.get("harness", []),
            "code": surfaces.get("code", [])}
