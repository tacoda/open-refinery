"""Repo-level drift & coverage.

Per repository, each governance **claim** sits on a surface — **charter**,
**harness**, or **code** — and is either backed by an instruction, a gate, both,
or neither. From that we compute:

- **coverage** — fraction of claims backed by *both* an instruction and a gate,
  overall and per surface, plus a 0–100 health score.
- **imitation surfaces** — claims with **no instruction and no gate**: they read
  as governed but nothing enforces them. Prime action targets.
- **drift** — across the three axes (charter↔harness, charter↔code, harness↔code),
  claims present on one surface but missing on the other.

Claims are authored/seeded today; auto-ingesting real `.claude/`, harness config,
and code signals is a follow-up connector.
"""

from __future__ import annotations

from itertools import combinations

from sqlmodel import Session, select

from .models import Claim, Repository

SURFACES = ("charter", "harness", "code")


def create_claim(session: Session, repo_id: str, surface: str, text: str, owner_id: str,
                 *, has_instruction: bool = False, has_gate: bool = False) -> Claim:
    if surface not in SURFACES:
        raise ValueError(f"unknown surface: {surface!r} (expected {SURFACES})")
    if session.get(Repository, repo_id) is None:
        raise ValueError(f"unknown repository: {repo_id!r}")
    claim = Claim(repo_id=repo_id, surface=surface, text=text, owner_id=owner_id,
                  has_instruction=has_instruction, has_gate=has_gate)
    session.add(claim)
    session.commit()
    session.refresh(claim)
    return claim


def list_claims(session: Session, repo_id: str) -> list[Claim]:
    return list(session.exec(select(Claim).where(Claim.repo_id == repo_id)
                             .order_by(Claim.surface, Claim.created_at)))


def delete_claim(session: Session, claim_id: str) -> None:
    claim = session.get(Claim, claim_id)
    if claim is not None:
        session.delete(claim)
        session.commit()


def _norm(text: str) -> str:
    return " ".join(text.lower().split())


def coverage(session: Session, repo_id: str) -> dict:
    """Coverage + imitation surfaces for a repo. Score is % of claims fully backed."""
    claims = list_claims(session, repo_id)
    total = len(claims)
    covered = [c for c in claims if c.has_instruction and c.has_gate]
    imitation = [c for c in claims if not c.has_instruction and not c.has_gate]
    partial = [c for c in claims if c not in covered and c not in imitation]

    per_surface = {}
    for s in SURFACES:
        sc = [c for c in claims if c.surface == s]
        per_surface[s] = {"total": len(sc),
                          "covered": sum(1 for c in sc if c.has_instruction and c.has_gate)}

    def brief(c: Claim) -> dict:
        return {"id": c.id, "surface": c.surface, "text": c.text,
                "has_instruction": c.has_instruction, "has_gate": c.has_gate}

    return {
        "total": total,
        "covered": len(covered),
        "partial": len(partial),
        "imitation": len(imitation),
        "score": 100 if total == 0 else round(len(covered) / total * 100),
        "per_surface": per_surface,
        "imitation_surfaces": [brief(c) for c in imitation],  # prime action targets
        "partial_gaps": [brief(c) for c in partial],
    }


def drift(session: Session, repo_id: str) -> list[dict]:
    """Claims present on one surface but missing on another, per axis."""
    claims = list_claims(session, repo_id)
    by_surface = {s: {_norm(c.text) for c in claims if c.surface == s} for s in SURFACES}
    texts = {_norm(c.text): c.text for c in claims}
    out = []
    for a, b in combinations(SURFACES, 2):
        only_a = sorted(texts[t] for t in by_surface[a] - by_surface[b])
        only_b = sorted(texts[t] for t in by_surface[b] - by_surface[a])
        if only_a or only_b:
            out.append({"axis": f"{a}↔{b}", "only_in": {a: only_a, b: only_b}})
    return out


def report(session: Session, repo_id: str) -> dict:
    if session.get(Repository, repo_id) is None:
        raise ValueError(f"unknown repository: {repo_id!r}")
    return {"repo_id": repo_id, "coverage": coverage(session, repo_id),
            "drift": drift(session, repo_id)}
