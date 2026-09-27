"""Advancing a run by exactly one stage.

The unit is **one stage**, not one run, and that is the whole design: a worker
claims a run, moves it one step, writes back, and lets go. A crash between
stages resumes rather than restarts, because the `Run` row is the durable state
and nothing is held in memory between steps.

Phases are not run here yet — Phase 5 attaches the harness. Until then a phase
stage goes through `stub_phase`, which produces a plausible document section and
nothing else, so the whole graph can be walked end to end before any model is
called.
"""

from __future__ import annotations

from sqlmodel import Session

from ..audit import AuditSink
from ..models import Repository, Run, now_iso
from ..provenance import Record
from . import forge as forgelib
from . import store as ps
from . import workspace as ws
from .actions import Context, perform
from .contracts import BUILT_IN, contract, read as read_contract
from .graph import ERROR, OK, Result, advance, plan_next


class RunnerError(RuntimeError):
    """The run cannot be advanced as configured."""


def context_for(session: Session, run: Run, *, credential: dict | None = None) -> Context:
    """Everything the actions need, assembled from the repository's own config."""
    repo = session.get(Repository, run.repo_id)
    if repo is None:
        raise RunnerError(f"unknown repository: {run.repo_id!r}")

    driver = forgelib.for_repo(repo.git_url, repo.forge)
    return Context(
        checkout=repo.git_url,          # a local repo's URL is its path
        repo_slug=forgelib.slug(repo.git_url),
        base=repo.base_branch or "main",
        forge=driver,
        credential=credential or {},
        prepare_cmd=repo.prepare_cmd,
        cleanup_cmd=repo.cleanup_cmd,
    )


def stub_phase(run: Run, stage, ctx: Context) -> Result:
    """Stand in for a turn until the harness lands.

    Deliberately produces what the stage *says* it produces and nothing more, so
    a graph's `requires` / `produces` wiring is exercised for real. It writes no
    files, which is why a run through the stub reaches `commit_and_push` and is
    correctly told there is no diff.
    """
    return Result(OK, produced=tuple(stage.produces),
                  reason=f"[stub] {stage.phase} would run here")


def _grade(stage, text: str) -> tuple[str, dict]:
    """Apply the stage's contract, if it has one.

    An objecting answer becomes a refusal, so the graph's revision loop handles
    it — a check that objects and is treated as success is a check for nothing.
    """
    if not stage.contract:
        return OK, {}
    spec = contract(stage.contract)
    if not spec:
        return OK, {}
    answer = read_contract(text, spec)
    return (ERROR if answer.objects else OK), answer.as_dict()


def step(session: Session, run: Run, audit: AuditSink, *,
         phase_runner=stub_phase, credential: dict | None = None) -> Run:
    """Advance one run by one stage. Returns the run as it now stands.

    Guards on the run's own recorded stage throughout, so running this twice
    does the work once — which is what makes at-least-once delivery safe.
    """
    if run.outcome:
        return run                      # already finished

    pipeline = ps.get_pipeline(session, run.pipeline_id)
    if pipeline is None:
        raise RunnerError(f"unknown pipeline: {run.pipeline_id!r}")
    graph = ps.graph_of(pipeline)
    state = ps.run_state(run)

    # 1. Should this stage run at all — skipped, held, or ready?
    planned = plan_next(state, graph)
    if planned.skipped:
        ps.record_step(session, run, run.stage, outcome="skipped", why=planned.why)
        return ps.apply_move(session, run, planned)
    if planned.held:
        if not run.held:
            audit.write(Record.of(recipe="run-held", actor=run.actor_id,
                                  owner=run.actor_id, inputs={"stage": run.stage},
                                  output=planned.why, subject=run.id))
        return ps.apply_move(session, run, planned)

    stage = graph.stage(run.stage)
    ctx = context_for(session, run, credential=credential)

    # 2. Do the thing.
    if stage.runs_a_turn:
        if stage.revert_changes:
            # Stage the work first, so reverting the check restores it rather
            # than discarding it.
            path = ws.worktree_path(ctx.checkout, run.id)
            if path.exists():
                ws.snapshot(path)
        result = phase_runner(run, stage, ctx)
        graded, answer = _grade(stage, result.reason or "")
        if graded == ERROR and result.outcome == OK:
            # The contract downgraded a claim its own output did not support.
            result = Result(ERROR, error=answer.get("why", "the contract refused"),
                            produced=result.produced)
        if stage.revert_changes:
            # A check may run; it may not repair.
            path = ws.worktree_path(ctx.checkout, run.id)
            if path.exists():
                ws.revert_changes(path)
    else:
        result = perform(stage.action, _as_dict(run), ctx)
        answer = {}

    # 3. Record what happened, and where the pull request went.
    produced = {name: result.reason or f"({stage.name})" for name in result.produced}
    if stage.action == "open_pull_request" and result.outcome == OK and result.reason:
        number, _, url = result.reason.partition("\t")
        run.pr_number, run.pr_url = number, url
        session.add(run)
        session.commit()
        audit.write(Record.of(recipe="pr-opened", actor=run.actor_id, owner=run.actor_id,
                              inputs={"stage": stage.name}, output=url, subject=run.id))
        produced = {}

    ps.record_step(session, run, stage.name, outcome=result.outcome,
                   why=result.error or result.reason or "", phase=stage.phase,
                   action=stage.action, answer=answer,
                   attempt=run.revisions + 1)

    # 4. Where does it go?
    moved = advance(ps.run_state(run), graph, result)
    updated = ps.apply_move(session, run, moved, produced=produced)

    audit.write(Record.of(
        recipe="run-stage", actor=run.actor_id, owner=run.actor_id,
        inputs={"from": stage.name, "outcome": result.outcome,
                "revisions": moved.revisions},
        output=moved.to, subject=run.id))
    return updated


def _as_dict(run: Run) -> dict:
    """The run as the actions read it — they take a dict, not an ORM object, so
    they stay testable against a bare git repo."""
    return {"id": run.id, "document": run.document, "revisions": run.revisions,
            "pr_number": run.pr_number, "pr_url": run.pr_url}


def drive(session: Session, run: Run, audit: AuditSink, *, limit: int = 20,
          phase_runner=stub_phase, credential: dict | None = None) -> Run:
    """Advance a run until it finishes, is held, or stops moving.

    Bounded, because a pipeline with a cycle and no revision cap is exactly the
    thing that should stop rather than spin. The worker pool in Phase 6 calls
    `step` instead — one stage per claim.
    """
    for _ in range(limit):
        before = (run.stage, run.revisions)
        run = step(session, run, audit, phase_runner=phase_runner, credential=credential)
        if run.outcome or run.held:
            break
        if (run.stage, run.revisions) == before:
            break                       # stopped moving: waiting on something
    return run
