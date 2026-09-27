"""The stage machine — every branch the factory can take, with no agent,
no worktree and no forge.

That this file needs none of those is the point: the alternative is discovering
what the pipeline does by sending real work through it.
"""

import pytest

from open_refinery.pipeline import default_pipeline, parse
from open_refinery.pipeline.graph import (
    BLOCKED_ON_PERSON,
    ERROR,
    OK,
    REFUSED,
    Result,
    advance,
    plan_next,
    should_skip,
    walk,
)


@pytest.fixture
def graph():
    return parse(default_pipeline())


def run_at(stage, **kw):
    base = {"stage": stage, "revisions": 0, "reason": "", "last_refusal": "",
            "document": {"spec": True}}
    return {**base, **kw}


# --- the happy path ---------------------------------------------------------

def test_a_clean_run_reaches_the_pull_request(graph):
    assert walk(graph) == ["prepare", "plan", "run", "prove", "review",
                           "commit", "publish", "waiting"]


def test_it_stops_at_waiting_because_nothing_merges_itself(graph):
    assert walk(graph)[-1] == "waiting"


def test_each_stage_leads_to_the_next(graph):
    assert advance(run_at("run", document={"spec": True, "work": True}),
                   graph, Result(OK)).to == "prove"


# --- refusals ---------------------------------------------------------------

def test_a_refusal_goes_back_and_counts_a_revision(graph):
    move = advance(run_at("run"), graph, Result(REFUSED, reason="no secrets in source"))
    assert move.to == "run" and move.revisions == 1 and move.reason == "revision"
    assert move.last_refusal == "no secrets in source"


def test_the_revision_cap_fails_the_run(graph):
    move = advance(run_at("run", revisions=2), graph, Result(REFUSED, reason="again"))
    assert move.to == "failed"


def test_an_identical_refusal_stops_early(graph):
    """A gate repeating itself word for word has shown its complaint is not
    about the diff — a second attempt costs a turn and learns nothing."""
    move = advance(run_at("run", revisions=1, last_refusal="same words"),
                   graph, Result(REFUSED, reason="same words"))
    assert move.to == "failed" and "not about the diff" in move.why


def test_a_different_refusal_is_worth_another_go(graph):
    move = advance(run_at("run", revisions=1, last_refusal="first complaint"),
                   graph, Result(REFUSED, reason="a different complaint"))
    assert move.to == "run" and move.revisions == 2


def test_a_refusal_with_nowhere_to_go_fails(graph):
    """`prove` has no refusal path — a check that refuses is not a retry."""
    move = advance(run_at("prove", document={"spec": True, "work": True}),
                   graph, Result(REFUSED, reason="tests fail"))
    assert move.to == "failed"


def test_the_commit_gate_sends_work_back_to_run(graph):
    """Rung 4's complaint becomes the brief for the next attempt."""
    move = advance(run_at("commit"), graph, Result(REFUSED, reason="hook: no console.log"))
    assert move.to == "run" and move.reason == "revision"


# --- errors -----------------------------------------------------------------

def test_a_failing_stage_fails_the_run_by_default(graph):
    move = advance(run_at("run"), graph, Result(ERROR, error="provider down"))
    assert move.to == "failed" and "provider down" in move.why


def test_on_error_continue_carries_on(graph):
    """A plan turn that fails hands over an empty plan rather than failing the
    run — planning is a help, not a gate."""
    move = advance(run_at("plan"), graph, Result(ERROR, error="timeout"))
    assert move.to == "run"


# --- what the human did -----------------------------------------------------

@pytest.mark.parametrize("event,expected", [
    ("merge", "landed"), ("close", "closed"), ("comment", "rework")])
def test_the_pull_request_outcome_decides(graph, event, expected):
    assert advance(run_at("waiting"), graph, Result(OK, event=event)).to == expected


def test_a_comment_sets_the_rework_reason(graph):
    """So `plan` skips on the way round — the comment is already the brief."""
    assert advance(run_at("waiting"), graph, Result(OK, event="comment")).reason == "rework"


def test_no_event_keeps_waiting(graph):
    move = advance(run_at("waiting"), graph, Result(OK))
    assert move.to == "waiting" and move.held is True


# --- skipping ---------------------------------------------------------------

def test_a_revision_skips_planning(graph):
    """Re-planning would only blur a gate's complaint."""
    assert "skipped on revision" in should_skip(graph.stage("plan"),
                                                run_at("plan", reason="revision"))


def test_rework_skips_planning_too(graph):
    assert should_skip(graph.stage("plan"), run_at("plan", reason="rework"))


def test_a_stage_whose_input_is_missing_is_skipped(graph):
    why = should_skip(graph.stage("review"), run_at("review", document={"spec": True}))
    assert "missing work" in why


def test_an_optional_stage_runs_unless_turned_off(graph):
    """opt-OUT: a factory that quietly stopped checking is worse than one that
    never checked."""
    item = run_at("prove", document={"spec": True, "work": True})
    assert should_skip(graph.stage("prove"), item) == ""
    assert should_skip(graph.stage("prove"), {**item, "skip": ["prove"]})


def test_an_opt_in_stage_does_not_run_unless_asked():
    """The other half. Conflating them is how `refine` ran on a job that never
    asked to be refined."""
    graph = parse({"first": "refine", "stages": {
        "refine": {"phase": "refine", "opt_in": True, "next": "landed"}}})
    item = run_at("refine")
    assert should_skip(graph.stage("refine"), item) == "not opted in"
    assert should_skip(graph.stage("refine"), {**item, "opt_in": ["refine"]}) == ""


def test_a_skipped_stage_moves_on_without_running(graph):
    move = plan_next(graph.stage("plan") and run_at("plan", reason="revision"), graph)
    assert move.skipped is True and move.to == "run"


# --- approval ---------------------------------------------------------------

def test_a_stage_marked_approve_holds_first(graph):
    move = plan_next(run_at("plan"), graph)
    assert move.held is True and move.to == "plan"


def test_an_approved_run_goes_ahead(graph):
    move = plan_next(run_at("plan", approved_at="2026-09-27T00:00:00Z"), graph)
    assert move.held is False and move.to == "plan"


def test_a_skipped_stage_is_not_also_held(graph):
    """Folding the two questions together is how a skipped stage ends up
    waiting for an approval nobody owes."""
    move = plan_next(run_at("plan", reason="revision"), graph)
    assert move.skipped is True and move.held is False


# --- edges ------------------------------------------------------------------

def test_a_terminal_run_stays_put(graph):
    assert advance(run_at("landed"), graph, Result(OK)).to == "landed"


def test_an_unknown_stage_fails_rather_than_hanging(graph):
    move = advance(run_at("atlantis"), graph, Result(OK))
    assert move.to == "failed" and "not a stage" in move.why


def test_blocked_keeps_the_run_where_it_is(graph):
    move = advance(run_at("run"), graph, Result(BLOCKED_ON_PERSON))
    assert move.to == "run" and move.held is True


def test_walk_is_bounded_so_a_cycle_shows_up_rather_than_hangs():
    """The thing `pipeline check` exists to show you before you pay for a run."""
    graph = parse({"first": "a", "stages": {
        "a": {"action": "teardown", "next": "b"},
        "b": {"action": "teardown", "next": "a"}}})
    assert len(walk(graph, limit=10)) == 10
