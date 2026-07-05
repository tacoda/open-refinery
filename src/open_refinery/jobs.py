"""Background jobs — run long work off the request path, keep the UI snappy.

An in-process, thread-based runner (zero new dependencies — the single `serve`
process handles it). `enqueue` records a `Job`, returns immediately, and runs the
work in a daemon thread with its own DB `Session`; poll `get_job` for status +
result. The work function takes a `Session` and returns a JSON-serializable dict.

This is a **port**: a Celery/RQ-backed runner can slot in later for horizontal
scale (see PLAN) — the API (`enqueue`/`get_job`) stays the same. For now the
in-process runner keeps deployment to one command.
"""

from __future__ import annotations

import threading

from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from .models import Job, now_iso


def create_job(session: Session, kind: str) -> Job:
    job = Job(kind=kind)
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def run_job(engine: Engine, job_id: str, fn) -> None:
    """Execute a job synchronously in its own Session (the thread body)."""
    with Session(engine) as session:
        job = session.get(Job, job_id)
        if job is None:
            return
        job.status = "running"
        job.updated_at = now_iso()
        session.add(job)
        session.commit()
        try:
            result = fn(session) or {}
            job.status, job.result = "done", result
        except Exception as exc:  # record the failure, don't crash the worker thread
            job.status, job.error = "failed", str(exc)
        job.updated_at = now_iso()
        session.add(job)
        session.commit()
        from .live import HUB
        HUB.publish({"type": "job", "id": job.id, "kind": job.kind, "status": job.status})


def enqueue(session: Session, engine: Engine, kind: str, fn) -> Job:
    """Record a job (pending) and run it in a background thread. Returns at once."""
    job = create_job(session, kind)
    threading.Thread(target=run_job, args=(engine, job.id, fn), daemon=True).start()
    return job


def get_job(session: Session, job_id: str) -> Job | None:
    return session.get(Job, job_id)


def list_jobs(session: Session, *, limit: int = 50) -> list[Job]:
    return list(session.exec(select(Job).order_by(Job.created_at.desc()).limit(limit)))
