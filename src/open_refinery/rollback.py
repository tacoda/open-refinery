"""Rollback — a first-class, governed revert to a known-good prior stage.

Rolling back is not a normal forward transition: it moves a work item back to a
stage it has **previously occupied** (from its `StageHistory`) and *reverses the
change sets* of every transition being undone — not just the code, but the
database migrations, configuration, library/dependency changes, **data updates**
(restore the prior snapshot), **service vendor swaps** (restore the prior
vendor), and **secret/credential rotations** (restore the prior credential
*reference* — never the material) those transitions carried in their diff.

The platform governs; it does not run git/alembic/pip itself (that's the
harness's job). So a rollback authorizes the revert (policy action `rollback`,
honoring enforcement mode, auditing refusals), computes a structured **reverse
plan** across all four categories, records that plan as the `rollback` audit
event, appends the move to the history, and returns the plan so the harness/UI
can apply it and the trail shows exactly what was reverted.
"""

from __future__ import annotations

from sqlmodel import Session, select

from .audit import AuditSink
from .models import StageHistory, User, WorkItem
from .policies import enforce as enforce_policy
from .provenance import Record
from .work_items import UnknownWorkItem, _record_stage


def stage_history(session: Session, item_id: str) -> list[StageHistory]:
    return list(session.exec(
        select(StageHistory).where(StageHistory.work_item_id == item_id)
        .order_by(StageHistory.created_at)))


def rollback_targets(session: Session, item_id: str) -> list[str]:
    """Distinct prior stages this item can roll back to (all but its current one)."""
    item = session.get(WorkItem, item_id)
    if item is None:
        raise UnknownWorkItem(item_id)
    seen, out = set(), []
    for h in stage_history(session, item_id):
        if h.stage != item.current_stage and h.stage not in seen:
            seen.add(h.stage)
            out.append(h.stage)
    return out


def _undone(history: list[StageHistory], to_stage: str) -> list[StageHistory]:
    """The transitions to reverse: everything after the item last sat at to_stage."""
    last = max((i for i, h in enumerate(history) if h.stage == to_stage), default=-1)
    return [h for h in history[last + 1:] if h.changes]


# Categories that are a map of {name: {"old", "new"}} — reversed by restoring
# each name to its value *before the earliest undone change* (first-seen "old").
#
# SECURITY: `secrets` old/new are **references only** — a credential version id,
# rotation id, or vault path — NEVER the secret material. The change set is
# stored in StageHistory.changes and digested into the audit trail (plaintext),
# so material must never be placed there. A rollback restores the prior
# reference; the harness re-activates that credential version out of band.
_RESTORE_KEYS = ("config", "env", "libraries", "data", "services", "secrets")


def reverse_plan(undone: list[StageHistory]) -> dict:
    """Invert the forward change sets of the undone transitions (oldest→newest).

    Restores each thing to its state *before the earliest undone change*: code to
    that transition's `prev` commit; each config value / env var / library /
    dataset / service / secret-reference to its first-seen `old`; migrations are
    downgraded newest-first so dependents drop first.
    """
    plan: dict = {"code": None, "migrations": [], **{k: {} for k in _RESTORE_KEYS}}
    forward_migrations = []
    for h in undone:                                  # oldest → newest
        c = h.changes or {}
        code = c.get("code")
        if code and plan["code"] is None:             # earliest code state wins
            plan["code"] = {"revert_to": code.get("prev")}
        forward_migrations.extend(c.get("migrations") or [])
        for cat in _RESTORE_KEYS:
            for name, chg in (c.get(cat) or {}).items():
                plan[cat].setdefault(name, chg.get("old"))
    plan["migrations"] = [{"downgrade": m} for m in reversed(forward_migrations)]
    return plan


def rollback_work_item(session: Session, item_id: str, to_stage: str, actor_id: str,
                       audit: AuditSink) -> dict:
    """Revert a work item to a prior stage + reverse its change sets. Authorized + audited.

    Returns {"item": WorkItem, "plan": reverse_plan} — the plan the harness applies.
    """
    item = session.get(WorkItem, item_id)
    if item is None:
        raise UnknownWorkItem(item_id)
    actor = session.get(User, actor_id)
    if actor is None:
        raise ValueError(f"unknown actor: {actor_id!r}")
    if to_stage == item.current_stage:
        raise ValueError(f"already at stage {to_stage!r}")
    if to_stage not in rollback_targets(session, item_id):
        raise ValueError(f"{to_stage!r} is not a prior stage of this item")

    enforce_policy(session, actor.role, "rollback", to_stage,  # gated + refusals audited
                   audit=audit, actor_id=actor_id, subject=item_id)

    plan = reverse_plan(_undone(stage_history(session, item_id), to_stage))

    frm = item.current_stage
    item.current_stage = to_stage
    session.add(item)
    session.commit()
    _record_stage(session, item_id, to_stage, "rollback", actor_id, plan)
    audit.write(Record.of(
        recipe="rollback", actor=actor_id, owner=item.owner_id,
        inputs={"from": frm, "process": item.process_id, "repo": item.repo_id},
        output={"to": to_stage, "plan": plan}, subject=item_id))
    session.refresh(item)
    return {"item": item, "plan": plan}
