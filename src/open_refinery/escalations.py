"""Approval SLAs — a pending request past its `due_at` is overdue and gets
escalated once: an `approval-overdue` audit event (hash-chained, and routable by
notification rules to whoever watches for it) plus a dedup stamp so a request is
escalated at most once. Pure `overdue_approvals` is testable; `escalate_overdue`
is the side-effecting sweep the scheduler calls on a cadence (same ethos as the
ingest scheduler — in-process, off the request path).
"""

from __future__ import annotations

from sqlmodel import Session, select

from .audit import AuditSink
from .models import ApprovalRequest, now_iso


def overdue_approvals(session: Session, now: str | None = None) -> list[ApprovalRequest]:
    """Pending requests whose SLA deadline has passed and not yet escalated."""
    now = now or now_iso()
    stmt = (select(ApprovalRequest)
            .where(ApprovalRequest.status == "pending")
            .where(ApprovalRequest.due_at != "")
            .where(ApprovalRequest.due_at <= now)
            .where(ApprovalRequest.escalated_at == ""))
    return list(session.exec(stmt))


def current_overdue(session: Session, now: str | None = None) -> list[ApprovalRequest]:
    """Pending requests past their deadline, regardless of whether escalation has
    fired — the live overdue queue for the dashboard."""
    now = now or now_iso()
    stmt = (select(ApprovalRequest)
            .where(ApprovalRequest.status == "pending")
            .where(ApprovalRequest.due_at != "")
            .where(ApprovalRequest.due_at <= now))
    return list(session.exec(stmt))


def escalate_overdue(session: Session, audit: AuditSink, now: str | None = None) -> list[str]:
    """Emit an `approval-overdue` audit event for each newly-overdue request and
    stamp it escalated. Returns the request ids escalated."""
    from .provenance import Record

    now = now or now_iso()
    escalated = []
    for req in overdue_approvals(session, now):
        slot = len(req.approvals)
        pending_role = req.required_roles[slot] if slot < len(req.required_roles) else ""
        audit.write(Record.of(recipe="approval-overdue", actor="system", owner=req.requested_by,
                              inputs={"request": req.id, "to": req.to_step,
                                      "due_at": req.due_at, "awaiting_role": pending_role},
                              output="overdue", subject=req.work_item_id))
        req.escalated_at = now
        session.add(req)
        escalated.append(req.id)
    session.commit()
    return escalated
