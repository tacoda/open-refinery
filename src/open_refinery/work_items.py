"""Work items and the transition loop — the core of the factory.

A `WorkItem` belongs to a repository and a process, sits at one step, and is
owned by a user. Shipping work = transitioning it between steps. Every
transition is a governed production: it checks the process allows the move,
records an `Event` (subject = the work item), and returns the moved item. The
item's history is `query_events(conn, subject=item.id)`.
"""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from .audit import AuditSink
from .oversight import requires_approval
from .processes import get_process
from .provenance import Record
from .store import register_schema

register_schema(
    """
    CREATE TABLE IF NOT EXISTS work_items (
        id            TEXT PRIMARY KEY,
        repo_id       TEXT NOT NULL REFERENCES repositories(id),
        process_id    TEXT NOT NULL REFERENCES processes(id),
        title         TEXT NOT NULL,
        current_stage TEXT NOT NULL,
        owner_id      TEXT NOT NULL REFERENCES users(id),
        created_at    TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS ix_work_items_owner ON work_items(owner_id);
    CREATE INDEX IF NOT EXISTS ix_work_items_repo ON work_items(repo_id);
    """
)


class InvalidTransition(Exception):
    """Raised when a move is not allowed by the item's process."""


class ApprovalRequired(Exception):
    """Raised when the process's oversight level requires a human approval first."""


class UnknownWorkItem(KeyError):
    """Raised when a work item id does not exist."""


@dataclass(frozen=True)
class WorkItem:
    id: str
    repo_id: str
    process_id: str
    title: str
    current_stage: str
    owner_id: str
    created_at: str


def _row_to_item(row: sqlite3.Row) -> WorkItem:
    return WorkItem(
        id=row["id"],
        repo_id=row["repo_id"],
        process_id=row["process_id"],
        title=row["title"],
        current_stage=row["current_stage"],
        owner_id=row["owner_id"],
        created_at=row["created_at"],
    )


def _exists(conn: sqlite3.Connection, table: str, id_: str) -> bool:
    return conn.execute(f"SELECT 1 FROM {table} WHERE id = ?", (id_,)).fetchone() is not None


def create_work_item(
    conn: sqlite3.Connection,
    repo_id: str,
    process_id: str,
    title: str,
    owner_id: str,
) -> WorkItem:
    if not _exists(conn, "repositories", repo_id):
        raise ValueError(f"unknown repository: {repo_id!r}")
    if not _exists(conn, "users", owner_id):
        raise ValueError(f"unknown owner: {owner_id!r}")
    process = get_process(conn, process_id)
    if process is None:
        raise ValueError(f"unknown process: {process_id!r}")

    item = WorkItem(
        id=uuid.uuid4().hex,
        repo_id=repo_id,
        process_id=process_id,
        title=title,
        current_stage=process.initial,  # every item starts at the process's initial step
        owner_id=owner_id,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    conn.execute(
        "INSERT INTO work_items "
        "(id, repo_id, process_id, title, current_stage, owner_id, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (item.id, repo_id, process_id, title, item.current_stage, owner_id, item.created_at),
    )
    conn.commit()
    return item


def get_work_item(conn: sqlite3.Connection, item_id: str) -> WorkItem | None:
    row = conn.execute("SELECT * FROM work_items WHERE id = ?", (item_id,)).fetchone()
    return _row_to_item(row) if row else None


def list_work_items(
    conn: sqlite3.Connection, *, owner_id: str | None = None, repo_id: str | None = None
) -> list[WorkItem]:
    clauses, params = [], []
    if owner_id is not None:
        clauses.append("owner_id = ?")
        params.append(owner_id)
    if repo_id is not None:
        clauses.append("repo_id = ?")
        params.append(repo_id)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    rows = conn.execute(
        f"SELECT * FROM work_items{where} ORDER BY created_at DESC", params
    )
    return [_row_to_item(row) for row in rows]


def transition(
    conn: sqlite3.Connection,
    item_id: str,
    to: str,
    actor_id: str,
    audit: AuditSink,
    *,
    approver_id: str | None = None,
) -> WorkItem:
    """Move a work item to a new step, recording the governed transition event.

    Order is load-bearing: validate the move, enforce oversight, apply, then
    audit — nothing is recorded unless the transition was allowed and applied.
    If the process's oversight level requires approval, an `approver_id` must be
    supplied or `ApprovalRequired` is raised; the approval is itself audited.
    """
    item = get_work_item(conn, item_id)
    if item is None:
        raise UnknownWorkItem(item_id)
    if not _exists(conn, "users", actor_id):
        raise ValueError(f"unknown actor: {actor_id!r}")

    process = get_process(conn, item.process_id)
    assert process is not None  # FK guarantees the process exists
    frm = item.current_stage
    if not process.can_transition(frm, to):
        raise InvalidTransition(f"{frm!r} -> {to!r} not allowed by process {process.name!r}")

    needs_approval = requires_approval(process.oversight, to, process.gates)
    if needs_approval:
        if approver_id is None:
            raise ApprovalRequired(
                f"moving into {to!r} needs approval "
                f"(process {process.name!r} is at oversight {process.oversight!r})"
            )
        if not _exists(conn, "users", approver_id):
            raise ValueError(f"unknown approver: {approver_id!r}")

    conn.execute("UPDATE work_items SET current_stage = ? WHERE id = ?", (to, item_id))
    conn.commit()

    audit.write(
        Record.of(
            recipe="transition",
            actor=actor_id,
            owner=item.owner_id,
            inputs={"from": frm, "process": item.process_id, "repo": item.repo_id},
            output=to,
            subject=item_id,
        )
    )
    if needs_approval:  # record the sign-off as its own audit event
        audit.write(
            Record.of(
                recipe="approval",
                actor=approver_id,
                owner=item.owner_id,
                inputs={"to": to, "moved_by": actor_id, "oversight": process.oversight},
                output="approved",
                subject=item_id,
            )
        )
    return WorkItem(**{**item.__dict__, "current_stage": to})
