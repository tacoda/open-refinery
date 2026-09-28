"""Driving a run through the graph, against a real git repository.

This is the first test in the suite where work goes in one end and a pull
request comes out the other. The harness is still a stub — Phase 5 attaches it —
so the phase that would write code writes nothing, and the delivery gate
correctly refuses a run with no diff. That refusal is the point: it proves the
gate is load-bearing rather than decorative.
"""

import subprocess
from pathlib import Path

import pytest

from open_refinery.models import Repository
from open_refinery.pipeline import default_pipeline, parse
from open_refinery.pipeline import store as ps
from open_refinery.pipeline import workspace as ws
from open_refinery.pipeline.graph import OK, Result
from open_refinery.pipeline.runner import drive, step
from open_refinery.store import SqliteSink, connect
from open_refinery.users import create_user, ensure_presets
from open_refinery.work_items import create_work_item


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True)


@pytest.fixture
def ctx(tmp_path):
    root = tmp_path / "app"
    root.mkdir()
    _git(root, "init", "-b", "main")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "T")
    (root / "README.md").write_text("# app\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "first")

    session = connect("sqlite:///:memory:")
    ensure_presets(session)
    user, _ = create_user(session, "dev@x.io", "pw", "developer")
    repo = Repository(name="app", git_url=str(root), owner_id=user.id,
                      base_branch="main", forge="local")
    session.add(repo)
    session.commit()
    session.refresh(repo)

    item = create_work_item(session, repo.id, "Add a login page", user.id)
    pipeline = ps.ensure_default(session, user.id)
    run = ps.start_run(session, item.id, pipeline, repo.id, user.id,
                       spec="Add a login page")
    return session, run, root, SqliteSink(session), user


def writes_a_file(name="login.py", body="print('hi')\n"):
    """A phase runner that actually builds something — what the harness will do."""
    def runner(run, stage, c):
        if stage.phase == "run":
            path = ws.worktree_path(c.checkout, run.id)
            (path / name).write_text(body)
            return Result(OK, produced=tuple(stage.produces),
                          reason=f"wrote {name}")
        if stage.contract == "proven":
            return Result(OK, produced=tuple(stage.produces),
                          reason="PROVEN: yes\n\n$ pytest -q\n1 passed")
        if stage.contract == "verdict":
            return Result(OK, produced=tuple(stage.produces), reason="VERDICT: pass")
        return Result(OK, produced=tuple(stage.produces), reason=f"[{stage.phase}]")
    return runner


# --- one stage at a time ----------------------------------------------------

def test_a_step_advances_exactly_one_stage(ctx):
    session, run, root, audit, _ = ctx
    assert run.stage == "prepare"

    run = step(session, run, audit)
    assert run.stage == "plan"
    assert ws.worktree_path(root, run.id).exists()


def test_the_plan_gate_holds_the_run_for_a_person(ctx):
    """Cheaper than gating the diff — a wrong approach is caught before the run
    phase spends its turn cap."""
    session, run, root, audit, _ = ctx
    run = step(session, run, audit)          # prepare → plan
    run = step(session, run, audit)          # plan is gated

    assert run.held is True and run.stage == "plan"


def test_a_held_run_does_not_move_until_approved(ctx):
    session, run, root, audit, user = ctx
    run = drive(session, run, audit)
    assert run.held and run.stage == "plan"

    ps.approve_run(session, run.id, user.id)
    session.refresh(run)
    run = drive(session, run, audit, phase_runner=writes_a_file())
    assert run.stage != "plan"


# --- the whole way to a pull request ----------------------------------------

def test_a_run_reaches_a_pull_request(ctx):
    """Work in one end, a request for review out the other."""
    session, run, root, audit, user = ctx
    ps.approve_run(session, run.id, user.id)
    session.refresh(run)

    run = drive(session, run, audit, phase_runner=writes_a_file())

    assert run.stage == "waiting"
    assert run.pr_url and Path(run.pr_url).exists()
    assert "Add a login page" in Path(run.pr_url).read_text()


def test_the_request_body_is_the_accumulated_document(ctx):
    session, run, root, audit, user = ctx
    ps.approve_run(session, run.id, user.id)
    session.refresh(run)
    run = drive(session, run, audit, phase_runner=writes_a_file())

    body = Path(run.pr_url).read_text()
    assert "What was asked" in body
    assert "Nothing merges itself" in body


def test_the_work_is_actually_committed(ctx):
    session, run, root, audit, user = ctx
    ps.approve_run(session, run.id, user.id)
    session.refresh(run)
    run = drive(session, run, audit, phase_runner=writes_a_file())

    branch = ws.branch_name(run.id)
    files = ws.git(root, "show", "--name-only", "--format=", branch).out
    assert "login.py" in files


def test_every_stage_is_recorded(ctx):
    session, run, root, audit, user = ctx
    ps.approve_run(session, run.id, user.id)
    session.refresh(run)
    run = drive(session, run, audit, phase_runner=writes_a_file())

    stages = [s.stage for s in ps.steps_of(session, run.id)]
    for expected in ("prepare", "plan", "run", "prove", "review", "commit", "publish"):
        assert expected in stages, expected


def test_the_run_is_audited_end_to_end(ctx):
    session, run, root, audit, user = ctx
    ps.approve_run(session, run.id, user.id)
    session.refresh(run)
    run = drive(session, run, audit, phase_runner=writes_a_file())

    from open_refinery.store import query_events
    recipes = {e.recipe for e in query_events(session, subject=run.id, limit=100)}
    assert "run-stage" in recipes and "pr-opened" in recipes


# --- the gate is load-bearing -----------------------------------------------

def test_a_run_that_builds_nothing_never_reaches_a_pull_request(ctx):
    """The stub phase writes no files, so the delivery gate refuses. A factory
    that shipped an empty branch would look like it worked."""
    session, run, root, audit, user = ctx
    ps.approve_run(session, run.id, user.id)
    session.refresh(run)

    run = drive(session, run, audit)          # the stub builds nothing

    assert run.outcome == "failed"
    assert not run.pr_url


def test_a_contract_downgrade_stops_the_run(ctx):
    """`PROVEN: yes` with no command under it is a claim, not a proof."""
    def claims_without_evidence(r, stage, c):
        if stage.phase == "run":
            (ws.worktree_path(c.checkout, r.id) / "a.py").write_text("x = 1\n")
            return Result(OK, produced=tuple(stage.produces))
        if stage.contract == "proven":
            return Result(OK, produced=tuple(stage.produces),
                          reason="PROVEN: yes\n\nit definitely works")
        return Result(OK, produced=tuple(stage.produces))

    session, run, root, audit, user = ctx
    ps.approve_run(session, run.id, user.id)
    session.refresh(run)
    run = drive(session, run, audit, phase_runner=claims_without_evidence)

    assert run.outcome == "failed"
    proof = [s for s in ps.steps_of(session, run.id) if s.stage == "prove"][0]
    assert proof.answer["downgraded_from"] == "yes"


def test_stepping_a_finished_run_does_nothing(ctx):
    """At-least-once delivery has to do the work once."""
    session, run, root, audit, user = ctx
    run.outcome = "landed"
    session.add(run)
    session.commit()

    before = len(ps.steps_of(session, run.id))
    step(session, run, audit)
    assert len(ps.steps_of(session, run.id)) == before


# --- a check may run, and may not repair ------------------------------------

def test_a_check_cannot_repair_what_it_found(ctx):
    """`prove` reverts what it touched, because a shell can write whatever its
    command line says."""
    def check_tries_to_fix(r, stage, c):
        path = ws.worktree_path(c.checkout, r.id)
        if stage.phase == "run":
            (path / "login.py").write_text("broken\n")
            return Result(OK, produced=tuple(stage.produces))
        if stage.phase == "prove":
            (path / "login.py").write_text("fixed by the check\n")   # not allowed
            (path / "scratch.log").write_text("noise\n")
            return Result(OK, produced=tuple(stage.produces),
                          reason="PROVEN: yes\n\n$ pytest\n1 passed")
        if stage.contract == "verdict":
            return Result(OK, produced=tuple(stage.produces), reason="VERDICT: pass")
        return Result(OK, produced=tuple(stage.produces))

    session, run, root, audit, user = ctx
    ps.approve_run(session, run.id, user.id)
    session.refresh(run)
    run = drive(session, run, audit, phase_runner=check_tries_to_fix)

    branch = ws.branch_name(run.id)
    shipped = ws.git(root, "show", f"{branch}:login.py", check=False).out
    assert shipped.strip() == "broken"          # the check's edit did not ship
    assert "scratch.log" not in ws.git(root, "show", "--name-only", "--format=",
                                       branch).out


def test_reverting_a_check_does_not_destroy_the_work(ctx):
    """The bug this pins: reverting everything uncommitted wipes what the run
    phase just built, and the delivery gate then reports an empty diff."""
    session, run, root, audit, user = ctx
    ps.approve_run(session, run.id, user.id)
    session.refresh(run)
    run = drive(session, run, audit, phase_runner=writes_a_file())

    assert run.stage == "waiting"               # it got all the way
    assert "login.py" in ws.git(root, "show", "--name-only", "--format=",
                                ws.branch_name(run.id)).out
