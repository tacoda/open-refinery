"""Spend ceilings, and the metering that makes them mean anything.

Until 3.0 the product had a quota mechanism that governed `POST /execute` — a
call site the factory never used — while the factory itself had no cost ceiling
at all and `pipeline/middleware.py` documented one it did not perform. These
tests are about the ceiling that now exists.
"""

import pytest

from open_refinery import (
    BudgetExceeded,
    check_budget,
    connect,
    create_budget,
    create_repository,
    create_user,
    create_work_item,
    list_budgets,
    spend_by_run,
    spend_of,
)
from open_refinery.budgets import charge
from open_refinery.pipeline import store as ps


def setup(**repo_kwargs):
    conn = connect("sqlite:///:memory:")
    dev, _ = create_user(conn, "dev@x.dev", "pw", "developer")
    repo = create_repository(conn, "or", "git@x:or.git", dev.id)
    for k, v in repo_kwargs.items():
        setattr(repo, k, v)
    conn.add(repo); conn.commit()
    item = create_work_item(conn, repo.id, "T", dev.id)
    pipeline = ps.ensure_default(conn, dev.id)
    run = ps.start_run(conn, item.id, pipeline, repo.id, dev.id, spec="do it")
    return conn, dev, repo, run


# --- metering ---------------------------------------------------------------

def test_a_runs_spend_is_the_sum_of_its_steps():
    conn, _, _, run = setup()
    assert spend_of(conn, run.id) == 0
    ps.record_step(conn, run, "plan", outcome="ok", why="", units=120)
    ps.record_step(conn, run, "run", outcome="ok", why="", units=380)
    assert spend_of(conn, run.id) == 500


def test_spend_by_run_reports_each_run_and_scopes_to_an_actor():
    conn, dev, repo, run = setup()
    ps.record_step(conn, run, "plan", outcome="ok", why="", units=42)

    other, _ = create_user(conn, "other@x.dev", "pw", "developer")
    item2 = create_work_item(conn, repo.id, "U", other.id)
    pipeline = ps.ensure_default(conn, other.id)
    run2 = ps.start_run(conn, item2.id, pipeline, repo.id, other.id, spec="x")
    ps.record_step(conn, run2, "plan", outcome="ok", why="", units=8)

    everyone = {r["run_id"]: r["units"] for r in spend_by_run(conn)}
    assert everyone == {run.id: 42, run2.id: 8}
    mine = {r["run_id"]: r["units"] for r in spend_by_run(conn, actor_id=dev.id)}
    assert mine == {run.id: 42}


# --- the per-run ceiling ----------------------------------------------------

def test_no_ceiling_by_default():
    conn, _, _, run = setup()
    ps.record_step(conn, run, "run", outcome="ok", why="", units=10 ** 9)
    check_budget(conn, run)          # 0 means unlimited; does not raise


def test_a_run_past_its_repositorys_ceiling_is_refused():
    conn, _, repo, run = setup(max_run_units=500)
    ps.record_step(conn, run, "plan", outcome="ok", why="", units=300)
    check_budget(conn, run)          # still under

    ps.record_step(conn, run, "run", outcome="ok", why="", units=250)
    with pytest.raises(BudgetExceeded, match="550 of its 500-unit ceiling"):
        check_budget(conn, run)


def test_the_refusal_says_what_to_do_about_it():
    """A ceiling nobody can act on is a dead end, not a control."""
    conn, _, _, run = setup(max_run_units=10)
    ps.record_step(conn, run, "run", outcome="ok", why="", units=11)
    with pytest.raises(BudgetExceeded, match="Raise the repository's max_run_units"):
        check_budget(conn, run)


# --- shared budgets ---------------------------------------------------------

def test_an_org_budget_covers_every_run():
    conn, dev, _, run = setup()
    create_budget(conn, "org", 100, dev.id)
    charge(conn, run, 100)
    with pytest.raises(BudgetExceeded, match="the org budget is exhausted"):
        check_budget(conn, run)


def test_a_repo_budget_only_covers_its_own_repository():
    conn, dev, repo, run = setup()
    other = create_repository(conn, "other", "git@x:other.git", dev.id)
    create_budget(conn, "repo", 50, dev.id, scope_id=other.id)
    charge(conn, run, 10_000)        # charged to nothing: no budget matches
    check_budget(conn, run)
    assert [b.used for b in list_budgets(conn)] == [0]


def test_a_team_budget_follows_the_actor():
    from open_refinery import create_team, set_user_team

    conn, dev, _, run = setup()
    team = create_team(conn, "core", dev.id)
    create_budget(conn, "team", 30, dev.id, scope_id=team.id)
    charge(conn, run, 30)
    check_budget(conn, run)          # dev is not on the team yet

    set_user_team(conn, dev.id, team.id)
    charge(conn, run, 30)
    with pytest.raises(BudgetExceeded, match="the team .* budget is exhausted"):
        check_budget(conn, run)


def test_a_window_rolls_and_a_lifetime_cap_does_not():
    conn, dev, _, run = setup()
    rolling = create_budget(conn, "org", 10, dev.id, window_seconds=60)
    charge(conn, run, 10)
    with pytest.raises(BudgetExceeded):
        check_budget(conn, run)

    # wind the window back past its length: the next check rolls it
    from datetime import datetime, timedelta, timezone
    rolling.window_started_at = (datetime.now(timezone.utc) - timedelta(seconds=120)).isoformat()
    conn.add(rolling); conn.commit()
    check_budget(conn, run)
    assert conn.get(type(rolling), rolling.id).used == 0


def test_charging_nothing_changes_nothing():
    conn, dev, _, run = setup()
    create_budget(conn, "org", 10, dev.id)
    charge(conn, run, 0)
    assert [b.used for b in list_budgets(conn)] == [0]


def test_a_budget_is_validated_when_it_is_made():
    conn, dev, _, _ = setup()
    with pytest.raises(ValueError, match="unknown budget scope"):
        create_budget(conn, "galaxy", 10, dev.id)
    with pytest.raises(ValueError, match="needs a repo id"):
        create_budget(conn, "repo", 10, dev.id)
    with pytest.raises(ValueError, match="must be positive"):
        create_budget(conn, "org", 0, dev.id)


# --- reading what a turn cost ----------------------------------------------

class _Msg:
    def __init__(self, usage):
        self.usage_metadata = usage


def test_units_are_summed_over_every_message_that_reported_usage():
    from open_refinery.pipeline.agent import units_of

    answer = {"messages": [
        _Msg({"input_tokens": 100, "output_tokens": 20, "total_tokens": 120}),
        _Msg(None),                                     # a tool message reports nothing
        _Msg({"input_tokens": 300, "output_tokens": 50, "total_tokens": 350}),
    ]}
    assert units_of(answer) == 470


def test_units_fall_back_to_input_plus_output():
    """Not every provider fills `total_tokens`."""
    from open_refinery.pipeline.agent import units_of

    assert units_of({"messages": [_Msg({"input_tokens": 7, "output_tokens": 3})]}) == 10


def test_a_provider_that_reports_nothing_meters_zero():
    """Honest rather than guessed: a budget cannot bound what nothing measures."""
    from open_refinery.pipeline.agent import units_of

    assert units_of({"messages": [_Msg(None)]}) == 0
    assert units_of({}) == 0
    assert units_of(None) == 0


# --- the runner honours the ceiling ----------------------------------------

def test_an_exhausted_budget_fails_the_run_rather_than_continuing():
    """A stage carrying `on_error: continue` would otherwise walk the rest of
    the graph, spending a stage at a time to learn the same thing each time."""
    from open_refinery.audit import MemorySink
    from open_refinery.pipeline.runner import step

    conn, _, _, run = setup(max_run_units=100)
    ps.record_step(conn, run, "prepare", outcome="ok", why="", units=500)

    audit = MemorySink()
    moved = step(conn, run, audit)
    assert (moved.stage, moved.outcome) == ("failed", "failed")

    # the reason is on the step and in the trail — where every other failure
    # puts it. (`Run.error` is a column nothing writes; that predates this.)
    blocked = [s for s in ps.steps_of(conn, run.id) if s.outcome == "blocked"]
    assert len(blocked) == 1
    assert "500 of its 100-unit ceiling" in blocked[0].why
    assert [r for r in audit.records if r.recipe == "budget-exceeded"]


def test_a_run_inside_its_ceiling_is_never_refused_for_budget():
    """It may still fail for its own reasons — there is no checkout here — but
    not this one."""
    from open_refinery.audit import MemorySink
    from open_refinery.pipeline.runner import step

    conn, _, _, run = setup(max_run_units=10_000)
    ps.record_step(conn, run, "prepare", outcome="ok", why="", units=500)
    audit = MemorySink()
    step(conn, run, audit)
    assert not [r for r in audit.records if r.recipe == "budget-exceeded"]
