"""Metrics — a read-model derived by aggregating the event store.

Everything here is computed from `events` and `work_items` via the ORM; nothing
new is stored. Scoped by ownership — developers see their own, platform/admin
see all.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func
from sqlmodel import Session, select

from .models import Event, WorkItem


def wip_by_stage(session: Session, owner_id: str | None = None) -> dict[str, int]:
    """Count of work items currently at each step (work in progress)."""
    stmt = select(WorkItem.current_stage, func.count())
    if owner_id:
        stmt = stmt.where(WorkItem.owner_id == owner_id)
    stmt = stmt.group_by(WorkItem.current_stage)
    return {stage: n for stage, n in session.exec(stmt)}


def event_counts(session: Session, owner_id: str | None = None) -> dict[str, int]:
    """Count of audit events by kind (transition / approval / attestation / …)."""
    stmt = select(Event.recipe, func.count())
    if owner_id:
        stmt = stmt.where(Event.owner == owner_id)
    stmt = stmt.group_by(Event.recipe)
    return {recipe: n for recipe, n in session.exec(stmt)}


def activity_by_actor(session: Session, owner_id: str | None = None) -> dict[str, int]:
    """Count of events per acting user — accountability at a glance."""
    stmt = select(Event.actor, func.count())
    if owner_id:
        stmt = stmt.where(Event.owner == owner_id)
    stmt = stmt.group_by(Event.actor)
    return {actor: n for actor, n in session.exec(stmt)}


def lead_times(session: Session, owner_id: str | None = None) -> dict[str, float]:
    """Lead time per work item = span between its first and last event."""
    stmt = select(Event.subject, func.min(Event.created_at), func.max(Event.created_at))
    stmt = stmt.where(Event.subject.is_not(None))
    if owner_id:
        stmt = stmt.where(Event.owner == owner_id)
    stmt = stmt.group_by(Event.subject)
    rows = list(session.exec(stmt))
    spans = [
        (datetime.fromisoformat(mx) - datetime.fromisoformat(mn)).total_seconds()
        for _subject, mn, mx in rows if mx > mn
    ]
    avg = sum(spans) / len(spans) if spans else 0.0
    return {"items": len(rows), "avg_lead_seconds": round(avg, 3)}


def summary(session: Session, owner_id: str | None = None) -> dict:
    """Bundle the read-model for a dashboard in one call."""
    return {
        "wip_by_stage": wip_by_stage(session, owner_id),
        "event_counts": event_counts(session, owner_id),
        "activity_by_actor": activity_by_actor(session, owner_id),
        "lead_times": lead_times(session, owner_id),
    }
