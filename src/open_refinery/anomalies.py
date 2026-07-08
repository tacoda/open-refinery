"""Behavioral anomaly detection over the audit trail.

Cheap, dependency-free heuristics that flag the patterns an oversight team wants
to catch *before* the post-mortem: denial spikes, mass changes by one actor,
off-hours agent activity, and a harness running far above the norm. `scan` is
pure (reads events, returns structured findings) and testable; `emit` is the
side-effecting sweep the scheduler runs — it writes an `anomaly` audit event for
each *new* high-severity finding (deduped via a setting) so notification rules
(2.1) can route it. Detection is a signal, never a block.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta

from sqlmodel import Session

from .audit import AuditSink
from .models import now_iso
from .provenance import Record
from .store import query_events
from .users import list_users

# thresholds — deliberately conservative; tune per install if noisy
DENIAL_SPIKE = 5          # denials within the window → spike
MASS_CHANGE = 15          # mutations by one actor within the short window → burst
HARNESS_ABS_MIN = 20      # an agent below this many events is never "over norm"
HARNESS_NORM_MULT = 3     # ...otherwise flag agents above N× the agent median
OFFHOURS_MIN = 3          # this many off-hours agent events → flag

WINDOW_HOURS = 1          # denial-spike / harness-norm lookback
MASS_WINDOW_MIN = 15      # mass-change lookback (tighter — a burst is sudden)
OFFHOURS_WINDOW_HOURS = 24
OFF_HOURS = set(range(0, 6)) | {22, 23}  # UTC night (naive: single-TZ install)

MUTATIONS = {"transition", "rollback", "rollback-applied", "invoke",
             "invoke-failed", "approval", "policy-change"}


def _since(now: str, **delta) -> str:
    return (datetime.fromisoformat(now) - timedelta(**delta)).isoformat()


def _hour(iso: str) -> int:
    return datetime.fromisoformat(iso).hour


def scan(session: Session, now: str | None = None) -> list[dict]:
    """Return structured anomaly findings. Read-only; each detector is isolated."""
    now = now or now_iso()
    agents = {u.id for u in list_users(session, kind="agent")}
    return _denial_spike(session, now) + _mass_change(session, now) + _agent_signals(session, now, agents)


def _f(kind: str, detail: str, actor: str = "", severity: str = "medium") -> dict:
    return {"kind": kind, "severity": severity, "detail": detail, "actor": actor}


def _denial_spike(session: Session, now: str) -> list[dict]:
    n = len(query_events(session, recipe="denied", since=_since(now, hours=WINDOW_HOURS), limit=1000))
    if n < DENIAL_SPIKE:
        return []
    sev = "high" if n >= DENIAL_SPIKE * 3 else "medium"
    return [_f("denial-spike", f"{n} policy denials in the last hour", severity=sev)]


def _mass_change(session: Session, now: str) -> list[dict]:
    recent = query_events(session, since=_since(now, minutes=MASS_WINDOW_MIN), limit=2000)
    burst = Counter(e.actor for e in recent if e.recipe in MUTATIONS)
    return [_f("mass-change", f"{n} changes by {a} in {MASS_WINDOW_MIN} min", a,
               "high" if n >= MASS_CHANGE * 2 else "medium")
            for a, n in burst.items() if n >= MASS_CHANGE]


def _agent_signals(session: Session, now: str, agents: set[str]) -> list[dict]:
    day = query_events(session, since=_since(now, hours=OFFHOURS_WINDOW_HOURS), limit=5000)
    per_agent = Counter(e.actor for e in day if e.actor in agents)
    off_by = Counter(e.actor for e in day if e.actor in agents and _hour(e.created_at) in OFF_HOURS)
    off = [_f("off-hours-agent", f"agent {a} active {n}× during off-hours", a)
           for a, n in off_by.items() if n >= OFFHOURS_MIN]
    return off + _over_norm(per_agent)


def _over_norm(per_agent: Counter) -> list[dict]:
    counts = sorted(per_agent.values())
    if not counts:
        return []
    median = counts[len(counts) // 2]
    ceiling = max(HARNESS_ABS_MIN, median * HARNESS_NORM_MULT)
    return [_f("harness-over-norm", f"agent {a} ran {n} actions (norm ~{median})", a)
            for a, n in per_agent.items() if n > ceiling]


def _signature(f: dict) -> str:
    return f"{f['kind']}:{f['actor']}"


def emit(session: Session, audit: AuditSink, now: str | None = None) -> list[str]:
    """Write an `anomaly` audit event for each new high-severity finding. Dedupe
    off the append-only audit itself: a signature already alerted within the day
    is skipped (the anomaly event's `subject` holds the signature). Returns the
    signatures emitted this run."""
    now = now or now_iso()
    prior = query_events(session, recipe="anomaly", since=_since(now, hours=OFFHOURS_WINDOW_HOURS),
                         limit=1000)
    seen = {e.subject for e in prior}
    fresh = []
    for f in scan(session, now):
        sig = _signature(f)
        if f["severity"] == "high" and sig not in seen:
            audit.write(Record.of(recipe="anomaly", actor="system", owner=f["actor"] or "system",
                                  inputs={"kind": f["kind"], "detail": f["detail"]},
                                  output="flagged", subject=sig))
            seen.add(sig)
            fresh.append(sig)
    return fresh
