"""Async approval queue — request a gated move, approve it later, possibly in a
chain (e.g. senior then platform).

`request_approval` records a pending `ApprovalRequest` whose `required_roles`
come from the process's `approval_chain` (or `[min_approver_role]`). Each slot is
signed by a **distinct** approver **at or above** that slot's role, in order;
when the chain completes the move is applied. This is the approve-later
counterpart to the synchronous `work_items.transition`.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlmodel import Session, select

from .audit import AuditSink
from .models import ApprovalRequest, User, now_iso
from .oversight import requires_approval
from .policies import PolicyDenied
from .processes import get_process
from .provenance import Record
from .users import at_least
from .work_items import InvalidTransition, UnknownWorkItem, apply_transition, get_work_item


def _chain(process) -> list[str]:
    return list(process.approval_chain) or [process.min_approver_role]


def _sla_deadline(process) -> str:
    """The `due_at` a request under this process gets, or "" when it sets no SLA."""
    if process.approval_sla_hours <= 0:
        return ""
    return (datetime.fromisoformat(now_iso())
            + timedelta(hours=process.approval_sla_hours)).isoformat()


def request_approval(session: Session, item_id: str, to: str, requester_id: str,
                     audit: AuditSink) -> ApprovalRequest:
    """Open a pending approval request for a gated move."""
    item = get_work_item(session, item_id)
    if item is None:
        raise UnknownWorkItem(item_id)
    if session.get(User, requester_id) is None:
        raise ValueError(f"unknown requester: {requester_id!r}")
    process = get_process(session, item.process_id)
    if not process.can_transition(item.current_stage, to):
        raise InvalidTransition(f"{item.current_stage!r} -> {to!r} not allowed")
    if not requires_approval(process.oversight, to, set(process.gates)):
        raise ValueError(f"moving into {to!r} needs no approval")

    req = ApprovalRequest(work_item_id=item_id, to_step=to, requested_by=requester_id,
                          required_roles=_chain(process), approvals=[], status="pending",
                          due_at=_sla_deadline(process))
    session.add(req)
    session.commit()
    session.refresh(req)
    audit.write(Record.of(recipe="approval-requested", actor=requester_id, owner=item.owner_id,
                          inputs={"to": to, "chain": req.required_roles}, output="pending",
                          subject=item_id))
    return req


def get_approval(session: Session, request_id: str) -> ApprovalRequest | None:
    return session.get(ApprovalRequest, request_id)


def list_approvals(session: Session, *, status: str | None = None,
                   work_item_id: str | None = None) -> list[ApprovalRequest]:
    stmt = select(ApprovalRequest)
    if status is not None:
        stmt = stmt.where(ApprovalRequest.status == status)
    if work_item_id is not None:
        stmt = stmt.where(ApprovalRequest.work_item_id == work_item_id)
    return list(session.exec(stmt.order_by(ApprovalRequest.created_at.desc())))


def _authorize_slot(session: Session, req: ApprovalRequest, approver_id: str) -> str:
    """Validate that `approver_id` may sign the next open slot; return its required
    role. Enforces segregation of duties (requester ≠ approver, one signature per
    chain) and the slot's minimum role."""
    approver = session.get(User, approver_id)
    if approver is None:
        raise ValueError(f"unknown approver: {approver_id!r}")
    # Segregation of duties: neither the requester nor a prior signer of this
    # chain may sign — every slot is a distinct person, none of them the requester.
    already_involved = {req.requested_by, *(a["user_id"] for a in req.approvals)}
    if approver_id in already_involved:
        raise PolicyDenied("segregation of duties: the requester and each signer must be distinct people")
    slot = len(req.approvals)
    required_role = req.required_roles[slot]
    if not at_least(session, approver.role, required_role):
        raise PolicyDenied(f"slot {slot} needs {required_role}+ (got {approver.role!r})")
    return required_role


def approve(session: Session, request_id: str, approver_id: str, audit: AuditSink) -> ApprovalRequest:
    """Sign the next slot in the chain; apply the move when the chain completes."""
    req = session.get(ApprovalRequest, request_id)
    if req is None:
        raise ValueError(f"unknown approval request: {request_id!r}")
    if req.status != "pending":
        raise ValueError(f"approval request is {req.status}, not pending")
    required_role = _authorize_slot(session, req, approver_id)

    approvals = req.approvals + [{"role": required_role, "user_id": approver_id, "at": now_iso()}]
    audit.write(Record.of(recipe="approval", actor=approver_id, owner=approver_id,
                          inputs={"request": request_id, "slot": required_role},
                          output="signed", subject=req.work_item_id))

    if len(approvals) == len(req.required_roles):  # chain complete → apply the move
        apply_transition(session, req.work_item_id, req.to_step, req.requested_by, audit)
        req.status = "applied"
    req.approvals = approvals
    session.add(req)
    session.commit()
    session.refresh(req)
    return req


def reject(session: Session, request_id: str, approver_id: str, audit: AuditSink) -> ApprovalRequest:
    req = session.get(ApprovalRequest, request_id)
    if req is None:
        raise ValueError(f"unknown approval request: {request_id!r}")
    if req.status != "pending":
        raise ValueError(f"approval request is {req.status}, not pending")
    approver = session.get(User, approver_id)
    if approver is None or not at_least(session, approver.role, req.required_roles[0]):
        raise PolicyDenied("insufficient role to reject this request")
    req.status = "rejected"
    session.add(req)
    session.commit()
    session.refresh(req)
    audit.write(Record.of(recipe="approval-rejected", actor=approver_id, owner=approver_id,
                          inputs={"request": request_id}, output="rejected",
                          subject=req.work_item_id))
    return req
