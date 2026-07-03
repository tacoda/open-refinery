"""Attestations — recorded claims that a check passed.

A gate can require named checks (evals, tests, code-health, …) to pass before a
work item may enter a step. Each attestation is recorded per work item and
audited; the latest attestation for a check wins.
"""

from __future__ import annotations

from sqlmodel import Session, select

from .audit import AuditSink
from .models import Attestation, User, WorkItem
from .provenance import Record


class AttestationMissing(Exception):
    """Raised when a required check has never been attested for the item."""


class AttestationFailed(Exception):
    """Raised when a required check's latest attestation is a failure."""


def attest(session: Session, item_id: str, check: str, actor_id: str, passed: bool,
           audit: AuditSink) -> None:
    """Record that `check` passed (or failed) for a work item, and audit it."""
    item = session.get(WorkItem, item_id)
    if item is None:
        raise ValueError(f"unknown work item: {item_id!r}")
    if session.get(User, actor_id) is None:
        raise ValueError(f"unknown actor: {actor_id!r}")

    session.add(Attestation(work_item_id=item_id, check_name=check, passed=passed,
                            actor_id=actor_id))
    session.commit()
    audit.write(Record.of(
        recipe="attestation", actor=actor_id, owner=item.owner_id,
        inputs={"check": check}, output="pass" if passed else "fail", subject=item_id,
    ))


def attestations_for(session: Session, item_id: str) -> dict[str, bool]:
    """Latest attestation per check for a work item (latest wins, no expiry)."""
    rows = session.exec(
        select(Attestation).where(Attestation.work_item_id == item_id)
        .order_by(Attestation.created_at)
    )
    return {a.check_name: a.passed for a in rows}


def unmet_checks(state: dict[str, bool], required: tuple[str, ...]) -> tuple[list[str], list[str]]:
    """Split required checks into (missing, failed) given current attestation state."""
    missing = [c for c in required if c not in state]
    failed = [c for c in required if state.get(c) is False]
    return missing, failed
