"""Policy governance — org-wide allow/deny rules, and content filtering.

A `Policy` is a rule `(effect, role, action, resource)`; `decide()` evaluates a
request against all policies with **deny-overrides** and a default of allow.
Policies are set by platform users and apply fleet-wide (single-tenant). Content
filtering redacts sensitive patterns from text crossing a target boundary.
"""

from __future__ import annotations

import re

from sqlmodel import Session, select

from .models import Policy, User
from .settings import get_setting
from .users import role_rank

EFFECTS = ("allow", "deny")
STRICT_DEFAULT_KEY = "policy.strict_default"  # admin setting; "true"/"false"


def strict_default(session: Session) -> bool:
    return (get_setting(session, STRICT_DEFAULT_KEY) or "false").lower() == "true"


class PolicyDenied(Exception):
    """Raised when a policy denies an action."""


def _match(pattern: str, value: str) -> bool:
    return pattern == "*" or pattern == value


POLICY_KINDS = ("rule", "skill", "command", "agent")  # what a governed harness artifact can be


def create_policy(session: Session, effect: str, owner_id: str, *, role: str = "*",
                  action: str = "*", resource: str = "*", strict: bool | None = None,
                  kind: str = "rule", content: str = "", namespace: str = "",
                  pack: str = "") -> Policy:
    if effect not in EFFECTS:
        raise ValueError(f"unknown effect: {effect!r} (expected {EFFECTS})")
    if kind not in POLICY_KINDS:
        raise ValueError(f"unknown policy kind: {kind!r} (expected {POLICY_KINDS})")
    if session.get(User, owner_id) is None:
        raise ValueError(f"unknown owner: {owner_id!r}")
    if strict is None:
        strict = strict_default(session)  # admin-configured default (off unless set)
    policy = Policy(effect=effect, role=role, action=action, resource=resource,
                    strict=strict, kind=kind, content=content, namespace=namespace,
                    pack=pack, owner_id=owner_id)
    session.add(policy)
    session.commit()
    session.refresh(policy)
    return policy


def list_policies(session: Session) -> list[Policy]:
    """All policies — governance is fleet-wide, not owner-scoped."""
    return list(session.exec(select(Policy).order_by(Policy.created_at.desc())))


def delete_policy(session: Session, policy_id: str) -> None:
    policy = session.get(Policy, policy_id)
    if policy is not None:
        session.delete(policy)
        session.commit()


def decide(policies: list[Policy], role: str, action: str, resource: str,
           *, rank_of=None) -> bool:
    """Allow unless a matching rule denies (deny-overrides; default allow).

    Only `rule` policies gate. **Layer graph:** a policy's layer is the rank of
    its author's role (`rank_of(policy)`). A **strict** rule locks the decision
    against *lower* layers — the highest-ranked strict rule wins, and lower rules
    can't override it; ties at that rank deny-override. With no strict rule,
    plain deny-overrides applies. `rank_of` defaults to a flat 0 (single layer),
    so callers that don't supply ranks keep the pre-graph behavior.
    """
    rank_of = rank_of or (lambda _p: 0)
    matches = [p for p in policies if p.kind == "rule"
               and _match(p.role, role) and _match(p.action, action) and _match(p.resource, resource)]
    strict = [p for p in matches if p.strict]
    if strict:
        top = max(rank_of(p) for p in strict)          # highest layer that locked
        pool = [p for p in strict if rank_of(p) == top]
        return not any(p.effect == "deny" for p in pool)
    return not any(p.effect == "deny" for p in matches)


def enforce(session: Session, role: str, action: str, resource: str) -> None:
    """Raise PolicyDenied if the current policy set denies the action.

    Resolves each rule's layer from its author's role rank (the platform→developer
    axis), so a higher-layer strict rule cannot be overridden by a lower one.
    """
    policies = list_policies(session)
    owners = {p.owner_id for p in policies}
    ranks = {oid: role_rank(session, u.role)
             for oid in owners if (u := session.get(User, oid)) is not None}
    rank_of = lambda p: ranks.get(p.owner_id, 0)
    if not decide(policies, role, action, resource, rank_of=rank_of):
        raise PolicyDenied(f"policy denies {role!r} {action!r} on {resource!r}")


# --- content filtering ----------------------------------------------------

# ponytail: a starter rule set for secrets/PII. Extend via config when needed.
_FILTERS: list[tuple[str, re.Pattern]] = [
    ("email", re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")),
    ("credit-card", re.compile(r"\b(?:\d[ -]*?){13,16}\b")),
    ("aws-key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("bearer-token", re.compile(r"\b(?:gh[pousr]|glpat|sk|pypi)[-_][A-Za-z0-9_-]{16,}\b")),
]


def scan_content(text: str) -> tuple[str, list[str]]:
    """Redact known sensitive patterns; return (clean_text, kinds_hit)."""
    hits: list[str] = []
    clean = text
    for kind, pattern in _FILTERS:
        if pattern.search(clean):
            hits.append(kind)
            clean = pattern.sub(f"[redacted:{kind}]", clean)
    return clean, hits
