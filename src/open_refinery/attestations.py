"""Attestations — recorded claims that a check passed.

A gate can require named checks (evals, tests, code-health, content-filter) to
pass before a work item may enter a step. Each attestation is recorded per work
item and audited; the latest attestation for a check wins.
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone

from .audit import AuditSink
from .provenance import Record
from .store import register_schema

register_schema(
    """
    CREATE TABLE IF NOT EXISTS attestations (
        id           TEXT PRIMARY KEY,
        work_item_id TEXT NOT NULL REFERENCES work_items(id),
        check_name   TEXT NOT NULL,
        passed       INTEGER NOT NULL,
        actor_id     TEXT NOT NULL REFERENCES users(id),
        created_at   TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS ix_attestations_item ON attestations(work_item_id);
    """
)


class AttestationMissing(Exception):
    """Raised when a required check has never been attested for the item."""


class AttestationFailed(Exception):
    """Raised when a required check's latest attestation is a failure."""


def attest(
    conn: sqlite3.Connection,
    item_id: str,
    check: str,
    actor_id: str,
    passed: bool,
    audit: AuditSink,
) -> None:
    """Record that `check` passed (or failed) for a work item, and audit it."""
    row = conn.execute(
        "SELECT owner_id FROM work_items WHERE id = ?", (item_id,)
    ).fetchone()
    if row is None:
        raise ValueError(f"unknown work item: {item_id!r}")
    if conn.execute("SELECT 1 FROM users WHERE id = ?", (actor_id,)).fetchone() is None:
        raise ValueError(f"unknown actor: {actor_id!r}")

    conn.execute(
        "INSERT INTO attestations (id, work_item_id, check_name, passed, actor_id, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (uuid.uuid4().hex, item_id, check, int(passed),
         actor_id, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    audit.write(
        Record.of(
            recipe="attestation",
            actor=actor_id,
            owner=row["owner_id"],
            inputs={"check": check},
            output="pass" if passed else "fail",
            subject=item_id,
        )
    )


def attestations_for(conn: sqlite3.Connection, item_id: str) -> dict[str, bool]:
    """Latest attestation per check for a work item.

    ponytail: latest wins, no expiry — attestations don't auto-invalidate on
    rework. Re-attest after changing the work. Add TTL/invalidation if that bites.
    """
    rows = conn.execute(
        "SELECT check_name, passed FROM attestations WHERE work_item_id = ? "
        "ORDER BY created_at ASC",
        (item_id,),
    )
    return {r["check_name"]: bool(r["passed"]) for r in rows}  # later rows overwrite


def unmet_checks(
    state: dict[str, bool], required: tuple[str, ...]
) -> tuple[list[str], list[str]]:
    """Split required checks into (missing, failed) given current attestation state."""
    missing = [c for c in required if c not in state]
    failed = [c for c in required if state.get(c) is False]
    return missing, failed
