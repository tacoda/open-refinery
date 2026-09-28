"""Policy governance — org-wide allow/deny rules, and content filtering.

A `Policy` is a rule `(effect, applies_to, action, resource)`; `decide()` evaluates a
request against all policies with **deny-overrides** and a default of allow.
Policies are set by platform users and apply fleet-wide (single-tenant).

Content filtering asks **two** questions, not one. Locally — a tool call inside
a run — the question is "is this a credential", and only that. On **egress**,
where text leaves for a third party, it also asks "did we just publish somebody's
personal data". See `scan_content`.
"""

from __future__ import annotations

import re

from sqlmodel import Session, select

from .models import Policy, User
from .settings import get_setting

EFFECTS = ("allow", "deny")
# The governance layer graph: factory (org service) > harness (agent tooling) >
# charter (repo/project). Precedence resolves on **this axis alone**. It used to
# be a lattice of (author's role rank, layer), which made a rule's weight depend
# on who wrote it — role rank is ordering, not authority, and the rest of the
# product had already stopped treating it as authority.
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


_SNAP = ("kind", "effect", "applies_to", "action", "resource", "strict", "layer",
         "content", "namespace")


def _record_version(session: Session, policy: Policy, change: str, changed_by: str, note: str) -> None:
    from .models import PolicyVersion
    n = len(list(session.exec(select(PolicyVersion).where(PolicyVersion.policy_id == policy.id))))
    session.add(PolicyVersion(policy_id=policy.id, version=n + 1, change=change,
                              changed_by=changed_by, note=note,
                              **{k: getattr(policy, k) for k in _SNAP}))
    session.commit()


def create_policy(session: Session, effect: str, owner_id: str, *, applies_to: str = "*",
                  action: str = "*", resource: str = "*", strict: bool | None = None,
                  kind: str = "rule", content: str = "", namespace: str = "",
                  pack: str = "", layer: str = "charter", note: str = "") -> Policy:
    """`applies_to` is `*` or a permission the actor must hold — never a role
    name. A role is a preset, copied once and never read again, so scoping a
    live rule to one judged people by a label that had stopped being true."""
    from .authority import PERMISSIONS

    if effect not in EFFECTS:
        raise ValueError(f"unknown effect: {effect!r} (expected {EFFECTS})")
    if applies_to != "*" and applies_to not in PERMISSIONS:
        raise ValueError(
            f"applies_to must be '*' or a permission: {applies_to!r} "
            f"(known: {', '.join(sorted(PERMISSIONS))})")
    if kind not in POLICY_KINDS:
        raise ValueError(f"unknown policy kind: {kind!r} (expected {POLICY_KINDS})")
    if layer not in LAYERS:
        raise ValueError(f"unknown layer: {layer!r} (expected {LAYERS})")
    if session.get(User, owner_id) is None:
        raise ValueError(f"unknown owner: {owner_id!r}")
    if strict is None:
        strict = strict_default(session)  # admin-configured default (off unless set)
    policy = Policy(effect=effect, applies_to=applies_to, action=action, resource=resource,
                    strict=strict, kind=kind, content=content, namespace=namespace,
                    pack=pack, layer=layer, owner_id=owner_id)
    session.add(policy)
    session.commit()
    session.refresh(policy)
    _record_version(session, policy, "created", owner_id, note)  # versioned history
    return policy


def list_policies(session: Session) -> list[Policy]:
    """All policies — governance is fleet-wide, not owner-scoped."""
    return list(session.exec(select(Policy).order_by(Policy.created_at.desc())))


def delete_policy(session: Session, policy_id: str, changed_by: str | None = None,
                  note: str = "") -> None:
    policy = session.get(Policy, policy_id)
    if policy is not None:
        _record_version(session, policy, "deleted", changed_by, note)  # tombstone version
        session.delete(policy)
        session.commit()


def list_policy_versions(session: Session, *, policy_id: str | None = None):
    """The policy change-log, newest first (optionally for one policy)."""
    from .models import PolicyVersion
    stmt = select(PolicyVersion)
    if policy_id is not None:
        stmt = stmt.where(PolicyVersion.policy_id == policy_id)
    return list(session.exec(stmt.order_by(PolicyVersion.created_at.desc())))


def policies_in_effect_at(session: Session, when: str) -> list[dict]:
    """Reconstruct the rule set in effect at an ISO timestamp: each policy whose
    'created' version is at/before `when` and not 'deleted' by then."""
    from .models import PolicyVersion
    versions = list(session.exec(select(PolicyVersion)
                                 .where(PolicyVersion.created_at <= when)
                                 .order_by(PolicyVersion.created_at)))
    live: dict[str, dict] = {}
    for v in versions:
        if v.change == "deleted":
            live.pop(v.policy_id, None)
        else:
            live[v.policy_id] = {"policy_id": v.policy_id, "version": v.version,
                                 **{k: getattr(v, k) for k in _SNAP}}
    return list(live.values())


def _ns_match(policy_ns: str, request_ns: str) -> bool:
    """A policy scopes to a namespace: blank policy_ns is global (gates any
    request); a namespaced policy gates only requests in that namespace."""
    return policy_ns == "" or policy_ns == request_ns


def decide(policies: list[Policy], permissions, action: str, resource: str,
           *, default_allow: bool = True, namespace: str = "") -> bool:
    """Decide whether an action is permitted by the rule set.

    Only `rule` policies gate. **Who it applies to** is `applies_to`: `*` for
    anyone, or a permission in `permissions` — the set the actor actually holds,
    rather than the name of the preset they were created from.

    **Layer graph:** precedence resolves on the artifact axis alone
    (factory > harness > charter); a **strict** rule locks the decision at the
    highest layer that locked (ties deny-override).

    **Namespace:** a namespaced policy gates only requests in that namespace; a
    blank-namespace policy is global. So a per-namespace whitelist is a set of
    namespaced `allow` rules under strict/default-deny mode.

    `default_allow=True` (audit mode): allow unless a matching rule denies.
    `default_allow=False` (**whitelist / default-deny**): deny unless a matching
    rule explicitly allows (and none in the deciding pool denies). No matching
    rule at all → the default.
    """
    held = set(permissions or ())
    key = lambda p: layer_rank(p.layer)
    matches = [p for p in policies if p.kind == "rule"
               and (p.applies_to == "*" or p.applies_to in held)
               and _match(p.action, action) and _match(p.resource, resource)
               and _ns_match(p.namespace, namespace)]
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


def enforce(session: Session, user: User, action: str, resource: str, *,
            audit=None, subject: str | None = None,
            namespace: str = "", intent: str = "") -> None:
    """Proactively gate an action: raise `PolicyDenied` if not permitted, and
    **record the refusal in the audit log** (when an audit sink is given).

    Generic over the action boundary — the same gate covers transitions and the
    tool/command/host-egress checks a harness makes *before acting*. `namespace` scopes to per-namespace whitelists; `intent` (the
    declared purpose) is recorded on the refusal for verification/audit.

    Honors the org enforcement mode — `audit` (default-allow) or `strict`
    (whitelist / default-deny). The actor is judged by the **permissions they
    hold**, which is the set `authority.py` uses for every route.
    """
    actor_id = user.id
    allow_default = enforcement_mode(session) == "audit"
    if not decide(list_policies(session), user.permissions, action, resource,
                  default_allow=allow_default, namespace=namespace):
        reason = f"policy denies {action!r} on {resource!r}"
        if namespace:
            reason += f" in {namespace!r}"
        if audit is not None:  # every refused attempt is auditable
            from .provenance import Record
            audit.write(Record.of(recipe="denied", actor=actor_id, owner=actor_id,
                                  inputs={"action": action, "resource": resource,
                                          "namespace": namespace, "intent": intent,
                                          "mode": enforcement_mode(session)},
                                  output=reason, subject=subject))
        raise PolicyDenied(reason)


# --- content filtering ----------------------------------------------------

# "Sensitive" means two different things, and conflating them refused ordinary
# work. Until 3.0 one list was scanned over every tool call's arguments, so a
# `git commit --author="a@b.com"`, a `package.json`, a CODEOWNERS file or any
# 13-digit literal was refused with "Secrets do not leave this machine" — while
# nothing had left anything.

# A SECRET is wrong wherever it appears. No legitimate source file contains a
# live AWS key, and writing one into your own checkout is as much of a mistake
# as posting it to a pull request. These are scanned everywhere.
SECRET_FILTERS: list[tuple[str, re.Pattern]] = [
    ("aws-key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("bearer-token", re.compile(r"\b(?:gh[pousr]|glpat|sk|pypi)[-_][A-Za-z0-9_-]{16,}\b")),
    ("private-key", re.compile(r"-----BEGIN(?: [A-Z]+)? PRIVATE KEY-----")),
]

# PERSONAL data is only a problem when the text **leaves**. An email address in
# a CODEOWNERS file is the file doing its job; the same address in a pull
# request body on a public forge is an address you published. Scanned on egress
# only.
PERSONAL_FILTERS: list[tuple[str, re.Pattern]] = [
    ("email", re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")),
    # Candidates only — a digit run is not a card number. `_luhn` decides, which
    # is what keeps `const id = 1234567890123` from being called a credit card.
    ("credit-card", re.compile(r"(?<![\d-])(?:\d[ -]?){12,18}\d(?![\d-])")),
]

_LUHN_CHECKED = {"credit-card"}


def _luhn(digits: str) -> bool:
    """The check digit every card number carries. A random run of digits passes
    about one time in ten, which is the difference between a filter and noise."""
    if not 13 <= len(digits) <= 19 or not digits.isdigit():
        return False
    total, parity = 0, len(digits) % 2
    for i, ch in enumerate(digits):
        n = int(ch)
        if i % 2 == parity:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def _apply(text: str, filters, hits: list[str]) -> str:
    for kind, pattern in filters:
        if kind in _LUHN_CHECKED:
            def sub(m):
                if not _luhn(re.sub(r"[ -]", "", m.group(0))):
                    return m.group(0)          # a number, not a card
                if kind not in hits:
                    hits.append(kind)
                return f"[redacted:{kind}]"
            text = pattern.sub(sub, text)
            continue
        if pattern.search(text):
            if kind not in hits:
                hits.append(kind)
            text = pattern.sub(f"[redacted:{kind}]", text)
    return text


def scan_content(text: str, *, egress: bool = False) -> tuple[str, list[str]]:
    """Redact what should not be there; return (clean_text, kinds_hit).

    `egress=True` for text **leaving this machine** — a pull request body, a
    comment on a forge. That adds the personal-data filters on top of the
    secrets, because the question there is not only "is this a credential" but
    "did we just publish somebody's address".

    The default is the local case: secrets only. A run writes files in its own
    worktree all day, and scanning those for email addresses refuses the work
    rather than protecting anything.
    """
    hits: list[str] = []
    clean = _apply(text, SECRET_FILTERS, hits)
    if egress:
        clean = _apply(clean, PERSONAL_FILTERS, hits)
    return clean, hits
