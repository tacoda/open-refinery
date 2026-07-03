"""Processes — declarative workflows work items move through.

A `Process` is a series of steps connected by transitions (a directed graph, so
feedback loops are first-class), owned by a user. Archetypes: **board** (free
movement) and **doctrine** (forward-linear). Structure lives in JSON columns.
"""

from __future__ import annotations

from sqlmodel import Session, select

from .models import Process, User
from .oversight import LEVELS
from .users import ROLES

ARCHETYPES = ("board", "doctrine")


def _derive_transitions(archetype: str, stages: list[str]) -> list[list[str]]:
    if archetype == "doctrine":  # strict forward procedure
        return [[a, b] for a, b in zip(stages, stages[1:])]
    # board (kanban): free movement between any two distinct stages
    return [[a, b] for a in stages for b in stages if a != b]


def create_process(
    session: Session,
    name: str,
    archetype: str,
    stages: list[str],
    owner_id: str,
    *,
    transitions: list | None = None,
    initial: str | None = None,
    oversight: str = "dark",
    gates: list[str] | None = None,
    checks: dict[str, list[str]] | None = None,
    min_approver_role: str = "senior",
) -> Process:
    if archetype not in ARCHETYPES:
        raise ValueError(f"unknown archetype: {archetype!r} (expected {ARCHETYPES})")
    if oversight not in LEVELS:
        raise ValueError(f"unknown oversight level: {oversight!r} (expected {LEVELS})")
    if min_approver_role not in ROLES:
        raise ValueError(f"unknown min_approver_role: {min_approver_role!r} (expected {ROLES})")
    if not stages:
        raise ValueError("a process needs at least one stage")

    stages = list(stages)
    initial = initial or stages[0]
    if initial not in stages:
        raise ValueError(f"initial stage {initial!r} not in stages")

    gates = list(gates or ())
    if set(gates) - set(stages):
        raise ValueError(f"gates reference unknown steps: {sorted(set(gates) - set(stages))}")

    checks = {step: list(names) for step, names in (checks or {}).items()}
    if set(checks) - set(stages):
        raise ValueError(f"checks reference unknown steps: {sorted(set(checks) - set(stages))}")

    trans = ([list(t) for t in transitions] if transitions is not None
             else _derive_transitions(archetype, stages))
    for frm, to in trans:
        if frm not in stages or to not in stages:
            raise ValueError(f"transition ({frm!r}, {to!r}) references an unknown stage")

    if session.get(User, owner_id) is None:
        raise ValueError(f"unknown owner: {owner_id!r}")

    process = Process(name=name, archetype=archetype, owner_id=owner_id, initial=initial,
                      oversight=oversight, min_approver_role=min_approver_role,
                      stages=stages, transitions=trans, gates=gates, checks=checks)
    session.add(process)
    session.commit()
    session.refresh(process)
    return process


def get_process(session: Session, process_id: str) -> Process | None:
    return session.get(Process, process_id)


def list_processes(session: Session, *, owner_id: str | None = None) -> list[Process]:
    stmt = select(Process)
    if owner_id is not None:
        stmt = stmt.where(Process.owner_id == owner_id)
    return list(session.exec(stmt.order_by(Process.created_at.desc())))
