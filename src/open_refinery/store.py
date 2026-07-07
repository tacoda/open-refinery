"""Database engine, sessions, and the durable audit sink — SQLModel over SQLite.

`connect()` builds an engine, creates tables from the SQLModel metadata, runs
pending migrations, and returns a `Session`. `engine_for()` exposes the engine
for the web layer's per-request sessions. Only SQLite is wired today; the ORM
keeps other backends within reach.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import threading
from pathlib import Path

from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from . import models  # noqa: F401 — import registers tables in SQLModel.metadata
from .audit import AuditSink, MemorySink  # noqa: F401 — re-exported for convenience
from .models import AuditChainState, Event
from .provenance import Record

# The hashed fields — the immutable record. prev_hash/entry_hash are excluded.
_CHAIN_FIELDS = ("artifact_id", "recipe", "actor", "owner", "input_digest",
                 "output_digest", "subject", "created_at")
_chain_lock = threading.Lock()  # single-process: serialize chain appends


def _canonical(e: Event | dict) -> str:
    d = e if isinstance(e, dict) else e.__dict__
    return json.dumps({k: d.get(k) for k in _CHAIN_FIELDS}, sort_keys=True, default=str)


def _entry_hash(prev_hash: str, e: Event | dict) -> str:
    return hashlib.sha256((prev_hash + _canonical(e)).encode()).hexdigest()

DEFAULT_DATABASE_URL = "sqlite:///open-refinery.db"


def _sqlite_path(database_url: str) -> str | None:
    prefix = "sqlite:///"
    return database_url[len(prefix):] if database_url.startswith(prefix) else None


def engine_for(database_url: str = DEFAULT_DATABASE_URL) -> Engine:
    """Build an engine and ensure its schema + migrations are applied."""
    if not database_url.startswith("sqlite"):
        raise ValueError(f"unsupported DATABASE_URL: {database_url!r} (sqlite only)")
    path = _sqlite_path(database_url)
    if path and path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    kwargs: dict = {"connect_args": {"check_same_thread": False}}
    if path == ":memory:":  # keep one shared in-memory DB across sessions
        kwargs["poolclass"] = StaticPool
    engine = create_engine(database_url, **kwargs)
    _init_schema(engine)
    return engine


def _init_schema(engine: Engine) -> None:
    from .migrations import run_migrations, stamp_latest

    raw = engine.raw_connection()
    try:
        fresh = raw.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='events'"
        ).fetchone() is None
    finally:
        raw.close()

    SQLModel.metadata.create_all(engine)

    raw = engine.raw_connection()
    try:
        raw.execute("PRAGMA foreign_keys=ON")
        stamp_latest(raw) if fresh else run_migrations(raw)
    finally:
        raw.close()

    # Roles are load-bearing (create_user validates against them) — seed the
    # default ladder before anything creates a user.
    from .users import ensure_default_roles
    with Session(engine) as s:
        ensure_default_roles(s)
        _backfill_chain(s)  # chain any pre-2.3 events so upgraded installs verify


def _backfill_chain(session: Session) -> None:
    """One-time: hash-chain events that predate the tamper-evident chain, in
    created_at order, establishing the baseline head. No-op once chained."""
    unchained = list(session.exec(select(Event).where(Event.entry_hash == "")
                                  .order_by(Event.created_at)))
    if not unchained:
        return
    state = session.get(AuditChainState, "head") or AuditChainState(id="head", head="")
    for e in unchained:
        e.prev_hash = state.head
        e.entry_hash = _entry_hash(state.head, e)
        state.head = e.entry_hash
        session.add(e)
    session.add(state)
    session.commit()


def connect(database_url: str = DEFAULT_DATABASE_URL, *, check_same_thread: bool = True) -> Session:
    """Open the store (schema + migrations applied) and return a Session."""
    return Session(engine_for(database_url))


# --- durable audit sink ---------------------------------------------------

class SqlSink:
    """Durable AuditSink — persists each event via the session."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def write(self, record: Record) -> None:
        event = Event(**record.to_dict())
        with _chain_lock:  # link into the tamper-evident chain
            state = self._session.get(AuditChainState, "head") or AuditChainState(id="head", head="")
            event.prev_hash = state.head
            event.entry_hash = _entry_hash(state.head, event)
            state.head = event.entry_hash
            self._session.add(event)
            self._session.add(state)
            self._session.commit()
        from .webhooks import deliver
        deliver(self._session, record)  # fan out to registered endpoints (best-effort)
        from .notifications import dispatch
        dispatch(self._session, record)  # governance alert rules (best-effort)
        from .live import HUB
        HUB.publish({"type": "event", "recipe": record.recipe, "actor": record.actor,
                     "subject": record.subject, "at": record.created_at})


# Backwards-compatible alias — the SQL-backed sink used to be SqliteSink.
SqliteSink = SqlSink


def purge_events(session: Session, older_than_days: int) -> int:
    """Delete audit events older than the retention window. Returns how many went."""
    from datetime import datetime, timedelta, timezone
    cutoff = (datetime.now(timezone.utc) - timedelta(days=older_than_days)).isoformat()
    rows = list(session.exec(select(Event).where(Event.created_at < cutoff)))
    for e in rows:
        session.delete(e)
    session.commit()
    return len(rows)


def query_events(
    session: Session,
    *,
    actor: str | None = None,
    recipe: str | None = None,
    owner: str | None = None,
    subject: str | None = None,
    since: str | None = None,
    until: str | None = None,
    limit: int = 100,
) -> list[Event]:
    """Query the audit trail, newest first. Filters combine with AND."""
    stmt = select(Event)
    if actor is not None:
        stmt = stmt.where(Event.actor == actor)
    if recipe is not None:
        stmt = stmt.where(Event.recipe == recipe)
    if owner is not None:
        stmt = stmt.where(Event.owner == owner)
    if subject is not None:
        stmt = stmt.where(Event.subject == subject)
    if since is not None:
        stmt = stmt.where(Event.created_at >= since)
    if until is not None:
        stmt = stmt.where(Event.created_at <= until)
    stmt = stmt.order_by(Event.created_at.desc()).limit(limit)
    return list(session.exec(stmt))


# --- tamper-evident chain: verify + signed export ------------------------

def _ordered_chain(session: Session) -> list[Event]:
    """Reconstruct the audit events in chain order by following prev→entry links.
    Robust to purge (an earlier segment removed) — starts at the earliest event
    whose prev_hash is no longer present."""
    events = list(session.exec(select(Event)))
    by_prev = {e.prev_hash: e for e in events}
    entries = {e.entry_hash for e in events}
    starts = [e for e in events if e.prev_hash not in entries]  # genesis or post-purge head
    if len(starts) != 1:
        return events  # forked/ambiguous — verify() will report the break
    ordered, cur = [], starts[0]
    seen = set()
    while cur is not None and cur.entry_hash not in seen:
        ordered.append(cur)
        seen.add(cur.entry_hash)
        cur = by_prev.get(cur.entry_hash)
    return ordered


def verify_chain(session: Session) -> dict:
    """Recompute every event's hash and walk the links. Any edit, insertion, or
    mid-chain deletion breaks it. Returns {ok, count, head, broken_at?}."""
    events = list(session.exec(select(Event)))
    if not events:
        return {"ok": True, "count": 0, "head": ""}
    ordered = _ordered_chain(session)
    if len(ordered) != len(events):
        return {"ok": False, "count": len(events), "broken_at": "chain link (fork or gap)"}
    prev = ordered[0].prev_hash
    for e in ordered:
        if e.prev_hash != prev or _entry_hash(e.prev_hash, e) != e.entry_hash:
            return {"ok": False, "count": len(events), "broken_at": e.artifact_id}
        prev = e.entry_hash
    head = (session.get(AuditChainState, "head") or AuditChainState()).head
    if head and head != prev:
        return {"ok": False, "count": len(events), "broken_at": "head mismatch (tail removed)"}
    return {"ok": True, "count": len(events), "head": prev}


_CSV_COLS = ("created_at", "recipe", "actor", "owner", "subject",
             "input_digest", "output_digest", "prev_hash", "entry_hash")


def events_csv(session: Session, **filters) -> str:
    """The (optionally filtered) audit trail as CSV — for spreadsheets/auditors.
    Includes the chain hashes so an exported sheet is still tamper-evident."""
    import csv
    import io
    rows = query_events(session, **filters)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(_CSV_COLS)
    for e in rows:
        w.writerow([getattr(e, c) if getattr(e, c) is not None else "" for c in _CSV_COLS])
    return buf.getvalue()


def _sign(payload: str) -> str:
    key = (os.environ.get("SECRET_KEY") or "").encode()
    return hmac.new(key, payload.encode(), hashlib.sha256).hexdigest()


def export_chain(session: Session) -> dict:
    """A portable, signed audit export an external auditor can verify independently:
    recompute the hash chain, then check the HMAC over the head with SECRET_KEY."""
    ordered = _ordered_chain(session)
    rows = [{**{k: getattr(e, k) for k in _CHAIN_FIELDS},
             "prev_hash": e.prev_hash, "entry_hash": e.entry_hash} for e in ordered]
    head = ordered[-1].entry_hash if ordered else ""
    return {"events": rows, "count": len(rows), "chain_head": head,
            "algorithm": "sha256 chain + hmac-sha256(SECRET_KEY) over head",
            "signature": _sign(head)}
