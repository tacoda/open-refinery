"""Debt audits & health — run an audit per area, score it, say what to try next.

Three areas, each scored 0–100 from signals the platform already computes:

- **factory**  — this service's rule config: dead/contradiction/redundant rules
                 (from governance analysis).
- **harness**  — the skill/command/agent artifacts: prompt-injection findings.
- **charter**  — the repos' stated governance: coverage + imitation surfaces
                 (from repo coverage/drift).

`audit(area)` returns the live picture; `run_audit(area, actor)` persists an
`Audit` row so health is trackable over time and reportable. Insights are the
"what to try next" — concrete, ordered by impact.
"""

from __future__ import annotations

from sqlmodel import Session, select

from .analysis import analyze
from .models import Audit, Repository, User
from .repo_governance import coverage

AREAS = ("factory", "harness", "charter")

# per-finding health cost by finding type (points off 100)
_COST = {"contradiction": 15, "dead": 8, "redundant": 3, "prompt_injection": 20}


def _clamp(n: int) -> int:
    return max(0, min(100, n))


def _factory(session: Session) -> dict:
    findings = [f for f in analyze(session)["findings"]
                if f["type"] in ("contradiction", "dead", "redundant")]
    score = _clamp(100 - sum(_COST[f["type"]] for f in findings))
    insights = []
    n_dead = sum(1 for f in findings if f["type"] == "dead")
    n_con = sum(1 for f in findings if f["type"] == "contradiction")
    n_red = sum(1 for f in findings if f["type"] == "redundant")
    if n_con:
        insights.append(f"Reconcile {n_con} contradicting rule(s) — make one strict or remove one.")
    if n_dead:
        insights.append(f"Remove or re-layer {n_dead} dead rule(s) shadowed by a strict rule.")
    if n_red:
        insights.append(f"Drop {n_red} redundant rule(s) already covered by a broader rule.")
    return {"area": "factory", "score": score, "findings": findings, "insights": insights}


def _harness(session: Session) -> dict:
    findings = [f for f in analyze(session)["findings"] if f["type"] == "prompt_injection"]
    score = _clamp(100 - sum(_COST["prompt_injection"] for _ in findings))
    insights = ([f"Quarantine/review {len(findings)} artifact(s) matching an injection pattern."]
                if findings else [])
    return {"area": "harness", "score": score, "findings": findings, "insights": insights}


def _charter(session: Session) -> dict:
    repos = list(session.exec(select(Repository)))
    findings: list[dict] = []
    scores: list[int] = []
    imitation = 0
    for r in repos:
        cov = coverage(session, r.id)
        if cov["total"] == 0:
            continue
        scores.append(cov["score"])
        imitation += cov["imitation"]
        for s in cov["imitation_surfaces"]:
            findings.append({"type": "imitation", "severity": "high", "repo": r.name, **s})
    score = round(sum(scores) / len(scores)) if scores else 100
    insights = []
    if imitation:
        insights.append(f"Close {imitation} imitation surface(s): add a backing instruction + gate.")
    if not scores:
        insights.append("No repo claims yet — seed charter/harness/code claims to measure coverage.")
    return {"area": "charter", "score": score, "findings": findings, "insights": insights}


_AUDITORS = {"factory": _factory, "harness": _harness, "charter": _charter}


def audit(session: Session, area: str) -> dict:
    if area not in _AUDITORS:
        raise ValueError(f"unknown area: {area!r} (expected {AREAS})")
    return _AUDITORS[area](session)


def run_audit(session: Session, area: str, actor_id: str) -> list[Audit]:
    """Run one area (or all) and persist the result(s)."""
    if session.get(User, actor_id) is None:
        raise ValueError(f"unknown actor: {actor_id!r}")
    areas = AREAS if area == "all" else (area,)
    rows = []
    for a in areas:
        res = audit(session, a)
        row = Audit(area=a, score=res["score"], findings=res["findings"],
                    insights=res["insights"], ran_by=actor_id)
        session.add(row)
        rows.append(row)
    session.commit()
    for row in rows:
        session.refresh(row)
    return rows


def list_audits(session: Session, *, area: str | None = None, limit: int = 50) -> list[Audit]:
    stmt = select(Audit)
    if area is not None:
        stmt = stmt.where(Audit.area == area)
    return list(session.exec(stmt.order_by(Audit.created_at.desc()).limit(limit)))


def health(session: Session) -> dict:
    """Live health across all areas — for the dashboard header, no persistence."""
    return {a: audit(session, a) for a in AREAS}
