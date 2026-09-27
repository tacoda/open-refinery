"""Pipelines and runs — defining the factory, and putting work through it.

Reading a pipeline is open: it is the shared shape of how work ships, and a
developer has to see the stages their work moves between. **Changing one is
`approve:factory`** — the stage graph is the factory.

Starting a run is `run:factory`. Approving a held stage is `approve:<layer>` for
whatever that stage is about, which for now is the code being written.
"""

from fastapi import APIRouter

from .. import authority
from .. import credentials as creds_mod
from ..deps import *  # noqa: F401,F403
from ..models import WorkItem
from ..pipeline import GraphError, default_pipeline, parse, template, templates
from ..pipeline import store as ps
from ..pipeline.graph import plan_next, walk
from ..pipeline.runner import RunnerError, drive, step
from ..pipeline.spec import ACTIONS, to_dict
from ..web import *  # noqa: F401,F403

router = APIRouter()


def _view(row) -> dict:
    return {"id": row.id, "name": row.name, "version": row.version,
            "first": row.first, "terminal": list(row.terminal), "model": row.model,
            "stages": row.stages, "layout": row.layout, "created_at": row.created_at}


@router.get("/pipelines")
def get_pipelines(all_versions: bool = False, session: Session = Depends(get_session),
                  _: User = Depends(current_user)):
    """The newest version of each pipeline, or every version.

    Open to anyone signed in: the stage graph is the shared shape of how work
    ships here, and a developer who cannot see it cannot follow their own work.
    """
    return [_view(r) for r in ps.list_pipelines(session, all_versions=all_versions)]


@router.get("/phases")
def get_phases(session: Session = Depends(get_session), _: User = Depends(current_user)):
    """Every phase and what it may do.

    Open to anyone signed in: the tool grant is rung 1 of the ladder, and a
    constraint nobody can read is one nobody can rely on.
    """
    from ..pipeline.phases import catalog
    return catalog(session)


@router.put("/phases/{name}")
def set_phase(name: str, body: PhaseBody, session: Session = Depends(get_session),
              user: User = Depends(approves("harness"))):
    """Change what a turn is allowed to be — the harness, which is the lead's.

    Only what is set here overrides the built-in, so changing a turn cap does
    not silently clear the prompt.
    """
    from ..models import PhaseConfig
    from ..pipeline.phases import ALL_TOOLS, resolve

    unknown = [t for t in (body.tools or []) if t not in ALL_TOOLS]
    if unknown:
        raise HTTPException(status_code=400, detail=f"unknown tools: {unknown}")

    row = session.get(PhaseConfig, name) or PhaseConfig(name=name)
    for field in ("prompt", "model", "thinking", "max_turns", "tools", "subagents"):
        value = getattr(body, field)
        if value is not None:
            setattr(row, field, value)
    row.updated_by = user.id
    session.add(row)
    session.commit()

    effective = resolve(session, name)
    SqliteSink(session).write(Record.of(
        recipe="phase-changed", actor=user.id, owner=user.id,
        inputs={"tools": list(effective.tools), "model": effective.model,
                "max_turns": effective.max_turns},
        output=name, subject=name))
    return {"name": name, "tools": list(effective.tools), "model": effective.model,
            "thinking": effective.thinking, "max_turns": effective.max_turns,
            "may_edit": effective.may_edit, "may_run": effective.may_run}


@router.get("/pipelines/actions")
def get_actions(_: User = Depends(current_user)):
    """What a stage can do when it is not running a phase — for the canvas
    palette, and so an unknown action is a validation error rather than a
    silent no-op."""
    return [{"action": name, "does": does} for name, does in sorted(ACTIONS.items())]


@router.post("/pipelines/validate")
def validate_pipeline(body: PipelineBody, _: User = Depends(current_user)):
    """Check a graph without saving it — what the canvas calls on every edit.

    Errors name the offending **stage**, because an error naming a JSON path is
    an error somebody ignores.
    """
    try:
        graph = parse(body.model_dump(exclude_none=True))
    except GraphError as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "stages": len(graph.stages), "path": walk(graph),
            "states": list(graph.states())}


@router.post("/pipelines", status_code=201)
def save_pipeline(body: PipelineBody, session: Session = Depends(get_session),
                  user: User = Depends(approves("factory"))):
    """Save a pipeline as the next version of its name.

    Never an edit in place: a run pins the version it started under, so this
    cannot reach work already in flight.
    """
    try:
        row = ps.save_pipeline(session, body.model_dump(exclude_none=True), user.id,
                               layout=body.layout)
    except GraphError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    SqliteSink(session).write(Record.of(
        recipe="pipeline-saved", actor=user.id, owner=user.id,
        inputs={"version": row.version, "stages": list(row.stages)},
        output=row.name, subject=row.id))
    return _view(row)


@router.get("/pipelines/templates")
def get_templates(_: User = Depends(current_user)):
    """The defaults to build from — each saying what it **gives up**, because a
    template chosen without knowing that is a decision nobody made."""
    return templates()


@router.get("/pipelines/templates/default")
def get_default_template(_: User = Depends(current_user)):
    """`ship-a-ticket` — the one a team gets before configuring anything."""
    return default_pipeline()


@router.get("/pipelines/templates/{name}")
def get_template(name: str, _: User = Depends(current_user)):
    try:
        return template(name)
    except GraphError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# NOTE: these sit ABOVE `/pipelines/{pipeline_id}` on purpose. FastAPI matches in
# declaration order, so a catch-all path parameter declared first swallows every
# literal below it — `/pipelines/templates` was being read as a pipeline id.
@router.get("/pipelines/{pipeline_id}")
def get_pipeline(pipeline_id: str, session: Session = Depends(get_session),
                 _: User = Depends(current_user)):
    row = ps.get_pipeline(session, pipeline_id)
    if row is None:
        raise HTTPException(status_code=404, detail="unknown pipeline")
    return _view(row)


@router.get("/pipelines/{pipeline_id}/export")
def export_pipeline(pipeline_id: str, session: Session = Depends(get_session),
                    _: User = Depends(current_user)):
    """The pipeline as the document it was written as — so it can be reviewed
    in a pull request, without any state living outside the database."""
    row = ps.get_pipeline(session, pipeline_id)
    if row is None:
        raise HTTPException(status_code=404, detail="unknown pipeline")
    return to_dict(ps.graph_of(row))


# --- runs -------------------------------------------------------------------

def _run_view(session, run) -> dict:
    return {"id": run.id, "work_item_id": run.work_item_id,
            "pipeline_id": run.pipeline_id, "pipeline_version": run.pipeline_version,
            "stage": run.stage, "reason": run.reason, "revisions": run.revisions,
            "held": run.held, "outcome": run.outcome, "pr_url": run.pr_url,
            "document": run.document, "created_at": run.created_at,
            "steps": [{"stage": s.stage, "outcome": s.outcome, "why": s.why,
                       "attempt": s.attempt, "answer": s.answer, "units": s.units}
                      for s in ps.steps_of(session, run.id)]}


@router.post("/runs", status_code=201)
def start_run(body: NewRun, session: Session = Depends(get_session),
              user: User = Depends(may_run)):
    """Put a work item through a pipeline."""
    item = session.get(WorkItem, body.work_item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="unknown work item")
    try:
        pipeline = (ps.get_pipeline(session, body.pipeline_id) if body.pipeline_id
                    else ps.latest_pipeline(session, body.pipeline or "ship-a-ticket"))
    except ps.UnknownPipeline as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if pipeline is None:
        raise HTTPException(status_code=404, detail="unknown pipeline")

    run = ps.start_run(session, item.id, pipeline, item.repo_id, user.id,
                       spec=body.spec or item.title,
                       opt_in=body.opt_in, skip=body.skip)
    SqliteSink(session).write(Record.of(
        recipe="run-started", actor=user.id, owner=user.id,
        inputs={"pipeline": pipeline.name, "version": pipeline.version,
                "work_item": item.id},
        output=run.stage, subject=run.id))
    return _run_view(session, run)


@router.get("/runs")
def get_runs(work_item_id: str | None = None, active: bool | None = None,
             session: Session = Depends(get_session), user: User = Depends(current_user)):
    """Your runs, or everyone's with `see:operations`."""
    scope = None if authority.sees_operations(user) else user.id
    return [_run_view(session, r) for r in
            ps.list_runs(session, work_item_id=work_item_id, actor_id=scope,
                         active=active)]


@router.get("/runs/{run_id}")
def get_run(run_id: str, session: Session = Depends(get_session),
            user: User = Depends(current_user)):
    run = ps.get_run(session, run_id)
    if run is None or (run.actor_id != user.id and not authority.sees_operations(user)):
        raise HTTPException(status_code=404, detail="unknown run")
    return _run_view(session, run)


@router.get("/runs/{run_id}/next")
def what_happens_next(run_id: str, session: Session = Depends(get_session),
                      user: User = Depends(current_user)):
    """What the machine would do at this stage — skip it, hold it, or go.

    Pure, so this answers without touching anything.
    """
    run = ps.get_run(session, run_id)
    if run is None or (run.actor_id != user.id and not authority.sees_operations(user)):
        raise HTTPException(status_code=404, detail="unknown run")
    pipeline = ps.get_pipeline(session, run.pipeline_id)
    move = plan_next(ps.run_state(run), ps.graph_of(pipeline))
    return {"to": move.to, "why": move.why, "held": move.held, "skipped": move.skipped}


@router.post("/runs/{run_id}/approve")
def approve_held_run(run_id: str, session: Session = Depends(get_session),
                     user: User = Depends(current_user)):
    """Clear a held stage. Needs `approve:code` — the gate is over the work."""
    run = ps.get_run(session, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="unknown run")
    if not authority.may_approve(user, "code"):
        who = authority.approvers_of(session, "code")
        hint = f" — ask {', '.join(who[:3])}" if who else ""
        raise HTTPException(status_code=403,
                            detail=f"you do not hold approve:code{hint}")
    if run.actor_id == user.id:
        raise HTTPException(status_code=403,
                            detail="you cannot approve your own run")

    updated = ps.approve_run(session, run_id, user.id)
    SqliteSink(session).write(Record.of(
        recipe="run-approved", actor=user.id, owner=run.actor_id,
        inputs={"stage": run.stage}, output="approved", subject=run_id))
    return _run_view(session, updated)


@router.post("/runs/{run_id}/advance")
def advance_run(run_id: str, all_the_way: bool = False,
                session: Session = Depends(get_session),
                user: User = Depends(may_run)):
    """Move a run forward — one stage, or until it stops.

    Phase 6 replaces this with a pool of workers claiming runs on a tick. Until
    then it is here so a run can be driven by hand, which is also how you watch
    a pipeline behave before trusting it to a worker.
    """
    run = ps.get_run(session, run_id)
    if run is None or (run.actor_id != user.id and not authority.sees_operations(user)):
        raise HTTPException(status_code=404, detail="unknown run")
    if run.outcome:
        return _run_view(session, run)
    if run.held:
        raise HTTPException(status_code=409,
                            detail=f"{run.stage} is waiting on a person — approve it first")

    # The runner uses the *run owner's* credentials, so a pull request is
    # authored by whoever is accountable for the work.
    try:
        credential = _forge_credential(session, run)
    except creds_mod.NoCredential as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Use the real harness when this person has a model key, and the stub when
    # they do not — so a fresh install can walk the whole graph offline, and
    # connecting a key is the only thing that has to change to make it real.
    phase_runner = _phase_runner(session, run)

    try:
        move = drive if all_the_way else step
        updated = move(session, run, SqliteSink(session), credential=credential,
                       phase_runner=phase_runner)
    except RunnerError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _run_view(session, updated)


def _phase_runner(session, run):
    """The harness if a model is connected, else the offline stub."""
    from ..models import Process, WorkItem
    from ..pipeline.runner import harness_phase, stub_phase

    pipeline = ps.get_pipeline(session, run.pipeline_id)
    graph = ps.graph_of(pipeline) if pipeline else None
    wanted = _model_of(graph, session, run)
    if not wanted:
        return stub_phase
    try:
        creds_mod.for_actor(session, run.actor_id, wanted)
    except creds_mod.NoCredential:
        return stub_phase

    # Oversight comes from the work item's process, so how closely a run is
    # watched is the team's setting rather than the harness's.
    item = session.get(WorkItem, run.work_item_id)
    process = session.get(Process, item.process_id) if item else None
    level = process.oversight if process else "supervised"
    return harness_phase(session, SqliteSink(session), oversight=level)


def _model_of(graph, session, run) -> str:
    """Which provider this run's phases would need a key for."""
    from ..pipeline.agent import _provider_of
    from ..pipeline.phases import resolve

    if graph is None:
        return ""
    models = {resolve(session, s.phase).model or graph.model
              for s in graph.stages.values() if s.phase}
    providers = {_provider_of(m) for m in models if m}
    return next(iter(providers), "")


def _forge_credential(session, run) -> dict:
    """The run owner's key for this repository's forge.

    `local` needs none, which is what makes it the path that works before
    anybody has connected anything.
    """
    from ..models import Repository
    from ..pipeline import forge as forgelib

    repo = session.get(Repository, run.repo_id)
    driver = forgelib.for_repo(repo.git_url if repo else "", repo.forge if repo else "")
    if driver.name == "local":
        return {}
    return creds_mod.for_actor(session, run.actor_id, driver.name)
