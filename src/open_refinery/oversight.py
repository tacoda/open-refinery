"""Oversight — the human-in-the-loop dial.

Every process runs at an autonomy level. The level (plus which steps are gated)
decides whether a transition needs a human approval before it applies. Same
audit trail at every level; they differ only in how much a human must touch a
move.

    L0 manual      — every transition needs approval (a human drives)
    L1 assisted    — every transition needs approval (AI proposes)
    L2 supervised  — transitions into a *gated* step need approval
    L3 autonomous  — no approval; humans are notified out of band
    L4 dark        — no approval; fully lights-out (default)
"""

from __future__ import annotations

LEVELS = ("manual", "assisted", "supervised", "autonomous", "dark")
_ALWAYS = ("manual", "assisted")
_NEVER = ("autonomous", "dark")


def requires_approval(level: str, to_step: str, gates: frozenset[str]) -> bool:
    """Does moving into `to_step` require a recorded approval first?"""
    if level in _ALWAYS:
        return True
    if level in _NEVER:
        return False
    # supervised: only gated steps need sign-off
    return to_step in gates
