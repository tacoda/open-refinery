"""Work items and the transition loop — the core of the factory.

A `WorkItem` belongs to a repository and a process, sits at one step, and is
owned by a user. Shipping work = transitioning it between steps; every
transition is a governed production (validate → oversight → apply → audit).
Tracker issues are synced in as work items.
"""

from __future__ import annotations

from sqlmodel import Session, select

from .attestations import AttestationFailed, AttestationMissing, attestations_for, unmet_checks
from .audit import AuditSink
from .integrations import TRACKER_KINDS, get_integration, list_issues
from .models import Process, Repository, User, WorkItem
from .oversight import requires_approval
from .policies import PolicyDenied
from .policies import enforce as enforce_policy
from .processes import get_process
from .provenance import Record
from .users import at_least


class InvalidTransition(Exception):
    """Raised when a move is not allowed by the item's process."""


class ApprovalRequired(Exception):
    """Raised when the process's oversight level requires a human approval first."""


class UnknownWorkItem(KeyError):
    """Raised when a work item id does not exist."""


def create_work_item(session: Session, repo_id: str, process_id: str, title: str,
                     owner_id: str, *, external_ref: str | None = None) -> WorkItem:
    if session.get(Repository, repo_id) is None:
        raise ValueError(f"unknown repository: {repo_id!r}")
    if session.get(User, owner_id) is None:
        raise ValueError(f"unknown owner: {owner_id!r}")
    process = session.get(Process, process_id)
    if process is None:
        raise ValueError(f"unknown process: {process_id!r}")

    item = WorkItem(repo_id=repo_id, process_id=process_id, title=title,
                    current_stage=process.initial, owner_id=owner_id, external_ref=external_ref)
    session.add(item)
    session.commit()
    _record_stage(session, item.id, process.initial, "initial", owner_id)
    session.refresh(item)
    return item


def _record_stage(session: Session, item_id: str, stage: str, kind: str,
                  actor_id: str | None, changes: dict | None = None) -> None:
    from .models import StageHistory
    session.add(StageHistory(work_item_id=item_id, stage=stage, kind=kind,
                             actor_id=actor_id, changes=changes or {}))
    session.commit()


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


def apply_transition(session: Session, item_id: str, to: str, actor_id: str,
                     audit: AuditSink, *, changes: dict | None = None) -> WorkItem:
    """Apply a move: validate the move + policy + required checks, then move + audit.

    Does NOT run the oversight approval gate — callers that reach here have already
    satisfied approval (the sync `transition` after its gate, or the approval queue
    after its chain completes).
    """
    item = get_work_item(session, item_id)
    if item is None:
        raise UnknownWorkItem(item_id)
    actor = session.get(User, actor_id)
    if actor is None:
        raise ValueError(f"unknown actor: {actor_id!r}")

    process = get_process(session, item.process_id)
    frm = item.current_stage
    if not process.can_transition(frm, to):
        raise InvalidTransition(f"{frm!r} -> {to!r} not allowed by process {process.name!r}")

    enforce_policy(session, actor.role, "transition", to,  # org-wide role policy (audits refusals)
                   audit=audit, actor_id=actor_id, subject=item_id)

    required = process.required_checks(to)
    if required:
        missing, failed = unmet_checks(attestations_for(session, item_id), required)
        if missing:
            raise AttestationMissing(f"entering {to!r} needs checks attested: {missing}")
        if failed:
            raise AttestationFailed(f"entering {to!r} blocked by failed checks: {failed}")

    item.current_stage = to
    session.add(item)
    session.commit()
    _record_stage(session, item_id, to, "transition", actor_id, changes)
    audit.write(Record.of(
        recipe="transition", actor=actor_id, owner=item.owner_id,
        inputs={"from": frm, "process": item.process_id, "repo": item.repo_id,
                "changes": changes or {}},
        output=to, subject=item_id,
    ))
    session.refresh(item)
    return item


def transition(session: Session, item_id: str, to: str, actor_id: str, audit: AuditSink,
               *, approver_id: str | None = None, changes: dict | None = None) -> WorkItem:
    """Synchronous move: enforce the oversight approval gate inline, then apply.

    For approve-later flows, use the approval queue (`approvals.request_approval`).
    """
    item = get_work_item(session, item_id)
    if item is None:
        raise UnknownWorkItem(item_id)
    process = get_process(session, item.process_id)

    needs_approval = requires_approval(process.oversight, to, set(process.gates))
    if needs_approval:
        if approver_id is None:
            raise ApprovalRequired(
                f"moving into {to!r} needs approval "
                f"(process {process.name!r} is at oversight {process.oversight!r})")
        approver = session.get(User, approver_id)
        if approver is None:
            raise ValueError(f"unknown approver: {approver_id!r}")
        if not at_least(session, approver.role, process.min_approver_role):
            raise PolicyDenied(
                f"approval requires {process.min_approver_role}+ (got {approver.role!r})")

    result = apply_transition(session, item_id, to, actor_id, audit, changes=changes)
    if needs_approval:
        audit.write(Record.of(
            recipe="approval", actor=approver_id, owner=result.owner_id,
            inputs={"to": to, "moved_by": actor_id, "oversight": process.oversight},
            output="approved", subject=item_id,
        ))
        session.refresh(result)  # the approval-event commit expired attrs; reload
    return result


def sync_tracker(session: Session, integ_id: str, repo_id: str, process_id: str,
                 actor_id: str, audit: AuditSink) -> dict:
    """Import a tracker integration's issues as work items, deduped by external ref."""
    integ = get_integration(session, integ_id)
    if integ is None:
        raise ValueError(f"unknown integration: {integ_id!r}")
    if integ.kind not in TRACKER_KINDS:
        raise ValueError(f"{integ.kind} is not a work-item tracker")

    created, skipped = 0, 0
    for issue in list_issues(session, integ_id):
        ref = f"{integ.kind}:{issue['key']}"
        if find_by_external_ref(session, ref):
            skipped += 1
            continue
        item = create_work_item(session, repo_id, process_id, issue["title"], actor_id,
                                external_ref=ref)
        audit.write(Record.of(
            recipe="sync", actor=actor_id, owner=actor_id,
            inputs={"integration": integ_id, "key": issue["key"]}, output=ref, subject=item.id,
        ))
        created += 1
    return {"created": created, "skipped": skipped}
