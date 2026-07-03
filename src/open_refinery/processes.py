"""Processes — declarative workflows work items move through.

A `Process` is a set of stages plus the transitions allowed between them, owned
by a user. Two archetypes ship: **board** (kanban — free movement between any
stages) and **doctrine** (a fixed forward procedure). The definition is data;
guards and stage actions attach later.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from .oversight import LEVELS
from .store import register_schema

ARCHETYPES = ("board", "doctrine")

register_schema(
    """
    CREATE TABLE IF NOT EXISTS processes (
        id         TEXT PRIMARY KEY,
        name       TEXT NOT NULL,
        archetype  TEXT NOT NULL,
        owner_id   TEXT NOT NULL REFERENCES users(id),
        definition TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS ix_processes_owner ON processes(owner_id);
    """
)


@dataclass(frozen=True)
class Process:
    id: str
    name: str
    archetype: str
    owner_id: str
    stages: tuple[str, ...]
    transitions: frozenset[tuple[str, str]]
    initial: str
    created_at: str
    oversight: str = "dark"           # autonomy level; see oversight.LEVELS
    gates: frozenset[str] = frozenset()  # steps that need approval under supervised

    def can_transition(self, frm: str, to: str) -> bool:
        return (frm, to) in self.transitions


def _derive_transitions(archetype: str, stages: tuple[str, ...]) -> frozenset[tuple[str, str]]:
    if archetype == "doctrine":  # strict forward procedure
        return frozenset(zip(stages, stages[1:]))
    # board (kanban): free movement between any two distinct stages
    return frozenset((a, b) for a in stages for b in stages if a != b)


def create_process(
    conn: sqlite3.Connection,
    name: str,
    archetype: str,
    stages: list[str],
    owner_id: str,
    *,
    transitions: list[tuple[str, str]] | None = None,
    initial: str | None = None,
    oversight: str = "dark",
    gates: list[str] | None = None,
) -> Process:
    if archetype not in ARCHETYPES:
        raise ValueError(f"unknown archetype: {archetype!r} (expected {ARCHETYPES})")
    if oversight not in LEVELS:
        raise ValueError(f"unknown oversight level: {oversight!r} (expected {LEVELS})")
    if not stages:
        raise ValueError("a process needs at least one stage")

    stages_t = tuple(stages)
    initial = initial or stages_t[0]
    if initial not in stages_t:
        raise ValueError(f"initial stage {initial!r} not in stages")

    gates_f = frozenset(gates or ())
    unknown_gates = gates_f - set(stages_t)
    if unknown_gates:
        raise ValueError(f"gates reference unknown steps: {sorted(unknown_gates)}")

    trans = (
        frozenset(map(tuple, transitions))
        if transitions is not None
        else _derive_transitions(archetype, stages_t)
    )
    for frm, to in trans:
        if frm not in stages_t or to not in stages_t:
            raise ValueError(f"transition ({frm!r}, {to!r}) references an unknown stage")

    if conn.execute("SELECT 1 FROM users WHERE id = ?", (owner_id,)).fetchone() is None:
        raise ValueError(f"unknown owner: {owner_id!r}")

    process = Process(
        id=uuid.uuid4().hex,
        name=name,
        archetype=archetype,
        owner_id=owner_id,
        stages=stages_t,
        transitions=trans,
        initial=initial,
        created_at=datetime.now(timezone.utc).isoformat(),
        oversight=oversight,
        gates=gates_f,
    )
    conn.execute(
        "INSERT INTO processes (id, name, archetype, owner_id, definition, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            process.id,
            name,
            archetype,
            owner_id,
            json.dumps(
                {
                    "stages": list(stages_t),
                    "transitions": sorted(map(list, trans)),
                    "initial": initial,
                    "oversight": oversight,
                    "gates": sorted(gates_f),
                }
            ),
            process.created_at,
        ),
    )
    conn.commit()
    return process


def _row_to_process(row: sqlite3.Row) -> Process:
    d = json.loads(row["definition"])
    return Process(
        id=row["id"],
        name=row["name"],
        archetype=row["archetype"],
        owner_id=row["owner_id"],
        stages=tuple(d["stages"]),
        transitions=frozenset(tuple(t) for t in d["transitions"]),
        initial=d["initial"],
        created_at=row["created_at"],
        oversight=d.get("oversight", "dark"),
        gates=frozenset(d.get("gates", ())),
    )


def get_process(conn: sqlite3.Connection, process_id: str) -> Process | None:
    row = conn.execute("SELECT * FROM processes WHERE id = ?", (process_id,)).fetchone()
    return _row_to_process(row) if row else None


def list_processes(
    conn: sqlite3.Connection, *, owner_id: str | None = None
) -> list[Process]:
    if owner_id is None:
        rows = conn.execute("SELECT * FROM processes ORDER BY created_at DESC")
    else:
        rows = conn.execute(
            "SELECT * FROM processes WHERE owner_id = ? ORDER BY created_at DESC",
            (owner_id,),
        )
    return [_row_to_process(row) for row in rows]
