"""Per-layer approval workflows — the governance-change cascade.

Admins configure, per role **layer**, the ordered chain of roles that must
approve a change to governance (a policy, etc.). A **change proposal** walks that
chain: each reviewer may **accept** (advance; apply on the last slot), **deny**
(stop), or give **feedback** (send back to the proposer to revise & resubmit).
Separation of duties: a distinct signer per slot, each at or above the slot's
role. Mirrors the work-item approval queue, one level up — for changing the rules
themselves rather than moving work.
"""

from __future__ import annotations

from sqlmodel import Session, select

from .audit import AuditSink
from .models import ApprovalWorkflow, ChangeProposal, User
from .policies import PolicyDenied, create_policy
from .provenance import Record
from .users import at_least, list_roles, role_rank, valid_role

DECISIONS = ("accept", "deny", "feedback")


# --- workflow config (admin) ----------------------------------------------

def set_workflow(session: Session, layer: str, chain: list[str], admin_id: str) -> ApprovalWorkflow:
    if not valid_role(session, layer):
        raise ValueError(f"unknown layer role: {layer!r}")
    for r in chain:
        if not valid_role(session, r):
            raise ValueError(f"chain role {r!r} is not a configured role")
    wf = session.get(ApprovalWorkflow, layer) or ApprovalWorkflow(layer=layer, updated_by=admin_id)
    wf.chain = list(chain)
    wf.updated_by = admin_id
    session.add(wf)
    session.commit()
    session.refresh(wf)
    return wf


def get_workflow(session: Session, layer: str) -> ApprovalWorkflow | None:
    return session.get(ApprovalWorkflow, layer)


def list_workflows(session: Session) -> list[ApprovalWorkflow]:
    return list(session.exec(select(ApprovalWorkflow)))


# --- proposals -------------------------------------------------------------

def _resolve_chain(session: Session, layer: str, proposer: User) -> list[str]:
    """The approval chain for a proposal. An admin-configured workflow for the
    layer wins; otherwise the suggestion **cascades up** the role ladder — every
    role ranked above the proposer, lowest first (a dev's idea escalates
    dev→…→platform→admin). Falls back to the layer role if the proposer is at the
    top."""
    wf = get_workflow(session, layer)
    if wf and wf.chain:
        return list(wf.chain)
    up = [r.name for r in list_roles(session) if r.rank > role_rank(session, proposer.role)]
    return up or [layer]


def propose(session: Session, target_kind: str, action: str, payload: dict, layer: str,
            proposer_id: str) -> ChangeProposal:
    if (target_kind, action) not in _APPLIERS:
        raise ValueError(f"unsupported change: {target_kind!r}/{action!r}")
    proposer = session.get(User, proposer_id)
    if proposer is None:
        raise ValueError(f"unknown proposer: {proposer_id!r}")
    if not valid_role(session, layer):
        raise ValueError(f"unknown layer role: {layer!r}")
    precheck = _PRECHECKS.get((target_kind, action))
    if precheck:
        precheck(session, payload, proposer)
    prop = ChangeProposal(target_kind=target_kind, action=action, payload=payload,
                          layer=layer, proposed_by=proposer_id,
                          chain=_resolve_chain(session, layer, proposer))
    session.add(prop)
    session.commit()
    session.refresh(prop)
    return prop


def review(session: Session, proposal_id: str, reviewer_id: str, decision: str, audit: AuditSink,
           *, note: str = "") -> ChangeProposal:
    if decision not in DECISIONS:
        raise ValueError(f"unknown decision: {decision!r} (expected {DECISIONS})")
    prop = session.get(ChangeProposal, proposal_id)
    if prop is None:
        raise ValueError(f"unknown proposal: {proposal_id!r}")
    if prop.status != "pending":
        raise ValueError(f"proposal is {prop.status}, not pending")
    reviewer = session.get(User, reviewer_id)
    if reviewer is None:
        raise ValueError(f"unknown reviewer: {reviewer_id!r}")

    slot_role = prop.chain[prop.current]
    if not at_least(session, reviewer.role, slot_role):
        raise PolicyDenied(f"slot {prop.current} needs {slot_role}+ (got {reviewer.role!r})")
    if any(d["user_id"] == reviewer_id for d in prop.decisions):
        raise PolicyDenied("a reviewer may act on a proposal only once (separation of duties)")

    prop.decisions = prop.decisions + [{"role": slot_role, "user_id": reviewer_id,
                                        "decision": decision, "note": note, "at": _now()}]
    if decision == "deny":
        prop.status = "denied"
    elif decision == "feedback":
        prop.status = "revising"           # proposer revises & resubmits
    else:  # accept
        prop.current += 1
        if prop.current == len(prop.chain):  # chain complete → apply
            prop.applied_ref = _apply(session, prop)
            prop.status = "accepted"
    session.add(prop)
    session.commit()
    session.refresh(prop)
    audit.write(Record.of(recipe=f"change-{decision}", actor=reviewer_id, owner=prop.proposed_by,
                          inputs={"proposal": proposal_id, "slot": slot_role, "note": note},
                          output=prop.status, subject=proposal_id))
    return prop


def resubmit(session: Session, proposal_id: str, proposer_id: str,
             *, payload: dict | None = None) -> ChangeProposal:
    """Proposer revises a feedback'd proposal and restarts review from the top."""
    prop = session.get(ChangeProposal, proposal_id)
    if prop is None:
        raise ValueError(f"unknown proposal: {proposal_id!r}")
    if prop.status != "revising":
        raise ValueError(f"proposal is {prop.status}, not revising")
    if prop.proposed_by != proposer_id:
        raise PolicyDenied("only the proposer may resubmit")
    if payload is not None:
        prop.payload = payload
    prop.decisions = []      # fresh review pass
    prop.current = 0
    prop.status = "pending"
    session.add(prop)
    session.commit()
    session.refresh(prop)
    return prop


def list_proposals(session: Session, *, status: str | None = None) -> list[ChangeProposal]:
    stmt = select(ChangeProposal)
    if status is not None:
        stmt = stmt.where(ChangeProposal.status == status)
    return list(session.exec(stmt.order_by(ChangeProposal.created_at.desc())))


# --- appliers: how an accepted proposal becomes a real change --------------

def _apply_policy_create(session: Session, prop: ChangeProposal) -> str:
    p = prop.payload
    # authored at the proposer's layer (owner drives strict-precedence rank)
    policy = create_policy(session, p.get("effect", "allow"), prop.proposed_by,
                           role=p.get("role", "*"), action=p.get("action", "*"),
                           resource=p.get("resource", "*"), strict=p.get("strict"),
                           kind=p.get("kind", "rule"), content=p.get("content", ""),
                           namespace=p.get("namespace", ""))
    return policy.id


def _apply_suggestion(session: Session, prop: ChangeProposal) -> str:
    # a free-text idea that cascaded up the ladder — adoption is the record itself;
    # no artifact is created (the payload's "text" is the accepted suggestion).
    return ""


def _apply_work_create(session: Session, prop: ChangeProposal) -> str:
    """An accepted proposal becomes **work**, not a change.

    This is the rule the improve lane is built on: the lane that proposes
    changes does not also get to make them. What acceptance buys is a work item
    — which then goes through the stage graph, the contracts, the delivery gate
    and the same review as anything else a person filed.

    Accepting is therefore cheap to get wrong and expensive to abuse, which is
    the right way round.
    """
    from .work_items import create_work_item

    p = prop.payload
    for key in ("repo_id", "process_id", "title"):
        if not p.get(key):
            raise ValueError(f"a work proposal needs {key!r}")
    item = create_work_item(session, p["repo_id"], p["process_id"], p["title"],
                            prop.proposed_by)
    return item.id


def _apply_ladder_move(session: Session, prop: ChangeProposal) -> str:
    """Move a rule to a different rung — **the one change applied directly.**

    A rung move changes where a rule is enforced, not what the codebase says, so
    there is no diff for a pipeline to produce. `ladder.move` keeps the
    asymmetry that matters: a promotion adds enforcement, a demotion removes it,
    and the demotion is the one this chain had to sign for.
    """
    from .ladder import move

    p = prop.payload
    rule_id, to = p.get("rule_id"), p.get("to")
    if not rule_id or to is None:
        raise ValueError("a ladder proposal needs 'rule_id' and 'to'")
    signer = prop.decisions[-1]["user_id"] if prop.decisions else prop.proposed_by
    rule = move(session, rule_id, int(to), approver_id=signer,
                predicate_name=p.get("predicate", ""))
    return rule.id


def _precheck_ladder_move(session: Session, payload: dict, proposer: User) -> None:
    """**The factory never proposes its own demotion.**

    A promotion adds enforcement and the factory may ask for one. A demotion
    removes it, and a system that can propose weakening its own guardrails only
    needs a tired approver to get there. Refused at propose time so the
    proposer sees it, rather than after a chain of people has signed.
    """
    from .ladder import plan_move

    if proposer.kind != "agent":
        return
    planned = plan_move(session, payload.get("rule_id", ""), int(payload.get("to", 0)))
    if planned.direction == "demotion":
        raise PolicyDenied(
            "an agent may not propose a demotion — removing enforcement is a "
            "person's decision (PLAN-3.0 §4.1)")


_APPLIERS = {("policy", "create"): _apply_policy_create,
             ("suggestion", "adopt"): _apply_suggestion,
             ("work", "create"): _apply_work_create,
             ("ladder", "move"): _apply_ladder_move}

# Refusals that belong at propose time, where the proposer is the one who reads
# them. Keyed the same way as the appliers.
_PRECHECKS = {("ladder", "move"): _precheck_ladder_move}


def _apply(session: Session, prop: ChangeProposal) -> str:
    return _APPLIERS[(prop.target_kind, prop.action)](session, prop)


def _now() -> str:
    from .models import now_iso
    return now_iso()
