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
# Artifact axis of the governance layer graph: factory (org service) > harness
# (agent tooling) > charter (repo/project). Precedence resolves on the lattice
# (author role rank, then layer).
LAYERS = ("factory", "harness", "charter")
LAYER_RANK = {"charter": 1, "harness": 2, "factory": 3}
STRICT_DEFAULT_KEY = "policy.strict_default"  # admin setting; "true"/"false"
ENFORCEMENT_KEY = "policy.enforcement"        # admin setting; "audit" | "strict"


def layer_rank(layer: str) -> int:
    return LAYER_RANK.get(layer, 0)


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
                  pack: str = "", layer: str = "charter") -> Policy:
    if effect not in EFFECTS:
        raise ValueError(f"unknown effect: {effect!r} (expected {EFFECTS})")
    if kind not in POLICY_KINDS:
        raise ValueError(f"unknown policy kind: {kind!r} (expected {POLICY_KINDS})")
    if layer not in LAYERS:
        raise ValueError(f"unknown layer: {layer!r} (expected {LAYERS})")
    if session.get(User, owner_id) is None:
        raise ValueError(f"unknown owner: {owner_id!r}")
    if strict is None:
        strict = strict_default(session)  # admin-configured default (off unless set)
    policy = Policy(effect=effect, role=role, action=action, resource=resource,
                    strict=strict, kind=kind, content=content, namespace=namespace,
                    pack=pack, layer=layer, owner_id=owner_id)
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
           *, rank_of=None, default_allow: bool = True) -> bool:
    """Decide whether an action is permitted by the rule set.

    Only `rule` policies gate. **Layer graph:** precedence resolves on the lattice
    of (author role rank, artifact layer) — role axis dominant, artifact axis
    (factory > harness > charter) as tiebreak; a **strict** rule locks the
    decision at the highest lattice point (ties deny-override).

    `default_allow=True` (audit mode): allow unless a matching rule denies.
    `default_allow=False` (**whitelist / default-deny**): deny unless a matching
    rule explicitly allows (and none in the deciding pool denies). No matching
    rule at all → the default.
    """
    rank_of = rank_of or (lambda _p: 0)
    key = lambda p: (rank_of(p), layer_rank(p.layer))
    matches = [p for p in policies if p.kind == "rule"
               and _match(p.role, role) and _match(p.action, action) and _match(p.resource, resource)]
    if not matches:
        return default_allow
    strict = [p for p in matches if p.strict]
    pool = matches
    if strict:
        top = max(key(p) for p in strict)              # highest lattice point that locked
        pool = [p for p in strict if key(p) == top]
    denied = any(p.effect == "deny" for p in pool)
    if default_allow:
        return not denied
    return not denied and any(p.effect == "allow" for p in pool)  # whitelist: needs an explicit allow


def enforcement_mode(session: Session) -> str:
    """Org enforcement mode: 'audit' (default-allow, opt-in deny) or 'strict'
    (whitelist / default-deny). Admin setting `policy.enforcement`."""
    mode = (get_setting(session, ENFORCEMENT_KEY) or "audit").lower()
    return "strict" if mode in ("strict", "whitelist", "deny") else "audit"


def enforce(session: Session, role: str, action: str, resource: str, *,
            audit=None, actor_id: str | None = None, subject: str | None = None) -> None:
    """Proactively gate an action: raise `PolicyDenied` if not permitted, and
    **record the refusal in the audit log** (when an audit sink is given).

    Honors the org enforcement mode — `audit` (default-allow) or `strict`
    (whitelist / default-deny). Resolves each rule's layer from its author's role
    rank, so a higher-layer strict rule can't be overridden by a lower one.
    """
    policies = list_policies(session)
    owners = {p.owner_id for p in policies}
    ranks = {oid: role_rank(session, u.role)
             for oid in owners if (u := session.get(User, oid)) is not None}
    rank_of = lambda p: ranks.get(p.owner_id, 0)
    allow_default = enforcement_mode(session) == "audit"
    if not decide(policies, role, action, resource, rank_of=rank_of, default_allow=allow_default):
        reason = f"policy denies {role!r} {action!r} on {resource!r}"
        if audit is not None:  # every refused attempt is auditable
            from .provenance import Record
            audit.write(Record.of(recipe="denied", actor=actor_id or role, owner=actor_id or role,
                                  inputs={"role": role, "action": action, "resource": resource,
                                          "mode": enforcement_mode(session)},
                                  output=reason, subject=subject))
        raise PolicyDenied(reason)


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
