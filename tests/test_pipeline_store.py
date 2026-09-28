"""Pipelines and runs, persisted.

The property worth protecting: **editing a pipeline never reaches a run already
in flight**, and the graph a finished run followed is still readable later.
"""

import pytest

from open_refinery.models import Repository
from open_refinery.pipeline import GraphError, default_pipeline
from open_refinery.pipeline import store as ps
from open_refinery.pipeline.graph import Move, Result
from open_refinery.store import connect
from open_refinery.users import create_user, ensure_presets


@pytest.fixture
def ctx():
    session = connect("sqlite:///:memory:")
    ensure_presets(session)
    user, _ = create_user(session, "ops@x.io", "pw", "platform")
    repo = Repository(name="app", git_url="git@x:app.git", owner_id=user.id)
    session.add(repo)
    session.commit()
    session.refresh(repo)

    # A run points at a real work item — the FK is what keeps a run from
    # outliving the thing it was started for.
    from open_refinery.work_items import create_work_item
    items = [create_work_item(session, repo.id, f"T{n}", user.id).id
             for n in (1, 2)]
    return session, user, repo, items


# --- pipelines --------------------------------------------------------------

def test_the_default_is_seeded_once(ctx):
    session, user, _, _items = ctx
    first = ps.ensure_default(session, user.id)
    again = ps.ensure_default(session, user.id)
    assert first.id == again.id and first.version == 1


def test_saving_writes_a_new_version_rather_than_editing(ctx):
    session, user, _, _items = ctx
    ps.ensure_default(session, user.id)

    raw = default_pipeline()
    raw["model"] = "claude-opus-5"
    second = ps.save_pipeline(session, raw, user.id)

    assert second.version == 2
    assert len(ps.list_pipelines(session, all_versions=True)) == 2
    assert len(ps.list_pipelines(session)) == 1          # newest per name


def test_an_invalid_pipeline_never_reaches_the_database(ctx):
    """Or the next run to pick it up fails somewhere far from here."""
    session, user, _, _items = ctx
    with pytest.raises(GraphError):
        ps.save_pipeline(session, {"first": "a", "stages": {
            "a": {"action": "teardown", "next": "atlantis"}}}, user.id)
    assert ps.list_pipelines(session) == []


def test_a_stored_pipeline_round_trips_to_a_graph(ctx):
    session, user, _, _items = ctx
    row = ps.ensure_default(session, user.id)
    graph = ps.graph_of(row)

    assert graph.first == "prepare"
    assert graph.model_for(graph.stage("plan")) == "claude-opus-5"


def test_the_layout_is_carried_forward(ctx):
    """So a canvas opens how it was left rather than re-laying-out."""
    session, user, _, _items = ctx
    ps.save_pipeline(session, default_pipeline(), user.id,
                     layout={"plan": {"x": 10, "y": 20}})
    later = ps.save_pipeline(session, default_pipeline(), user.id)
    assert later.layout == {"plan": {"x": 10, "y": 20}}


# --- runs -------------------------------------------------------------------

def test_a_run_starts_at_the_first_stage(ctx):
    session, user, repo, items = ctx
    pipeline = ps.ensure_default(session, user.id)
    run = ps.start_run(session, items[0], pipeline, repo.id, user.id, spec="Add login")

    assert run.stage == "prepare"
    assert "Add login" in run.document


def test_a_run_pins_the_version_it_started_under(ctx):
    """Editing a pipeline mid-run must not change the rules under it."""
    session, user, repo, items = ctx
    v1 = ps.ensure_default(session, user.id)
    run = ps.start_run(session, items[0], v1, repo.id, user.id)

    raw = default_pipeline()
    del raw["stages"]["prove"]
    raw["stages"]["run"]["next"] = "review"
    ps.save_pipeline(session, raw, user.id)

    assert run.pipeline_version == 1
    assert "prove" in ps.graph_of(ps.get_pipeline(session, run.pipeline_id)).stages


def test_run_state_is_a_plain_dict_for_the_pure_machine(ctx):
    """The machine never sees an ORM object — that is what keeps it testable
    with a literal."""
    session, user, repo, items = ctx
    pipeline = ps.ensure_default(session, user.id)
    run = ps.start_run(session, items[0], pipeline, repo.id, user.id, spec="Do it")

    state = ps.run_state(run)
    assert state["stage"] == "prepare" and state["document"]["spec"] is True
    assert isinstance(state, dict)


def test_applying_a_move_advances_the_run_and_the_document(ctx):
    session, user, repo, items = ctx
    pipeline = ps.ensure_default(session, user.id)
    run = ps.start_run(session, items[0], pipeline, repo.id, user.id, spec="Do it")

    run = ps.apply_move(session, run, Move("plan", "prepared"),
                        produced={"plan": "touch auth.py"})
    assert run.stage == "plan"
    assert "touch auth.py" in run.document


def test_a_terminal_move_records_the_outcome(ctx):
    session, user, repo, items = ctx
    pipeline = ps.ensure_default(session, user.id)
    run = ps.start_run(session, items[0], pipeline, repo.id, user.id)

    run = ps.apply_move(session, run, Move("landed", "merged"))
    assert run.outcome == "landed"
    assert ps.list_runs(session, active=True) == []
    assert len(ps.list_runs(session, active=False)) == 1


def test_steps_are_append_only(ctx):
    """A step is a fact, not a status."""
    session, user, repo, items = ctx
    pipeline = ps.ensure_default(session, user.id)
    run = ps.start_run(session, items[0], pipeline, repo.id, user.id)

    ps.record_step(session, run, "run", outcome="refused", why="hook refused")
    ps.record_step(session, run, "run", outcome="ok", why="second attempt", attempt=2)

    steps = ps.steps_of(session, run.id)
    assert [s.outcome for s in steps] == ["refused", "ok"]


def test_a_downgraded_answer_is_stored_structurally(ctx):
    """Queryable across runs, not re-parsed from prose later."""
    from open_refinery.pipeline.contracts import BUILT_IN, read

    session, user, repo, items = ctx
    pipeline = ps.ensure_default(session, user.id)
    run = ps.start_run(session, items[0], pipeline, repo.id, user.id)

    answer = read("PROVEN: yes\n\nit works", BUILT_IN["proven"])
    step = ps.record_step(session, run, "prove", outcome="ok", why="done",
                          phase="prove", answer=answer.as_dict())

    assert step.answer["value"] == "unproven"
    assert step.answer["downgraded_from"] == "yes"


def test_approving_clears_the_hold(ctx):
    session, user, repo, items = ctx
    pipeline = ps.ensure_default(session, user.id)
    run = ps.start_run(session, items[0], pipeline, repo.id, user.id)
    run = ps.apply_move(session, run, Move("plan", "held", held=True))
    assert run.held is True

    run = ps.approve_run(session, run.id, user.id)
    assert run.held is False and run.approved_at


def test_runs_can_be_listed_by_work_item_and_actor(ctx):
    session, user, repo, items = ctx
    pipeline = ps.ensure_default(session, user.id)
    ps.start_run(session, items[0], pipeline, repo.id, user.id)
    ps.start_run(session, items[1], pipeline, repo.id, user.id)

    assert len(ps.list_runs(session, work_item_id=items[0])) == 1
    assert len(ps.list_runs(session, actor_id=user.id)) == 2


def test_an_unknown_run_is_reported_not_guessed(ctx):
    session, *_ = ctx
    with pytest.raises(ps.UnknownRun):
        ps.approve_run(session, "nope", "someone")


def test_an_unknown_pipeline_name_is_reported(ctx):
    session, *_ = ctx
    with pytest.raises(ps.UnknownPipeline):
        ps.latest_pipeline(session, "not-a-pipeline")
