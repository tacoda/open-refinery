"""Governance analysis — flag things that poison jobs.

Static analysis over the rule set + artifact content, surfaced per role level:

- **dead**     — a rule shadowed by a strict higher-layer opposite rule; it can
                 never take effect.
- **contradiction** — two same-layer rules, opposite effect, overlapping match;
                 the outcome is ambiguous (deny wins) — reconcile.
- **redundant** — a rule fully covered by a broader same-effect rule.
- **prompt_injection** — a skill/command/agent whose `content` matches a known
                 injection pattern; review before it reaches a harness.

Each finding carries the author layer (role + rank) so a viewer sees only
findings at or below their own layer. Drift (config vs. what's actually enforced
/ vs. code) is the next, repo-level slice.
"""

from __future__ import annotations

import re

from sqlmodel import Session, select

from .models import Policy, User
from .policies import layer_rank, list_policies
from .users import role_rank

SEVERITY = {"prompt_injection": "high", "contradiction": "high",
            "dead": "medium", "redundant": "low"}

# ponytail: a starter injection-pattern set; extend as harnesses surface more.
_INJECTION = [re.compile(p, re.I) for p in (
    r"ignore (all |the )?(previous|prior|above)\s+instructions",
    r"disregard\s+.{0,20}(instruction|rule|policy|guidance)",
    r"you are now\b",
    r"system prompt",
    r"reveal\s+.{0,20}(prompt|instruction|system|secret)",
    r"</?system>",
    r"override\s+.{0,20}(instruction|rule|policy)",
)]


def _overlap(a: str, b: str) -> bool:
    return a == "*" or b == "*" or a == b


def _covers(broad: Policy, narrow: Policy) -> bool:
    """broad's match space ⊇ narrow's, and they are not identical."""
    dims = (("role", broad.role, narrow.role), ("action", broad.action, narrow.action),
            ("resource", broad.resource, narrow.resource))
    if all(b == n for _, b, n in dims):
        return False  # identical, not "broader"
    return all(b == "*" or b == n for _, b, n in dims)


def analyze(session: Session, *, viewer_rank: int | None = None) -> dict:
    policies = list_policies(session)
    rules = [p for p in policies if p.kind == "rule"]
    author_role = {u.id: u.role for u in session.exec(select(User))}
    rank = {p.id: role_rank(session, author_role.get(p.owner_id, "")) for p in policies}

    key = lambda p: (rank[p.id], layer_rank(p.layer))  # lattice: role rank, then artifact layer

    def author(p: Policy) -> dict:
        return {"role": author_role.get(p.owner_id, ""), "rank": rank[p.id]}

    findings: list[dict] = []

    def add(kind: str, p: Policy, detail: str, insight: str) -> None:
        findings.append({"type": kind, "severity": SEVERITY[kind], "rule_id": p.id,
                         "author_role": author_role.get(p.owner_id, ""), "rank": rank[p.id],
                         "detail": detail, "insight": insight})

    # dead: shadowed by a strict higher-rank opposite rule
    for lose in rules:
        for win in rules:
            if win is lose or not win.strict or win.effect == lose.effect:
                continue
            if key(win) > key(lose) \
                    and _overlap(win.action, lose.action) and _overlap(win.resource, lose.resource):
                add("dead", lose,
                    f"shadowed by a strict {author(win)['role']} {win.layer} rule on {win.action}/{win.resource}",
                    "remove it, or raise its layer above the strict rule")
                break

    # contradiction: same lattice point (rank + layer), opposite effect, overlapping
    for i, a in enumerate(rules):
        for b in rules[i + 1:]:
            if a.effect != b.effect and key(a) == key(b) \
                    and _overlap(a.role, b.role) and _overlap(a.action, b.action) \
                    and _overlap(a.resource, b.resource):
                add("contradiction", a,
                    f"conflicts with a {author(b)['role']} {b.layer} rule on {b.action}/{b.resource} (deny wins)",
                    "reconcile the two rules or make one strict")

    # redundant: covered by a broader same-effect rule
    for narrow in rules:
        for broad in rules:
            if broad is narrow or broad.effect != narrow.effect:
                continue
            if _covers(broad, narrow) and rank[broad.id] >= rank[narrow.id]:
                add("redundant", narrow,
                    f"already covered by a broader {broad.effect} rule ({broad.action}/{broad.resource})",
                    "safe to remove")
                break

    # prompt injection in artifact content (skill/command/agent)
    for p in policies:
        if p.kind == "rule" or not p.content:
            continue
        for pat in _INJECTION:
            if pat.search(p.content):
                add("prompt_injection", p,
                    f"{p.kind} content matches injection pattern /{pat.pattern}/",
                    "review/quarantine before this reaches a harness")
                break

    if viewer_rank is not None:  # a viewer sees findings at or below their layer
        findings = [f for f in findings if f["rank"] <= viewer_rank]

    metrics: dict[str, int] = {}
    for f in findings:
        metrics[f["type"]] = metrics.get(f["type"], 0) + 1
    return {"findings": findings, "metrics": metrics, "total": len(findings)}
