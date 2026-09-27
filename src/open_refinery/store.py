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


# --- keys ------------------------------------------------------------------
# One SECRET_KEY, three jobs (Fernet encryption, chain integrity, export
# signing). Using it raw for all three means a leak in any one compromises the
# others, so each purpose gets its own derived subkey. Cheap, standard domain
# separation — and `crypto.py` already flagged this as the point to do it.

CHAIN_ALGO = "hmac-sha256-v1"   # what new events are signed with
LEGACY_ALGO = "sha256"          # unkeyed, pre-2.13 — verifiable, not forgeable forward


def _subkey(purpose: bytes) -> bytes:
    secret = (os.environ.get("SECRET_KEY") or "").encode()
    return hmac.new(secret, purpose, hashlib.sha256).digest()


def _sign_state(head: str, algo: str) -> str:
    """Authenticate the chain head — the anchor the whole log hangs from."""
    return hmac.new(_subkey(b"open-refinery/audit-head/v1"),
                    f"{algo}:{head}".encode(), hashlib.sha256).hexdigest()


def _entry_hash(prev_hash: str, e: Event | dict, algo: str = CHAIN_ALGO) -> str:
    """Link one event to the chain.

    The keyed construction is the whole of the tamper resistance: an attacker
    with full write access to the database can still edit a row, but cannot
    recompute the links to match without SECRET_KEY, which lives in the
    environment and never in the store.

    `sha256` is the unkeyed pre-2.13 construction, kept so existing installs
    verify across the upgrade. It is only ever *read* — nothing writes it.
    """
    payload = (prev_hash + _canonical(e)).encode()
    if algo == LEGACY_ALGO:
        return hashlib.sha256(payload).hexdigest()
    return hmac.new(_subkey(b"open-refinery/audit-chain/v1"), payload, hashlib.sha256).hexdigest()

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
            event.chain_algo = CHAIN_ALGO
            event.entry_hash = _entry_hash(state.head, event, CHAIN_ALGO)
            state.head = event.entry_hash
            state.algo = CHAIN_ALGO
            state.signature = _sign_state(state.head, CHAIN_ALGO)
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


def _checkpoint_payload(c) -> str:
    return json.dumps({"kind": c.kind, "created_at": c.created_at, "head": c.head,
                       "cut_to": c.cut_to, "deleted_count": c.deleted_count},
                      sort_keys=True)


def _sign_checkpoint(c) -> str:
    return hmac.new(_subkey(b"open-refinery/audit-checkpoint/v1"),
                    _checkpoint_payload(c).encode(), hashlib.sha256).hexdigest()


def purge_events(session: Session, older_than_days: int) -> int:
    """Delete audit events past the retention window, leaving a signed receipt.

    Retention genuinely requires deleting events, and a deletion leaves a gap in
    the chain that is **indistinguishable from an attacker removing evidence** —
    which is exactly how removing the oldest events used to verify clean. So a
    purge records an `AuditCheckpoint` saying what it removed and where the
    surviving chain now starts, signed with a key the database does not hold.
    `verify_chain` refuses any gap no valid checkpoint accounts for.
    """
    from datetime import datetime, timedelta, timezone

    from .models import AuditCheckpoint

    cutoff = (datetime.now(timezone.utc) - timedelta(days=older_than_days)).isoformat()
    rows = list(session.exec(select(Event).where(Event.created_at < cutoff)))
    if not rows:
        return 0

    with _chain_lock:  # a concurrent write would move the head mid-purge
        survivors = [e for e in session.exec(select(Event)) if e.created_at >= cutoff]
        # Where the chain will start once these are gone. Blank when nothing
        # survives — the whole log went, and the checkpoint says so.
        ordered_survivors = sorted(survivors, key=lambda e: e.created_at)
        cut_to = ordered_survivors[0].prev_hash if ordered_survivors else ""
        head = (session.get(AuditChainState, "head") or AuditChainState()).head

        for e in rows:
            session.delete(e)

        checkpoint = AuditCheckpoint(kind="purge", head=head, cut_to=cut_to,
                                     deleted_count=len(rows))
        if not survivors:  # nothing left to chain to; reset the anchor
            state = session.get(AuditChainState, "head")
            if state is not None:
                state.head, state.algo, state.signature = "", "", ""
                session.add(state)
        checkpoint.signature = _sign_checkpoint(checkpoint)
        session.add(checkpoint)
        session.commit()
    return len(rows)


def _valid_checkpoints(session: Session) -> list:
    """Checkpoints whose signature holds. A forged one — written to excuse a
    deletion — fails here and its gap stays unexplained."""
    from .models import AuditCheckpoint
    out = []
    for c in session.exec(select(AuditCheckpoint)):
        if c.signature and hmac.compare_digest(c.signature, _sign_checkpoint(c)):
            out.append(c)
    return out


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


def _gap_is_explained(session: Session, first: Event) -> bool:
    """Whether a chain starting at `first` has a signed checkpoint accounting
    for whatever came before it."""
    return any(c.cut_to == first.prev_hash for c in _valid_checkpoints(session))


def verify_chain(session: Session) -> dict:
    """Recompute every event's link and walk the chain.

    Returns {ok, count, head, broken_at?}. What this catches, and why each one
    is here — every case below was written as a failing test first:

    - **a forged event**, even with the whole chain recomputed, because the
      links are keyed with a secret the database does not contain
    - **a deleted prefix** — removing the oldest events used to read as a
      legitimate purge and verify clean. A gap now needs a signed checkpoint.
    - **a forged checkpoint** written to excuse a deletion
    - a mid-chain deletion, a truncated tail, and any edited field

    What it cannot catch: someone holding `SECRET_KEY`, and someone who deletes
    the database outright. Off-box mirroring is the answer to the second and is
    on the roadmap; nothing local answers the first.

    A rotated `SECRET_KEY` reports as tampering, because to this function the
    two are the same observation. `doctor` says so in its remedy.
    """
    events = list(session.exec(select(Event)))
    if not events:
        # Everything purged is fine only if a checkpoint says so.
        if _valid_checkpoints(session) or not session.get(AuditChainState, "head"):
            return {"ok": True, "count": 0, "head": ""}
        head = (session.get(AuditChainState, "head") or AuditChainState()).head
        if head:
            return {"ok": False, "count": 0,
                    "broken_at": "unexplained gap (every event deleted, no checkpoint)"}
        return {"ok": True, "count": 0, "head": ""}

    ordered = _ordered_chain(session)
    if len(ordered) != len(events):
        return {"ok": False, "count": len(events), "broken_at": "chain link (fork or gap)"}

    first = ordered[0]
    if first.prev_hash and not _gap_is_explained(session, first):
        return {"ok": False, "count": len(events),
                "broken_at": f"unexplained gap (events deleted before {first.prev_hash[:12]}…)"}

    prev, keyed_yet = first.prev_hash, False
    for e in ordered:
        algo = e.chain_algo or LEGACY_ALGO
        # Algorithm downgrade. Once the chain is keyed it stays keyed: relabelling
        # a row as the old unkeyed construction is the one recomputation an
        # attacker without SECRET_KEY *can* do, so a legacy row appearing after a
        # keyed one is tampering rather than history.
        if keyed_yet and algo == LEGACY_ALGO:
            return {"ok": False, "count": len(events),
                    "broken_at": f"algorithm downgrade at {e.artifact_id}"}
        keyed_yet = keyed_yet or algo == CHAIN_ALGO
        if e.prev_hash != prev or _entry_hash(e.prev_hash, e, algo) != e.entry_hash:
            return {"ok": False, "count": len(events), "broken_at": e.artifact_id}
        prev = e.entry_hash
    state = session.get(AuditChainState, "head") or AuditChainState()
    if state.head and state.head != prev:
        return {"ok": False, "count": len(events), "broken_at": "head mismatch (tail removed)"}
    # The anchor. A rewrite that relabels every row as the legacy construction
    # produces a head the attacker cannot sign, which is what catches the
    # wholesale downgrade the per-row check alone cannot see.
    if state.signature and not hmac.compare_digest(
            state.signature, _sign_state(state.head, state.algo or CHAIN_ALGO)):
        return {"ok": False, "count": len(events),
                "broken_at": "chain head signature does not verify (chain rewritten)"}
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


EXPORT_ALGO = "hmac-sha256 over the full event list"


def _export_signature(rows: list[dict], head: str) -> str:
    """Sign **every exported event**, not just the head.

    Signing the head alone proves nothing about the rows beside it: an attacker
    who rewrote history exports a head they control, with a signature over it
    that verifies perfectly. Covering the list means dropping or editing any
    row invalidates the export.
    """
    payload = json.dumps({"head": head, "events": rows}, sort_keys=True, default=str)
    return hmac.new(_subkey(b"open-refinery/audit-export/v1"),
                    payload.encode(), hashlib.sha256).hexdigest()


def export_chain(session: Session) -> dict:
    """A portable, signed audit export an auditor can verify independently."""
    ordered = _ordered_chain(session)
    rows = [{**{k: getattr(e, k) for k in _CHAIN_FIELDS},
             "prev_hash": e.prev_hash, "entry_hash": e.entry_hash,
             "chain_algo": e.chain_algo or LEGACY_ALGO} for e in ordered]
    head = ordered[-1].entry_hash if ordered else ""
    return {"events": rows, "count": len(rows), "chain_head": head,
            "algorithm": EXPORT_ALGO, "signature": _export_signature(rows, head)}


def verify_export(export: dict) -> dict:
    """Check an export against its signature — the auditor's side of the seam.

    Needs the same `SECRET_KEY` the export was made under, so it runs here or
    anywhere that key is available. Returns {ok, count, reason?}.
    """
    rows = export.get("events") or []
    head = str(export.get("chain_head") or "")
    signature = str(export.get("signature") or "")
    if not signature:
        return {"ok": False, "count": len(rows), "reason": "export carries no signature"}
    if not hmac.compare_digest(signature, _export_signature(rows, head)):
        return {"ok": False, "count": len(rows),
                "reason": "signature does not match the exported events"}
    return {"ok": True, "count": len(rows)}
