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
                  *, credential: dict | None = None, output_schema: dict | None = None) -> Target:
    if kind not in KINDS:
        raise ValueError(f"unknown target kind: {kind!r} (expected {KINDS})")
    if session.get(User, owner_id) is None:
        raise ValueError(f"unknown owner: {owner_id!r}")
    secret = encrypt(json.dumps(credential)) if credential else ""
    target = Target(name=name, kind=kind, endpoint=endpoint, owner_id=owner_id, secret=secret,
                    output_schema=output_schema or {})
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


def resolve_targets(session: Session, process_id: str, step: str | None = None) -> list[Target]:
    """Targets for a process/step, best first — for routing with failover.

    Ordered by priority desc, step-specific routes before process-wide ones at
    equal priority.
    """
    routes = session.exec(select(Route).where(Route.process_id == process_id)).all()
    candidates = [r for r in routes if r.step is None or r.step == step]
    candidates.sort(key=lambda r: (r.priority, r.step is not None), reverse=True)
    targets = [session.get(Target, r.target_id) for r in candidates]
    return [t for t in targets if t is not None]


def resolve_target(session: Session, process_id: str, step: str | None = None) -> Target | None:
    """The single best target for a process/step (highest-priority match)."""
    targets = resolve_targets(session, process_id, step)
    return targets[0] if targets else None


# --- quotas ---------------------------------------------------------------

def create_quota(session: Session, target_id: str, limit: int, owner_id: str) -> Quota:
    if session.get(Target, target_id) is None:
        raise ValueError(f"unknown target: {target_id!r}")
    if session.get(User, owner_id) is None:
        raise ValueError(f"unknown owner: {owner_id!r}")
    quota = Quota(target_id=target_id, limit=limit, owner_id=owner_id)
    session.add(quota)
    session.commit()
    session.refresh(quota)
    return quota


def list_quotas(session: Session, *, owner_id: str | None = None) -> list[Quota]:
    stmt = select(Quota)
    if owner_id is not None:
        stmt = stmt.where(Quota.owner_id == owner_id)
    return list(session.exec(stmt.order_by(Quota.created_at.desc())))


def consume_quota(session: Session, target_id: str, units: int = 1) -> None:
    """Enforce and record usage against every quota on a target.

    Raises `QuotaExceeded` before consuming if any quota would be exceeded, so a
    blocked call consumes nothing.
    """
    quotas = list(session.exec(select(Quota).where(Quota.target_id == target_id)))
    for q in quotas:
        if q.used + units > q.limit:
            raise QuotaExceeded(
                f"target {target_id!r} quota exhausted ({q.used}/{q.limit}, +{units})")
    for q in quotas:
        q.used += units
        session.add(q)
    session.commit()
