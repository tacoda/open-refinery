"""Workers — the factory floor.

**Parallelism is runs, not turns.** Ten tickets go through the factory at once
because ten runs are in flight, each a clean governed unit — not because one run
was shattered into pieces that have to be reassembled. That also keeps the
worktree claim meaningful: one run, one worktree, one branch, one pull request.

A worker does one thing on each tick:

    claim an actionable run → advance it by ONE stage → release it

The unit is a stage rather than a run, so a worker never holds a run for long
and a crash loses at most the step in flight. Nothing is kept in memory between
ticks: the `Run` row is the durable state, which is what makes resume free.

**The claim is a conditional update**, not a lock file. Two workers cannot take
the same run because the `UPDATE` matches only an unclaimed row, and a crash
leaves a *stale* claim that a later worker can see and take over — where a lock
file would just stay locked.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

from sqlalchemy import update
from sqlmodel import Session, select

from ..audit import AuditSink
from ..concurrency import ConcurrencyExceeded, slot
from ..models import Repository, Run, Team, User, now_iso
from ..provenance import Record
from .runner import RunnerError, step

# How long a claim may sit before another worker may take it over. Longer than
# any single stage should take, and short enough that a crash does not strand a
# run for an afternoon.
STALE_AFTER_SECONDS = 900


def _elapsed(iso: str, now: str) -> float:
    from datetime import datetime
    try:
        return (datetime.fromisoformat(now) - datetime.fromisoformat(iso)).total_seconds()
    except (TypeError, ValueError):
        return float("inf")          # unparseable → treat as stale


def actionable(session: Session, now: str | None = None) -> list[Run]:
    """Runs a worker could pick up, oldest first.

    Not finished, not waiting on a person, and either unclaimed or claimed so
    long ago that whoever held it is gone. Oldest first so a run cannot be
    starved by newer work arriving.
    """
    now = now or now_iso()
    out = []
    for run in session.exec(select(Run).where(Run.outcome == "").order_by(Run.created_at)):
        if run.held:
            continue
        if run.claimed_by and _elapsed(run.claimed_at, now) < STALE_AFTER_SECONDS:
            continue
        out.append(run)
    return out


def claim(session: Session, run_id: str, worker: str, *, now: str | None = None) -> bool:
    """Take a run, if nobody else has it. True when this worker got it.

    A **conditional update**: the WHERE clause is the mutual exclusion, so two
    workers racing for the same run produce one winner and one `False` rather
    than two runs of the same stage. Checking first and then writing would leave
    exactly that gap.
    """
    now = now or now_iso()
    stale_before = _stale_cutoff(now)
    result = session.exec(
        update(Run)
        .where(Run.id == run_id, Run.outcome == "", Run.held == False,  # noqa: E712
               (Run.claimed_by == "") | (Run.claimed_at < stale_before))
        .values(claimed_by=worker, claimed_at=now)
        .execution_options(synchronize_session=False))
    session.commit()
    return bool(result.rowcount)


def _stale_cutoff(now: str) -> str:
    from datetime import datetime, timedelta
    return (datetime.fromisoformat(now)
            - timedelta(seconds=STALE_AFTER_SECONDS)).isoformat()


def release(session: Session, run_id: str) -> None:
    """Give a run back so the next tick can pick it up."""
    session.exec(
        update(Run).where(Run.id == run_id)
        .values(claimed_by="", claimed_at="")
        .execution_options(synchronize_session=False))
    session.commit()


def _cap_for(session: Session, run: Run) -> tuple[str | None, int]:
    """The team whose concurrency cap this run counts against."""
    actor = session.get(User, run.actor_id)
    team = session.get(Team, actor.team_id) if actor and actor.team_id else None
    return (actor.team_id if actor else None), (team.max_concurrency if team else 0)


def oversight_for(session: Session, run: Run) -> str:
    """How closely this run is watched — the repository's setting, not the
    harness's. It lived on the work item's process until 3.0, where it was the
    only field of that record a run ever read."""
    from ..oversight import DEFAULT

    repo = session.get(Repository, run.repo_id)
    return repo.oversight if repo else DEFAULT


@dataclass
class Tick:
    """What one worker did on one tick."""

    run_id: str = ""
    from_stage: str = ""
    to_stage: str = ""
    skipped: bool = False
    error: str = ""

    @property
    def did_work(self) -> bool:
        return bool(self.run_id) and not self.skipped


def tick(session: Session, worker: str, audit: AuditSink, *,
         phase_runner=None, credential_for=None) -> Tick:
    """Claim one run, advance it one stage, release it.

    Always releases — a worker that crashed mid-stage leaves a stale claim
    rather than a permanent one, but a worker that merely *failed* should not
    make anybody wait for the stale window.
    """
    candidates = actionable(session)
    for run in candidates:
        if not claim(session, run.id, worker):
            continue                      # somebody else got there first

        session.refresh(run)
        from_stage = run.stage
        team_id, cap = _cap_for(session, run)
        try:
            with slot(team_id, cap):
                runner = phase_runner or _default_runner(session, run, audit)
                credential = credential_for(session, run) if credential_for else None
                moved = step(session, run, audit, phase_runner=runner,
                             credential=credential)
            return Tick(run_id=run.id, from_stage=from_stage, to_stage=moved.stage)
        except ConcurrencyExceeded:
            # The team is already at its cap. Not an error — try again next tick,
            # and let a run from another team through in the meantime.
            return Tick(run_id=run.id, from_stage=from_stage, skipped=True)
        except RunnerError as exc:
            audit.write(Record.of(
                recipe="run-error", actor=run.actor_id, owner=run.actor_id,
                inputs={"stage": from_stage}, output=str(exc), subject=run.id))
            return Tick(run_id=run.id, from_stage=from_stage, error=str(exc))
        finally:
            release(session, run.id)

    return Tick()                         # nothing to do


def _default_runner(session: Session, run: Run, audit: AuditSink):
    """The harness when the run's owner has a model key, else the offline stub."""
    from .. import credentials as creds
    from ..models_port import provider_of
    from . import store as ps
    from .phases import resolve
    from .runner import harness_phase, stub_phase

    pipeline = ps.get_pipeline(session, run.pipeline_id)
    if pipeline is None:
        return stub_phase
    graph = ps.graph_of(pipeline)
    models = {resolve(session, s.phase).model or graph.model
              for s in graph.stages.values() if s.phase}
    providers = {p.key for p in (provider_of(m) for m in models if m) if p}
    if not providers:
        return stub_phase
    try:
        creds.for_actor(session, run.actor_id, next(iter(providers)))
    except creds.NoCredential:
        return stub_phase
    return harness_phase(session, audit, oversight=oversight_for(session, run))


def drain(session: Session, worker: str, audit: AuditSink, *, limit: int = 50,
          **kw) -> list[Tick]:
    """Tick until there is nothing left to do. For tests and `runs work`."""
    done = []
    for _ in range(limit):
        result = tick(session, worker, audit, **kw)
        if not result.run_id:
            break
        done.append(result)
    return done


# --- the pool ---------------------------------------------------------------

def start_pool(engine, *, workers: int = 2, interval: float = 2.0,
               name: str = "worker") -> list[threading.Thread]:
    """Run N workers on a loop, each in a daemon thread.

    Threads rather than processes, for the same reason the job runner is: one
    `serve` command, no broker to deploy. The claim is a database row, so
    swapping these for separate processes — or a Celery pool — changes nothing
    about correctness.
    """
    from ..store import SqliteSink

    def loop(worker_id: str):
        while True:
            try:
                with Session(engine) as session:
                    result = tick(session, worker_id, SqliteSink(session))
                if result.did_work:
                    continue          # more to do — do not sleep on a busy floor
            except Exception:         # noqa: BLE001 — a bad tick must not kill the worker
                pass
            time.sleep(interval)

    threads = []
    for n in range(max(1, workers)):
        thread = threading.Thread(target=loop, args=(f"{name}-{n}",), daemon=True)
        thread.start()
        threads.append(thread)
    return threads
