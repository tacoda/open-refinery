"""Pipelines and runs, persisted.

The only module in this package that touches the database — everything else is
pure, so the stage machine stays testable without one.

**Saving a pipeline writes a new version rather than editing in place.** A run
pins the version it started under, so an edit never reaches work already in
flight, and the graph a finished run actually followed is still on disk months
later.
"""

from __future__ import annotations

from sqlmodel import Session, select

from ..models import Pipeline, Run, RunStep, User, now_iso
from . import document as doclib
from .graph import Move, Result
from .spec import Graph, GraphError, default_pipeline, parse, to_dict


class UnknownPipeline(LookupError):
    """Raised for a pipeline name or id that does not exist."""


class UnknownRun(LookupError):
    """Raised for a run id that does not exist."""


# --- pipelines --------------------------------------------------------------

def save_pipeline(session: Session, raw: dict, owner_id: str, *,
                  layout: dict | None = None) -> Pipeline:
    """Validate a graph and store it as the next version of its name.

    Validation first, always: a pipeline that cannot be parsed must never reach
    the database, or the next run to pick it up fails somewhere far from here.
    """
    graph = parse(raw)                       # raises GraphError with the bad stage named
    if session.get(User, owner_id) is None:
        raise ValueError(f"unknown owner: {owner_id!r}")

    latest = _latest(session, graph.name)
    row = Pipeline(
        name=graph.name, version=(latest.version + 1) if latest else 1,
        owner_id=owner_id, first=graph.first, terminal=list(graph.terminal),
        model=graph.model, stages=to_dict(graph)["stages"],
        layout=layout if layout is not None else (latest.layout if latest else {}),
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def _latest(session: Session, name: str) -> Pipeline | None:
    return session.exec(
        select(Pipeline).where(Pipeline.name == name)
        .order_by(Pipeline.version.desc())).first()


def get_pipeline(session: Session, pipeline_id: str) -> Pipeline | None:
    return session.get(Pipeline, pipeline_id)


def latest_pipeline(session: Session, name: str) -> Pipeline:
    row = _latest(session, name)
    if row is None:
        raise UnknownPipeline(f"no pipeline named {name!r}")
    return row


def list_pipelines(session: Session, *, all_versions: bool = False) -> list[Pipeline]:
    """The newest version of each pipeline, or every version."""
    rows = list(session.exec(select(Pipeline).order_by(Pipeline.name, Pipeline.version.desc())))
    if all_versions:
        return rows
    seen, out = set(), []
    for row in rows:
        if row.name not in seen:
            seen.add(row.name)
            out.append(row)
    return out


def graph_of(row: Pipeline) -> Graph:
    """The stored row as the graph the machine runs on."""
    return parse({"name": row.name, "first": row.first, "terminal": list(row.terminal),
                  "model": row.model, "stages": row.stages})


def ensure_default(session: Session, owner_id: str) -> Pipeline:
    """Seed `ship-a-ticket` if it is not there — the defaults to build from."""
    try:
        return latest_pipeline(session, "ship-a-ticket")
    except UnknownPipeline:
        return save_pipeline(session, default_pipeline(), owner_id)


# --- runs -------------------------------------------------------------------

def start_run(session: Session, work_item_id: str, pipeline: Pipeline, repo_id: str,
              actor_id: str, *, spec: str = "", opt_in=(), skip=()) -> Run:
    """Begin a run at the pipeline's first stage."""
    graph = graph_of(pipeline)
    run = Run(work_item_id=work_item_id, pipeline_id=pipeline.id,
              pipeline_version=pipeline.version, repo_id=repo_id, actor_id=actor_id,
              stage=graph.first, document=doclib.start(spec).text,
              opt_in=list(opt_in), skip=list(skip))
    session.add(run)
    session.commit()
    session.refresh(run)
    return run


def get_run(session: Session, run_id: str) -> Run | None:
    return session.get(Run, run_id)


def list_runs(session: Session, *, work_item_id: str | None = None,
              actor_id: str | None = None, active: bool | None = None) -> list[Run]:
    stmt = select(Run)
    if work_item_id is not None:
        stmt = stmt.where(Run.work_item_id == work_item_id)
    if actor_id is not None:
        stmt = stmt.where(Run.actor_id == actor_id)
    if active is True:
        stmt = stmt.where(Run.outcome == "")
    elif active is False:
        stmt = stmt.where(Run.outcome != "")
    return list(session.exec(stmt.order_by(Run.created_at.desc())))


def run_state(run: Run) -> dict:
    """The run as the dict the pure machine reads.

    The machine never sees an ORM object, which is what keeps it testable with
    a literal.
    """
    doc = doclib.read(run.document)
    return {"stage": run.stage, "reason": run.reason, "revisions": run.revisions,
            "last_refusal": run.last_refusal, "approved_at": run.approved_at,
            "document": {k: True for k in doc.keys()},
            "opt_in": list(run.opt_in or []), "skip": list(run.skip or [])}


def apply_move(session: Session, run: Run, move: Move, *,
               produced: dict[str, str] | None = None) -> Run:
    """Write a `Move` back to the run. The only place a run's stage changes."""
    if produced:
        doc = doclib.read(run.document)
        for name, body in produced.items():
            doc = doc.with_section(name, body)
        run.document = doc.text

    run.stage = move.to
    run.reason = move.reason
    run.revisions = move.revisions
    run.last_refusal = move.last_refusal
    run.held = move.held
    run.updated_at = now_iso()
    if move.is_terminal_move:
        run.outcome = move.to
    session.add(run)
    session.commit()
    session.refresh(run)
    return run


def record_step(session: Session, run: Run, stage: str, *, outcome: str, why: str,
                phase: str = "", action: str = "", answer: dict | None = None,
                units: int = 0, target_id: str = "", attempt: int = 1) -> RunStep:
    """Append what happened. Never updated — a step is a fact, not a status."""
    step = RunStep(run_id=run.id, stage=stage, phase=phase, action=action,
                   attempt=attempt, outcome=outcome, why=why,
                   answer=answer or {}, units=units, target_id=target_id,
                   finished_at=now_iso())
    session.add(step)
    session.commit()
    session.refresh(step)
    return step


def steps_of(session: Session, run_id: str) -> list[RunStep]:
    return list(session.exec(
        select(RunStep).where(RunStep.run_id == run_id).order_by(RunStep.started_at)))


def approve_run(session: Session, run_id: str, approver_id: str) -> Run:
    """Clear a hold so the stage may proceed. The approval itself is recorded by
    the caller, which owns the audit sink."""
    run = session.get(Run, run_id)
    if run is None:
        raise UnknownRun(run_id)
    run.approved_at = now_iso()
    run.held = False
    run.updated_at = now_iso()
    session.add(run)
    session.commit()
    session.refresh(run)
    return run
