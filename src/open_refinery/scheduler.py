"""Scheduled ingest — auto-ingest repos on a cadence, off the request path.

A repo with `ingest_interval_hours > 0` is re-ingested automatically. The due
check is pure (`due_repos`) and testable; `run_due_ingests` enqueues a background
ingest job (see `jobs`) for each due repo and stamps `last_ingest_at`. A thin
daemon loop (`start_scheduler`) calls `run_due_ingests` on an interval — started
only on the `serve` path, never in tests.

In-process, zero-dep — same ethos as the job runner. A cron/Celery-beat backend
can replace the loop later without changing `run_due_ingests`.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime

from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from .ingest import ingest
from .jobs import enqueue
from .models import Repository, now_iso


def _due(repo: Repository, now: str) -> bool:
    if repo.ingest_interval_hours <= 0:
        return False
    if not repo.last_ingest_at:
        return True
    elapsed = (datetime.fromisoformat(now) - datetime.fromisoformat(repo.last_ingest_at)).total_seconds()
    return elapsed >= repo.ingest_interval_hours * 3600


def due_repos(session: Session, now: str | None = None) -> list[Repository]:
    now = now or now_iso()
    return [r for r in session.exec(select(Repository)) if _due(r, now)]


def run_due_ingests(session: Session, engine: Engine, now: str | None = None) -> list[str]:
    """Enqueue a background ingest for every due repo; stamp last_ingest_at.
    Returns the repo ids scheduled."""
    now = now or now_iso()
    scheduled = []
    for repo in due_repos(session, now):
        rid, uid = repo.id, repo.owner_id
        enqueue(session, engine, f"ingest:{rid}", lambda s, rid=rid, uid=uid: ingest(s, rid, uid))
        repo.last_ingest_at = now
        session.add(repo)
        scheduled.append(rid)
    session.commit()
    return scheduled


def start_scheduler(engine: Engine, *, interval_seconds: int = 300) -> threading.Thread:
    """Run `run_due_ingests` and the overdue-approval escalation sweep on a loop
    in a daemon thread (the serve path)."""
    from .anomalies import emit as emit_anomalies
    from .escalations import escalate_overdue
    from .store import SqliteSink

    def _loop():
        while True:
            try:
                with Session(engine) as session:
                    run_due_ingests(session, engine)
                    escalate_overdue(session, SqliteSink(session))
                    emit_anomalies(session, SqliteSink(session))
            except Exception:  # a bad tick must not kill the scheduler
                pass
            time.sleep(interval_seconds)

    t = threading.Thread(target=_loop, daemon=True)
    t.start()
    return t
