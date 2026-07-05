"""In-process concurrency caps — live in-flight tracking per team.

A team's `max_concurrency` bounds how many governed invokes it may run at once.
Unlike quotas (a windowed *sum*), this is a live *count* of in-flight calls: a
counter is incremented on entry and decremented on exit. Single-process, same
ethos as the job runner / scheduler — a Redis-backed counter can replace it for
multi-process later, same `slot()` API.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager

_LOCK = threading.Lock()
_IN_FLIGHT: dict[str, int] = {}


class ConcurrencyExceeded(Exception):
    """Raised when a team is already at its max concurrent invokes."""


@contextmanager
def slot(team_id: str | None, cap: int):
    """Hold one in-flight slot for a team. `cap<=0` or no team → unlimited.

    Raises `ConcurrencyExceeded` if the team is already at `cap` in-flight calls.
    """
    if not team_id or cap <= 0:
        yield
        return
    with _LOCK:
        if _IN_FLIGHT.get(team_id, 0) >= cap:
            raise ConcurrencyExceeded(
                f"team {team_id!r} at max concurrency ({cap})")
        _IN_FLIGHT[team_id] = _IN_FLIGHT.get(team_id, 0) + 1
    try:
        yield
    finally:
        with _LOCK:
            _IN_FLIGHT[team_id] -= 1
            if _IN_FLIGHT[team_id] <= 0:
                del _IN_FLIGHT[team_id]


def in_flight(team_id: str) -> int:
    with _LOCK:
        return _IN_FLIGHT.get(team_id, 0)
