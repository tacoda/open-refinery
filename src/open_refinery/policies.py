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
                  kind: str = "rule", content: str = "") -> Policy:
    if effect not in EFFECTS:
        raise ValueError(f"unknown effect: {effect!r} (expected {EFFECTS})")
    if kind not in POLICY_KINDS:
        raise ValueError(f"unknown policy kind: {kind!r} (expected {POLICY_KINDS})")
    if session.get(User, owner_id) is None:
        raise ValueError(f"unknown owner: {owner_id!r}")
    if strict is None:
        strict = strict_default(session)  # admin-configured default (off unless set)
    policy = Policy(effect=effect, role=role, action=action, resource=resource,
                    strict=strict, kind=kind, content=content, owner_id=owner_id)
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


def decide(policies: list[Policy], role: str, action: str, resource: str) -> bool:
    """Allow unless a matching rule denies (deny-overrides; default allow).

    Only `rule` policies gate. A **strict** rule cannot be overridden by a
    lower/other layer: if any matching rule is strict, the strict rules decide
    alone (still deny-overrides among them). ponytail: strictness is the current
    override lock; the full factory→harness→charter layer graph lands later.
    """
    matches = [p for p in policies if p.kind == "rule"
               and _match(p.role, role) and _match(p.action, action) and _match(p.resource, resource)]
    strict = [p for p in matches if p.strict]
    pool = strict or matches
    return not any(p.effect == "deny" for p in pool)


def enforce(session: Session, role: str, action: str, resource: str) -> None:
    """Raise PolicyDenied if the current policy set denies the action."""
    if not decide(list_policies(session), role, action, resource):
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
