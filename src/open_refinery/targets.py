"""Targets, routing, and quotas — the Platform layer's outbound governance.

A **Target** is where work runs: a model, an MCP server, or a backend API
(credentials encrypted at rest). A **Route** maps a process (optionally a step)
to a target with a priority, so work is directed to the right target. A **Quota**
caps usage of a target and is enforced before a call.
"""

from __future__ import annotations

import json

from sqlmodel import Session, select

from .crypto import decrypt, encrypt
from .models import Quota, Route, Target, User

KINDS = ("model", "mcp", "api")


class QuotaExceeded(Exception):
    """Raised when consuming would push a target's usage past its quota."""


# --- targets --------------------------------------------------------------

def create_target(session: Session, name: str, kind: str, endpoint: str, owner_id: str,
                  *, credential: dict | None = None, output_schema: dict | None = None,
                  region: str = "", compliance: list | None = None, unit_cost: int = 0) -> Target:
    if kind not in KINDS:
        raise ValueError(f"unknown target kind: {kind!r} (expected {KINDS})")
    if session.get(User, owner_id) is None:
        raise ValueError(f"unknown owner: {owner_id!r}")
    secret = encrypt(json.dumps(credential)) if credential else ""
    target = Target(name=name, kind=kind, endpoint=endpoint, owner_id=owner_id, secret=secret,
                    output_schema=output_schema or {}, region=region,
                    compliance=compliance or [], unit_cost=unit_cost)
    session.add(target)
    session.commit()
    session.refresh(target)
    return target


def get_target(session: Session, target_id: str) -> Target | None:
    return session.get(Target, target_id)


def list_targets(session: Session, *, owner_id: str | None = None) -> list[Target]:
    stmt = select(Target)
    if owner_id is not None:
        stmt = stmt.where(Target.owner_id == owner_id)
    return list(session.exec(stmt.order_by(Target.created_at.desc())))


def delete_target(session: Session, target_id: str) -> None:
    target = session.get(Target, target_id)
    if target is not None:
        session.delete(target)
        session.commit()


def set_target_credential(session: Session, target_id: str, credential: dict) -> Target:
    """Replace a target's stored credential (e.g. after an OAuth handshake)."""
    target = session.get(Target, target_id)
    if target is None:
        raise ValueError(f"unknown target: {target_id!r}")
    target.secret = encrypt(json.dumps(credential)) if credential else ""
    session.add(target)
    session.commit()
    session.refresh(target)
    return target


def target_credential(session: Session, target_id: str) -> dict:
    """Decrypt a target's credential ({} when none) — for the executor/caller."""
    target = session.get(Target, target_id)
    if target is None:
        raise ValueError(f"unknown target: {target_id!r}")
    return json.loads(decrypt(target.secret)) if target.secret else {}


# --- routing --------------------------------------------------------------

def create_route(session: Session, process_id: str, target_id: str, owner_id: str,
                 *, step: str | None = None, priority: int = 0) -> Route:
    if session.get(Target, target_id) is None:
        raise ValueError(f"unknown target: {target_id!r}")
    if session.get(User, owner_id) is None:
        raise ValueError(f"unknown owner: {owner_id!r}")
    route = Route(process_id=process_id, target_id=target_id, owner_id=owner_id,
                  step=step, priority=priority)
    session.add(route)
    session.commit()
    session.refresh(route)
    return route


def list_routes(session: Session, *, owner_id: str | None = None) -> list[Route]:
    stmt = select(Route)
    if owner_id is not None:
        stmt = stmt.where(Route.owner_id == owner_id)
    return list(session.exec(stmt.order_by(Route.priority.desc())))


def delete_route(session: Session, route_id: str) -> None:
    route = session.get(Route, route_id)
    if route is not None:
        session.delete(route)
        session.commit()


ROUTING_POLICY_KEY = "routing.policy"  # admin setting; JSON RoutingPolicy


def routing_policy(session: Session) -> dict:
    """Org-wide routing inputs: {require_region, require_compliance:[...],
    prefer:'priority'|'cost'}. Blank/missing → no constraint, priority order."""
    from .settings import get_setting
    raw = get_setting(session, ROUTING_POLICY_KEY)
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return {}


def _passes(target: Target, policy: dict) -> bool:
    region = policy.get("require_region") or ""
    if region and target.region != region:
        return False
    required = policy.get("require_compliance") or []
    return set(required) <= set(target.compliance or [])


def resolve_targets(session: Session, process_id: str, step: str | None = None) -> list[Target]:
    """Targets for a process/step, best first — for routing with failover.

    Ordered by priority desc, step-specific routes before process-wide ones at
    equal priority. The org **routing policy** then filters candidates that fail a
    required region / compliance tag, and (when `prefer='cost'`) orders survivors
    cheapest-first while keeping priority as the primary key.
    """
    routes = session.exec(select(Route).where(Route.process_id == process_id)).all()
    candidates = [r for r in routes if r.step is None or r.step == step]
    candidates.sort(key=lambda r: (r.priority, r.step is not None), reverse=True)
    pairs = [(r, session.get(Target, r.target_id)) for r in candidates]
    pairs = [(r, t) for r, t in pairs if t is not None]

    policy = routing_policy(session)
    pairs = [(r, t) for r, t in pairs if _passes(t, policy)]  # compliance/region gate
    if policy.get("prefer") == "cost":  # cheapest first, priority still dominant
        pairs.sort(key=lambda rt: (-rt[0].priority, rt[1].unit_cost))
    return [t for _, t in pairs]


def resolve_target(session: Session, process_id: str, step: str | None = None) -> Target | None:
    """The single best target for a process/step (highest-priority match)."""
    targets = resolve_targets(session, process_id, step)
    return targets[0] if targets else None


# --- quotas ---------------------------------------------------------------

def create_quota(session: Session, target_id: str, limit: int, owner_id: str,
                 *, window_seconds: int = 0) -> Quota:
    if session.get(Target, target_id) is None:
        raise ValueError(f"unknown target: {target_id!r}")
    if session.get(User, owner_id) is None:
        raise ValueError(f"unknown owner: {owner_id!r}")
    quota = Quota(target_id=target_id, limit=limit, owner_id=owner_id, window_seconds=window_seconds)
    session.add(quota)
    session.commit()
    session.refresh(quota)
    return quota


def list_quotas(session: Session, *, owner_id: str | None = None) -> list[Quota]:
    stmt = select(Quota)
    if owner_id is not None:
        stmt = stmt.where(Quota.owner_id == owner_id)
    return list(session.exec(stmt.order_by(Quota.created_at.desc())))


def _elapsed_seconds(started_iso: str, now_iso_str: str) -> float:
    from datetime import datetime
    return (datetime.fromisoformat(now_iso_str) - datetime.fromisoformat(started_iso)).total_seconds()


def consume_quota(session: Session, target_id: str, units: int = 1) -> None:
    """Enforce and record usage against every quota on a target.

    For windowed quotas (`window_seconds > 0`), usage resets once the rolling
    window has elapsed — giving per-minute/hour rate caps. Raises `QuotaExceeded`
    before consuming if any quota would be exceeded, so a blocked call consumes
    nothing.
    """
    from .models import now_iso
    now = now_iso()
    quotas = list(session.exec(select(Quota).where(Quota.target_id == target_id)))
    for q in quotas:  # roll the window before checking
        if q.window_seconds:
            if not q.window_started_at or _elapsed_seconds(q.window_started_at, now) >= q.window_seconds:
                q.used = 0
                q.window_started_at = now
    for q in quotas:
        if q.used + units > q.limit:
            raise QuotaExceeded(
                f"target {target_id!r} quota exhausted ({q.used}/{q.limit}, +{units})")
    for q in quotas:
        q.used += units
        session.add(q)
    session.commit()
