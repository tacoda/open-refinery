"""The stage graph: what parses, and what a bad pipeline is told.

Validation is strict about reachability and exits, because the two ways to
write a pipeline that looks fine and hangs are a stage nothing reaches and a
stage with no way out.
"""

import pytest

from open_refinery.pipeline import GraphError, default_pipeline, parse
from open_refinery.pipeline.spec import to_dict


def g(**stages):
    return {"first": next(iter(stages)), "stages": stages}


# --- the shipped default ----------------------------------------------------

def test_the_default_pipeline_parses():
    graph = parse(default_pipeline())
    assert graph.name == "ship-a-ticket"
    assert graph.first == "prepare"


def test_the_default_spends_the_thinking_model_once(graph=None):
    """Deciding and building are separate turns on different models."""
    graph = parse(default_pipeline())
    assert graph.model_for(graph.stage("plan")) == "claude-opus-5"
    assert graph.model_for(graph.stage("run")) == "claude-sonnet-5"


def test_the_default_holds_the_plan_for_a_person():
    """Cheaper than gating the diff — a wrong approach is caught before the
    run phase spends its turn cap."""
    assert parse(default_pipeline()).stage("plan").approve is True


def test_the_default_reverts_what_a_check_touched():
    """A check may run; it may not repair."""
    assert parse(default_pipeline()).stage("prove").revert_changes is True


def test_the_default_ends_in_a_human_decision():
    waiting = parse(default_pipeline()).stage("waiting")
    assert dict(waiting.outcomes) == {"merge": "landed", "close": "closed",
                                      "comment": "rework"}


def test_states_are_derived_from_the_graph():
    """A team that adds a stage gets its state for free."""
    graph = parse(default_pipeline())
    assert "rework" in graph.states() and "landed" in graph.states()
    assert "blocked" in graph.states()


# --- a stage is a phase or an action, never both ----------------------------

def test_a_stage_with_both_a_phase_and_an_action_is_refused():
    with pytest.raises(GraphError, match="one or the other"):
        parse(g(a={"phase": "run", "action": "teardown", "next": "b"},
                b={"action": "teardown", "next": "a"}))


def test_a_stage_with_neither_is_refused():
    with pytest.raises(GraphError, match="neither a phase nor an action"):
        parse(g(a={"next": "b"}, b={"action": "teardown", "next": "a"}))


def test_an_unknown_action_names_the_known_ones():
    with pytest.raises(GraphError, match="Known:"):
        parse(g(a={"action": "make_coffee", "next": "landed"}))


# --- reachability and exits -------------------------------------------------

def test_a_stage_with_no_way_out_is_refused():
    with pytest.raises(GraphError, match="no way out"):
        parse(g(a={"action": "teardown"}))


def test_a_stage_leading_nowhere_real_is_refused():
    with pytest.raises(GraphError, match="neither a stage nor terminal"):
        parse(g(a={"action": "teardown", "next": "atlantis"}))


def test_an_unreachable_stage_is_refused():
    raw = g(a={"action": "teardown", "next": "landed"},
            orphan={"action": "teardown", "next": "landed"})
    with pytest.raises(GraphError, match="unreachable"):
        parse(raw)


def test_a_stage_reached_only_by_an_outcome_edge_is_reachable():
    """The bug this prevents: walking `next` alone reports `rework`
    unreachable, and the default pipeline stops parsing."""
    parse(default_pipeline())   # rework is reached only via on_comment


def test_a_stage_reached_only_by_a_refusal_is_reachable():
    raw = {"first": "a", "stages": {
        "a": {"phase": "run", "next": "landed",
              "on_refusal": {"goto": "fix"}},
        "fix": {"action": "teardown", "next": "a"}}}
    assert "fix" in parse(raw).stages


def test_the_first_stage_must_exist():
    with pytest.raises(GraphError, match="first stage"):
        parse({"first": "nope", "stages": {"a": {"action": "teardown", "next": "landed"}}})


def test_an_empty_pipeline_is_refused():
    with pytest.raises(GraphError, match="at least one stage"):
        parse({"stages": {}})


# --- the flags that look alike ----------------------------------------------

def test_optional_and_opt_in_cannot_both_be_set():
    """Conflating them makes every optional stage default-on, which is how
    `refine` ran on a job that never asked to be refined."""
    with pytest.raises(GraphError, match="pick one"):
        parse(g(a={"phase": "run", "optional": True, "opt_in": True, "next": "landed"}))


def test_a_contract_on_an_action_is_refused():
    """A contract grades an answer, and an action does not give one."""
    with pytest.raises(GraphError, match="runs no phase"):
        parse(g(a={"action": "teardown", "contract": "verdict", "next": "landed"}))


def test_an_unknown_on_error_is_refused():
    with pytest.raises(GraphError, match="on_error"):
        parse(g(a={"phase": "run", "on_error": "shrug", "next": "landed"}))


# --- round trip -------------------------------------------------------------

def test_a_graph_round_trips_through_its_document():
    """Export then import has to give the same pipeline, or a team reviewing
    one in a pull request is reviewing something else."""
    original = parse(default_pipeline())
    again = parse(to_dict(original))

    assert again.first == original.first
    assert set(again.stages) == set(original.stages)
    for name, stage in original.stages.items():
        assert again.stages[name] == stage, name


def test_export_omits_defaults():
    """A document full of `false` is one nobody reads."""
    body = to_dict(parse(g(a={"action": "teardown", "next": "landed"})))["stages"]["a"]
    assert body == {"action": "teardown", "next": "landed"}


def test_a_single_string_is_accepted_where_a_list_is_meant():
    stage = parse(g(a={"phase": "run", "requires": "spec", "next": "landed"})).stage("a")
    assert stage.requires == ("spec",)


def test_on_refusal_accepts_a_bare_stage_name():
    stage = parse(g(a={"phase": "run", "on_refusal": "a", "next": "landed"})).stage("a")
    assert stage.on_refusal == "a" and stage.max_revisions == 2
