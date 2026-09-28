"""Oversight — the human-in-the-loop dial.

A repository runs its work at an autonomy level. The level decides how much of a
run a person has to touch: it becomes the set of tool calls the harness
interrupts on (`pipeline/agent.interrupts_for`). The audit trail is the same at
every level; they differ only in what waits for a human.

    L0 manual      — a person answers every call
    L1 assisted    — a person answers every write
    L2 supervised  — what a rule marks `ask` waits (the default)
    L3 autonomous  — nothing waits; humans are notified out of band
    L4 dark        — nothing waits, and nothing is announced

`ask` never becomes `allow`: at autonomous and dark it degrades to REFUSE,
because an unattended factory reading `ask` as yes has answered a question
nobody put.

Until 3.0 this lived on a `Process` and gated a kanban transition. It carried
over to the repository because a run was the only thing that ever read it.
"""

from __future__ import annotations

LEVELS = ("manual", "assisted", "supervised", "autonomous", "dark")
DEFAULT = "supervised"
