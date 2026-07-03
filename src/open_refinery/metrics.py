"""Metrics — a read-model derived by aggregating the event store.

Everything here is computed from `events` and `work_items`; nothing new is
stored. The point of the "open" factory: make finding the numbers easy. Scoped
by ownership — developers see their own, platform/admin see all.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime


def _scope(column: str, owner_id: str | None) -> tuple[str, list]:
    return (f" WHERE {column} = ?", [owner_id]) if owner_id else ("", [])


def wip_by_stage(conn: sqlite3.Connection, owner_id: str | None = None) -> dict[str, int]:
    """Count of work items currently at each step (work in progress)."""
    where, params = _scope("owner_id", owner_id)
    rows = conn.execute(
        f"SELECT current_stage, COUNT(*) n FROM work_items{where} GROUP BY current_stage",
        params,
    )
    return {r["current_stage"]: r["n"] for r in rows}


def event_counts(conn: sqlite3.Connection, owner_id: str | None = None) -> dict[str, int]:
    """Count of audit events by kind (transition / approval / attestation / …)."""
    where, params = _scope("owner", owner_id)
    rows = conn.execute(
        f"SELECT recipe, COUNT(*) n FROM events{where} GROUP BY recipe", params
    )
    return {r["recipe"]: r["n"] for r in rows}


def activity_by_actor(conn: sqlite3.Connection, owner_id: str | None = None) -> dict[str, int]:
    """Count of events per acting user — accountability at a glance."""
    where, params = _scope("owner", owner_id)
    rows = conn.execute(
        f"SELECT actor, COUNT(*) n FROM events{where} GROUP BY actor", params
    )
    return {r["actor"]: r["n"] for r in rows}


def lead_times(conn: sqlite3.Connection, owner_id: str | None = None) -> dict[str, float]:
    """Lead time per work item = span between its first and last event."""
    where, params = _scope("owner", owner_id)
    clause = where or " WHERE 1=1"
    rows = conn.execute(
        f"SELECT subject, MIN(created_at) mn, MAX(created_at) mx FROM events"
        f"{clause} AND subject IS NOT NULL GROUP BY subject",
        params,
    ).fetchall()
    spans = [
        (datetime.fromisoformat(r["mx"]) - datetime.fromisoformat(r["mn"])).total_seconds()
        for r in rows
        if r["mx"] > r["mn"]
    ]
    avg = sum(spans) / len(spans) if spans else 0.0
    return {"items": len(rows), "avg_lead_seconds": round(avg, 3)}


def summary(conn: sqlite3.Connection, owner_id: str | None = None) -> dict:
    """Bundle the read-model for a dashboard in one call."""
    return {
        "wip_by_stage": wip_by_stage(conn, owner_id),
        "event_counts": event_counts(conn, owner_id),
        "activity_by_actor": activity_by_actor(conn, owner_id),
        "lead_times": lead_times(conn, owner_id),
    }
