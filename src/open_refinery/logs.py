"""Live run logs — a per-work-item log tail streamed over the WS hub.

Logs are ephemeral: an in-process bounded ring buffer per work item (same
single-process ethos as the job runner / scheduler / hub). A harness POSTs log
lines for a run; each is fanned out live over `HUB.publish` (type `log`, keyed by
the work item) and kept in the buffer so a late subscriber can fetch recent
lines. Not persisted — restart clears them; the audit trail remains the durable
record.
"""

from __future__ import annotations

from collections import deque

from .live import HUB
from .models import now_iso

_MAX = 200  # ring-buffer depth per work item
_BUFFERS: dict[str, deque] = {}

LEVELS = ("debug", "info", "warning", "error")


def append_log(item_id: str, line: str, level: str = "info") -> dict:
    """Record + broadcast one log line for a run."""
    if level not in LEVELS:
        level = "info"
    entry = {"subject": item_id, "line": line, "level": level, "at": now_iso()}
    buf = _BUFFERS.setdefault(item_id, deque(maxlen=_MAX))
    buf.append(entry)
    HUB.publish({"type": "log", **entry})
    return entry


def recent_logs(item_id: str) -> list[dict]:
    return list(_BUFFERS.get(item_id, ()))
