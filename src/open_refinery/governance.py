"""Governance landscape — the admin's read view of what's defined where.

Summarizes the configured authority ladder, the rule set grouped by **layer**
(author role rank, the platform→developer axis), and **what overrides what**:
strict rules that shadow a lower-layer rule with the opposite effect. This is
the observability payoff over roles + the layer graph.

ponytail: override detection treats rules as conflicting when their (action,
resource) overlap (equal or a "*" wildcard) and effects differ; a strict
higher-rank rule is the winner. Drift/violation signal needs enforcement-outcome
logging — a later slice; reported as an empty list for now.
"""

from __future__ import annotations

from sqlmodel import Session, func, select

from .analysis import analyze
from .models import Policy, User
from .policies import list_policies
from .users import list_roles, role_rank


def _overlap(a: str, b: str) -> bool:
    return a == "*" or b == "*" or a == b


def landscape(session: Session) -> dict:
    roles = list_roles(session)
    counts = dict(session.exec(select(User.role, func.count()).group_by(User.role)).all())

    rules = [p for p in list_policies(session) if p.kind == "rule"]
    author_role = {u.id: u.role for u in session.exec(select(User))}
    rank_of = {p.id: role_rank(session, author_role.get(p.owner_id, "")) for p in rules}

    def brief(p: Policy) -> dict:
        return {"id": p.id, "effect": p.effect, "role": p.role, "action": p.action,
                "resource": p.resource, "strict": p.strict,
                "author_role": author_role.get(p.owner_id, ""), "rank": rank_of[p.id]}

    # group rules by layer (rank), highest first
    layers: dict[int, list] = {}
    for p in rules:
        layers.setdefault(rank_of[p.id], []).append(brief(p))
    layered = [{"rank": r, "rules": layers[r]} for r in sorted(layers, reverse=True)]

    # what overrides what: a strict rule shadowing a lower-rank, opposite-effect rule
    overrides = []
    for win in rules:
        if not win.strict:
            continue
        for lose in rules:
            if win is lose or win.effect == lose.effect:
                continue
            if rank_of[win.id] > rank_of[lose.id] \
                    and _overlap(win.action, lose.action) and _overlap(win.resource, lose.resource):
                overrides.append({"winner": brief(win), "shadowed": brief(lose)})

    return {
        "roles": [{"name": r.name, "rank": r.rank, "users": int(counts.get(r.name, 0))} for r in roles],
        "layers": layered,
        "overrides": overrides,
        "violations": analyze(session)["findings"],  # dead/contradiction/redundant/injection
    }
