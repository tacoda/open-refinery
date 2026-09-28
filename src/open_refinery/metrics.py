"""Metrics — a read-model derived by aggregating what the factory did.

Everything here is computed from `runs`, `run_steps`, `work_items` and `events`
via the ORM; nothing new is stored. Scoped by ownership — developers see their
own, platform/admin see all.

Until 3.0 this aggregated the kanban: work items by the column somebody dragged
them into, and a "lead time" that was the span between a subject's first and
last audit event. Neither described the factory. What a team asks about is how
much shipped, how much of it landed, how long it took, and which stage keeps
having to be done twice — all of which is in `runs` and `run_steps`.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func
from sqlmodel import Session, select

from .models import Event, Run, RunStep, WorkItem

# A run that reached one of these is over. `Run.outcome` is set with the move.
OUTCOMES = ("landed", "closed", "failed")


def _runs(session: Session, owner_id: str | None) -> list[Run]:
    stmt = select(Run)
    if owner_id:
        stmt = stmt.where(Run.actor_id == owner_id)
    return list(session.exec(stmt))


def _seconds(start: str, end: str) -> float | None:
    try:
        return (datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds()
    except (TypeError, ValueError):
        return None


def _mean(values: list[float]) -> float:
    return round(sum(values) / len(values), 1) if values else 0.0


def wip_by_stage(session: Session, owner_id: str | None = None) -> dict[str, int]:
    """Count of work items at each stage — **derived from their runs**.

    It used to read `WorkItem.current_stage`, a column a person moved by hand on
    a board the factory ignored. Stages come from `work_items.STAGES`.
    """
    from .work_items import stages_for

    stmt = select(WorkItem)
    if owner_id:
        stmt = stmt.where(WorkItem.owner_id == owner_id)
    items = list(session.exec(stmt))
    counts: dict[str, int] = {}
    for stage in stages_for(session, items).values():
        counts[stage] = counts.get(stage, 0) + 1
    return counts


def delivery(session: Session, owner_id: str | None = None) -> dict:
    """How much shipped, how much of it landed, and how long it took.

    `landed_pct` is over *finished* runs, not all of them: counting a run that
    is still going as a failure to land would make the number sag whenever the
    factory is busy, which is exactly when nobody should be misreading it.

    Time to a pull request is measured to the step that opened one. Time to an
    outcome is measured to the run's last update, which for a finished run is
    the move that finished it — nothing touches a run afterwards.
    """
    runs = _runs(session, owner_id)
    finished = [r for r in runs if r.outcome]
    by_outcome = {name: sum(1 for r in finished if r.outcome == name) for name in OUTCOMES}
    landed = by_outcome["landed"]

    pr_steps = {}
    if runs:
        stmt = (select(RunStep)
                .where(RunStep.run_id.in_([r.id for r in runs]))
                .where(RunStep.action == "open_pull_request")
                .where(RunStep.outcome == "ok"))
        for s in session.exec(stmt):
            pr_steps.setdefault(s.run_id, s.finished_at or s.started_at)

    to_pr = [d for r in runs
             if (d := _seconds(r.created_at, pr_steps.get(r.id, ""))) is not None and d >= 0]
    to_outcome = [d for r in finished
                  if (d := _seconds(r.created_at, r.updated_at)) is not None and d >= 0]

    return {
        "runs": len(runs),
        "in_flight": len(runs) - len(finished),
        "held": sum(1 for r in runs if r.held and not r.outcome),
        **by_outcome,
        "finished": len(finished),
        "landed_pct": round(100 * landed / len(finished)) if finished else 0,
        "reached_a_pull_request": len(pr_steps),
        "avg_seconds_to_pull_request": _mean(to_pr),
        "avg_seconds_to_outcome": _mean(to_outcome),
    }


def stage_health(session: Session, owner_id: str | None = None) -> list[dict]:
    """Per stage: how often it ran, how often it had to be done again, what it
    cost. A stage that refuses on every repository is a fact about the workflow
    rather than about any one ticket.

    Ordered by the stages that go wrong most, because that is the row somebody
    opened this to find.
    """
    runs = _runs(session, owner_id)
    if not runs:
        return []
    rows: dict[str, dict] = {}
    for s in session.exec(select(RunStep).where(RunStep.run_id.in_([r.id for r in runs]))):
        row = rows.setdefault(s.stage, {"stage": s.stage, "attempts": 0, "ok": 0,
                                        "refused": 0, "error": 0, "blocked": 0,
                                        "skipped": 0, "units": 0, "retries": 0})
        row["attempts"] += 1
        if s.outcome in row:
            row[s.outcome] += 1
        row["units"] += s.units
        if s.attempt > 1:
            row["retries"] += 1
    for row in rows.values():
        bad = row["refused"] + row["error"]
        row["trouble_pct"] = round(100 * bad / row["attempts"]) if row["attempts"] else 0
    return sorted(rows.values(), key=lambda r: (-r["trouble_pct"], -r["attempts"]))


def event_counts(session: Session, owner_id: str | None = None) -> dict[str, int]:
    """Count of audit events by kind (run-stage / approval / denied / …)."""
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


def summary(session: Session, owner_id: str | None = None) -> dict:
    """Bundle the read-model for a dashboard in one call."""
    return {
        "delivery": delivery(session, owner_id),
        "wip_by_stage": wip_by_stage(session, owner_id),
        "stage_health": stage_health(session, owner_id),
        "event_counts": event_counts(session, owner_id),
        "activity_by_actor": activity_by_actor(session, owner_id),
    }
