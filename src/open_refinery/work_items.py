"""Work items — the tickets the factory works on.

A `WorkItem` belongs to a repository and is owned by a user. It is the durable
identity of a piece of work: a tracker issue synced in, or one named by hand.

**It has no state machine of its own.** Until 3.0 an item sat on a `Process` — a
second stage graph, with its own transitions, gates, checks and approval chain —
that a run completely ignored. A work item's stage is now *derived* from its
runs, so the board shows what the factory is actually doing rather than where
somebody last dragged a card.
"""

from __future__ import annotations

from sqlmodel import Session, select

from .audit import AuditSink
from .integrations import TRACKER_KINDS, get_integration, list_issues
from .models import Repository, Run, User, WorkItem
from .provenance import Record


class UnknownWorkItem(KeyError):
    """Raised when a work item id does not exist."""


# What a work item's stage can be. Read off its newest run, because the run is
# the only thing that actually moves.
STAGES = ("open", "running", "waiting", "landed", "closed", "failed")


def create_work_item(session: Session, repo_id: str, title: str, owner_id: str,
                     *, external_ref: str | None = None) -> WorkItem:
    if session.get(Repository, repo_id) is None:
        raise ValueError(f"unknown repository: {repo_id!r}")
    if session.get(User, owner_id) is None:
        raise ValueError(f"unknown owner: {owner_id!r}")

    item = WorkItem(repo_id=repo_id, title=title, owner_id=owner_id,
                    external_ref=external_ref)
    session.add(item)
    session.commit()
    session.refresh(item)
    return item


def get_work_item(session: Session, item_id: str) -> WorkItem | None:
    return session.get(WorkItem, item_id)


def find_by_external_ref(session: Session, external_ref: str) -> WorkItem | None:
    return session.exec(select(WorkItem).where(WorkItem.external_ref == external_ref)).first()


def list_work_items(session: Session, *, owner_id: str | None = None,
                    repo_id: str | None = None) -> list[WorkItem]:
    stmt = select(WorkItem)
    if owner_id is not None:
        stmt = stmt.where(WorkItem.owner_id == owner_id)
    if repo_id is not None:
        stmt = stmt.where(WorkItem.repo_id == repo_id)
    return list(session.exec(stmt.order_by(WorkItem.created_at.desc())))


def stage_of(session: Session, item_id: str) -> str:
    """Where this item stands, read off its newest run.

    `open` until something runs; then the run says. A finished run's outcome
    (`landed` / `closed` / `failed`) wins over its stage, because an outcome is
    the last word.
    """
    run = session.exec(
        select(Run).where(Run.work_item_id == item_id)
        .order_by(Run.created_at.desc())).first()
    if run is None:
        return "open"
    if run.outcome:
        return run.outcome if run.outcome in STAGES else "closed"
    return "waiting" if run.stage == "waiting" else "running"


def stages_for(session: Session, items: list[WorkItem]) -> dict[str, str]:
    """`stage_of` for a whole list in one query — what the board needs."""
    ids = {i.id for i in items}
    if not ids:
        return {}
    newest: dict[str, Run] = {}
    for run in session.exec(select(Run).where(Run.work_item_id.in_(ids))
                            .order_by(Run.created_at)):
        newest[run.work_item_id] = run          # ascending, so the last one wins
    out = {}
    for item in items:
        run = newest.get(item.id)
        if run is None:
            out[item.id] = "open"
        elif run.outcome:
            out[item.id] = run.outcome if run.outcome in STAGES else "closed"
        else:
            out[item.id] = "waiting" if run.stage == "waiting" else "running"
    return out


def sync_tracker(session: Session, integ_id: str, repo_id: str,
                 actor_id: str, audit: AuditSink, *, autostart: bool | None = None) -> dict:
    """Import a tracker integration's issues as work items, deduped by external ref.

    `autostart` starts a run for each newly imported issue. It defaults to the
    integration's own setting, so a sync behaves the same way its webhooks do —
    one place to decide whether tickets from this tracker run by themselves.
    """
    integ = get_integration(session, integ_id)
    if integ is None:
        raise ValueError(f"unknown integration: {integ_id!r}")
    if integ.kind not in TRACKER_KINDS:
        raise ValueError(f"{integ.kind} is not a work-item tracker")
    if autostart is None:
        autostart = integ.autostart

    created, skipped, runs = 0, 0, []
    for issue in list_issues(session, integ_id):
        ref = f"{integ.kind}:{issue['key']}"
        if find_by_external_ref(session, ref):
            skipped += 1
            continue
        item = create_work_item(session, repo_id, issue["title"], actor_id,
                                external_ref=ref)
        audit.write(Record.of(
            recipe="sync", actor=actor_id, owner=actor_id,
            inputs={"integration": integ_id, "key": issue["key"]}, output=ref, subject=item.id,
        ))
        created += 1
        if autostart:
            run_id = _autostart(session, item, issue, integ, actor_id, audit)
            if run_id:
                runs.append(run_id)
    return {"created": created, "skipped": skipped, "runs": runs}


def _autostart(session: Session, item, issue: dict, integ, actor_id: str,
               audit: AuditSink) -> str | None:
    """Start a run for a freshly imported issue.

    The issue's text is the spec — quoted, never interpolated into a prompt.
    Whoever filed the ticket wrote it, and on a public tracker that is anybody.
    """
    from .pipeline import store as ps

    try:
        pipeline = ps.latest_pipeline(session, integ.intake_pipeline or "ship-a-ticket")
    except ps.UnknownPipeline:
        return None
    body = issue.get("body") or ""
    spec = f"{issue['title']}\n\n{body}" if body else issue["title"]
    run = ps.start_run(session, item.id, pipeline, item.repo_id, actor_id, spec=spec)
    audit.write(Record.of(
        recipe="run-started", actor=actor_id, owner=actor_id,
        inputs={"from": "sync", "pipeline": pipeline.name, "work_item": item.id},
        output=run.stage, subject=run.id))
    return run.id
