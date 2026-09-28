"""Workers — the factory floor.

Parallelism is **runs, not turns**: ten tickets go through at once because ten
runs are in flight, each a clean governed unit. The claim is what makes that
safe, so most of this file is about the claim.
"""

import subprocess
import threading
from datetime import datetime, timedelta, timezone

import pytest

from open_refinery.models import Repository, Run, Team, now_iso
from open_refinery.pipeline import store as ps
from open_refinery.pipeline import workers
from open_refinery.pipeline.graph import OK, Result
from open_refinery.pipeline.workers import (
    STALE_AFTER_SECONDS,
    actionable,
    claim,
    drain,
    release,
    tick,
)
from open_refinery.processes import create_process
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
    _git(root, "config", "user.email", "t@x.io")
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
    process = create_process(session, "flow", "board", ["todo", "done"], user.id)
    pipeline = ps.ensure_default(session, user.id)

    def start(title="Add a thing"):
        item = create_work_item(session, repo.id, process.id, title, user.id)
        run = ps.start_run(session, item.id, pipeline, repo.id, user.id, spec=title)
        ps.approve_run(session, run.id, user.id)      # past the plan gate
        session.refresh(run)
        return run

    return session, start, SqliteSink(session), user, root


def builds_something(r, stage, c):
    from open_refinery.pipeline import workspace as ws
    if stage.phase == "run":
        (ws.worktree_path(c.checkout, r.id) / "x.py").write_text("x = 1\n")
        return Result(OK, produced=tuple(stage.produces), reason="built it")
    if stage.contract == "proven":
        return Result(OK, produced=tuple(stage.produces),
                      reason="PROVEN: yes\n\n$ pytest\n1 passed")
    if stage.contract == "verdict":
        return Result(OK, produced=tuple(stage.produces), reason="VERDICT: pass")
    return Result(OK, produced=tuple(stage.produces), reason=f"[{stage.phase}]")


# --- what is actionable -----------------------------------------------------

def test_a_fresh_run_is_actionable(ctx):
    session, start, *_ = ctx
    run = start()
    assert [r.id for r in actionable(session)] == [run.id]


def test_a_finished_run_is_not(ctx):
    session, start, *_ = ctx
    run = start()
    run.outcome = "landed"
    session.add(run)
    session.commit()
    assert actionable(session) == []


def test_a_run_waiting_on_a_person_is_not(ctx):
    """A worker picking up a held run would advance past the person it is
    waiting for."""
    session, start, *_ = ctx
    run = start()
    run.held = True
    session.add(run)
    session.commit()
    assert actionable(session) == []


def test_the_oldest_run_comes_first(ctx):
    """So a run cannot be starved by newer work arriving."""
    session, start, *_ = ctx
    first, second = start("one"), start("two")
    assert [r.id for r in actionable(session)] == [first.id, second.id]


# --- the claim --------------------------------------------------------------

def test_a_claim_is_exclusive(ctx):
    session, start, *_ = ctx
    run = start()
    assert claim(session, run.id, "worker-a") is True
    assert claim(session, run.id, "worker-b") is False


def test_a_claimed_run_is_not_offered_to_anyone_else(ctx):
    session, start, *_ = ctx
    run = start()
    claim(session, run.id, "worker-a")
    assert actionable(session) == []


def test_releasing_makes_it_available_again(ctx):
    session, start, *_ = ctx
    run = start()
    claim(session, run.id, "worker-a")
    release(session, run.id)
    assert [r.id for r in actionable(session)] == [run.id]


def test_a_stale_claim_can_be_taken_over(ctx):
    """A crash leaves a stale claim that a later worker can see — where a lock
    file would just stay locked."""
    session, start, *_ = ctx
    run = start()
    claim(session, run.id, "worker-that-died")

    long_ago = (datetime.now(timezone.utc)
                - timedelta(seconds=STALE_AFTER_SECONDS + 60)).isoformat()
    run.claimed_at = long_ago
    session.add(run)
    session.commit()

    assert [r.id for r in actionable(session)] == [run.id]
    assert claim(session, run.id, "worker-b") is True


def test_a_fresh_claim_cannot_be_stolen(ctx):
    session, start, *_ = ctx
    run = start()
    claim(session, run.id, "worker-a")
    assert claim(session, run.id, "worker-b") is False


def test_a_finished_run_cannot_be_claimed(ctx):
    session, start, *_ = ctx
    run = start()
    run.outcome = "landed"
    session.add(run)
    session.commit()
    assert claim(session, run.id, "worker-a") is False


def test_racing_workers_produce_one_winner(tmp_path):
    """The claim is the mutual exclusion, so six workers racing for one run
    produce one winner. Checking first and then writing would leave the gap
    between the check and the write.

    Separate sessions on a shared database, because that is what workers are —
    a Session is not thread-safe and sharing one would test nothing.
    """
    url = f"sqlite:///{tmp_path / 'race.db'}"
    setup = connect(url)
    ensure_presets(setup)
    user, _ = create_user(setup, "dev@x.io", "pw", "developer")
    repo = Repository(name="app", git_url=str(tmp_path), owner_id=user.id)
    setup.add(repo)
    setup.commit()
    setup.refresh(repo)
    process = create_process(setup, "flow", "board", ["todo", "done"], user.id)
    item = create_work_item(setup, repo.id, process.id, "T", user.id)
    pipeline = ps.ensure_default(setup, user.id)
    run = ps.start_run(setup, item.id, pipeline, repo.id, user.id)
    setup.close()

    won, barrier = [], threading.Barrier(6)
    lock = threading.Lock()

    def race(name):
        session = connect(url)
        try:
            barrier.wait()               # everyone reaches the claim together
            if claim(session, run.id, name):
                with lock:
                    won.append(name)
        finally:
            session.close()

    threads = [threading.Thread(target=race, args=(f"w{n}",)) for n in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(won) == 1, won


# --- a tick -----------------------------------------------------------------

def test_a_tick_advances_exactly_one_stage(ctx):
    session, start, audit, *_ = ctx
    run = start()
    result = tick(session, "w1", audit, phase_runner=builds_something)

    assert result.run_id == run.id
    assert result.from_stage == "prepare" and result.to_stage == "plan"


def test_a_tick_always_releases_the_run(ctx):
    """A worker that merely failed should not make anybody wait for the stale
    window."""
    session, start, audit, *_ = ctx
    start()
    tick(session, "w1", audit, phase_runner=builds_something)
    assert all(not r.claimed_by for r in actionable(session))


def test_a_tick_with_nothing_to_do_says_so(ctx):
    session, _, audit, *_ = ctx
    assert tick(session, "w1", audit).run_id == ""


def test_draining_drives_a_run_to_a_pull_request(ctx):
    """The whole point: tick after tick, with nothing held in memory between."""
    session, start, audit, _, root = ctx
    run = start()

    drain(session, "w1", audit, phase_runner=builds_something)
    session.refresh(run)

    assert run.stage == "waiting"
    assert run.pr_url


def test_two_runs_both_finish(ctx):
    """Parallelism is runs — each is a clean unit with its own worktree."""
    session, start, audit, _, root = ctx
    first, second = start("one"), start("two")

    drain(session, "w1", audit, phase_runner=builds_something, limit=60)
    session.refresh(first)
    session.refresh(second)

    assert first.stage == "waiting" and second.stage == "waiting"
    assert first.pr_url != second.pr_url


def test_a_run_that_becomes_held_is_left_alone(ctx):
    session, start, audit, user, _ = ctx
    run = start()
    run.approved_at = ""                # un-approve, so the plan gate holds again
    session.add(run)
    session.commit()

    drain(session, "w1", audit, phase_runner=builds_something)
    session.refresh(run)

    assert run.held and run.stage == "plan"


# --- the concurrency cap ----------------------------------------------------

def test_a_team_at_its_cap_is_skipped_not_failed(ctx):
    """Not an error — try again next tick, and let another team through in the
    meantime."""
    session, start, audit, user, _ = ctx
    team = Team(name="t", max_concurrency=1, owner_id=user.id)
    session.add(team)
    session.commit()
    session.refresh(team)
    user.team_id = team.id
    session.add(user)
    session.commit()
    start()

    from open_refinery.concurrency import slot
    with slot(team.id, 1):               # the team's only slot is taken
        result = tick(session, "w1", audit, phase_runner=builds_something)

    assert result.skipped is True and result.error == ""


def test_an_uncapped_team_is_not_limited(ctx):
    session, start, audit, *_ = ctx
    start()
    assert tick(session, "w1", audit, phase_runner=builds_something).skipped is False


# --- what a worker chooses to run -------------------------------------------

def test_a_run_without_a_model_key_uses_the_stub(ctx):
    from open_refinery.pipeline.runner import stub_phase

    session, start, audit, *_ = ctx
    run = start()
    assert workers._default_runner(session, run, audit) is stub_phase


def test_oversight_comes_from_the_work_items_process(ctx):
    """How closely a run is watched is the team's setting, not the harness's."""
    session, start, *_ = ctx
    run = start()
    assert workers.oversight_for(session, run) in ("dark", "supervised",
                                                   "manual", "assisted", "autonomous")
