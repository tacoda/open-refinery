"""Ingest repo surfaces — populate `Claim`s from reality, not seeded text.

`ingest(repo)` reads a repository's actual surfaces via a **reader** (default:
GitHub, using a connected integration's credential) and turns stated behaviors
into `Claim`s:

- **charter** ← `.claude/` docs (headings / bullet lines)
- **harness** ← a harness/agent config file (`CLAUDE.md`, `AGENTS.md`)
- **code**    ← structural signals (tests present, CI workflow present)

Each new claim gets a heuristic backing read: `has_instruction` if it echoes an
authored policy/standard, `has_gate` if the org has any gated process. Re-ingest
is idempotent (dedupe by repo+surface+text). The reader is injectable, so the
extraction/dedup/backing pipeline is fully testable offline; the live GitHub
path is best-effort and returns nothing on any error rather than failing the call.
"""

from __future__ import annotations

import base64

from sqlmodel import Session, select

from .models import Policy, Process, Repository, Standard
from .repo_governance import create_claim, list_claims


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


def _instruction_blob(session: Session) -> str:
    parts = [p.content for p in session.exec(select(Policy)) if p.content]
    parts += [s.body for s in session.exec(select(Standard))]
    return _norm(" ".join(parts))


def _has_gate(session: Session) -> bool:
    # ponytail: org-wide "any gated process" — not per-repo; refine when repos link processes.
    return any(p.gates for p in session.exec(select(Process)))


def _backed_by_instruction(text: str, blob: str) -> bool:
    words = [w for w in _norm(text).split() if len(w) > 4]
    return bool(words) and any(w in blob for w in words)


# --- readers ---------------------------------------------------------------

def _parse_repo(git_url: str) -> tuple[str, str] | None:
    """owner, repo from a GitHub git URL (ssh or https)."""
    u = git_url.strip()
    if "github.com" not in u:
        return None
    tail = u.split("github.com", 1)[1].lstrip(":/")
    tail = tail[:-4] if tail.endswith(".git") else tail
    parts = tail.split("/")
    return (parts[0], parts[1]) if len(parts) >= 2 else None


def github_reader(session: Session, repo: Repository) -> dict:
    """Best-effort read of a repo's surfaces via a connected GitHub integration."""
    from .integrations import _credential, _gh, list_integrations
    try:
        integ = next((i for i in list_integrations(session, owner_id=repo.owner_id)
                      if i.kind == "github"), None)
        if integ is None:
            return {}
        cred = _credential(session, integ.id)
        parsed = _parse_repo(repo.git_url)
        if parsed is None:
            return {}
        owner, name = parsed

        def _text(path: str) -> str:
            item = _gh(cred, f"/repos/{owner}/{name}/contents/{path}")
            return base64.b64decode(item.get("content", "")).decode("utf-8", "replace")

        charter: list[str] = []
        try:
            for entry in _gh(cred, f"/repos/{owner}/{name}/contents/.claude"):
                if entry.get("name", "").endswith(".md"):
                    charter += _extract(_text(entry["path"]))
        except Exception:
            pass

        harness: list[str] = []
        for cfg in ("CLAUDE.md", "AGENTS.md"):
            try:
                harness += _extract(_text(cfg))
            except Exception:
                continue

        code: list[str] = []
        try:
            root = {e.get("name") for e in _gh(cred, f"/repos/{owner}/{name}/contents")}
            if "tests" in root or "test" in root:
                code.append("Has a tests directory")
            if ".github" in root:
                code.append("Has CI configuration")
        except Exception:
            pass

        return {"charter": charter, "harness": harness, "code": code}
    except Exception:
        return {}  # ingest is best-effort — never fail the request on a read error


# --- pipeline --------------------------------------------------------------

def ingest(session: Session, repo_id: str, actor_id: str, *, reader=None) -> dict:
    repo = session.get(Repository, repo_id)
    if repo is None:
        raise ValueError(f"unknown repository: {repo_id!r}")
    reader = reader or github_reader
    surfaces = reader(session, repo)

    existing = {(c.surface, _norm(c.text)) for c in list_claims(session, repo_id)}
    blob = _instruction_blob(session)
    gate = _has_gate(session)

    created = 0
    for surface, texts in surfaces.items():
        for text in texts:
            key = (surface, _norm(text))
            if key in existing:
                continue
            existing.add(key)
            create_claim(session, repo_id, surface, text, actor_id,
                         has_instruction=_backed_by_instruction(text, blob), has_gate=gate)
            created += 1

    return {"repo_id": repo_id, "created": created,
            "total_claims": len(list_claims(session, repo_id))}
