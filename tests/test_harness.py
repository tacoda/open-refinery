"""The harness: what one turn is allowed to be.

None of this calls a model. The grants, the interrupt mapping and the
governance decisions are all decidable without spending anything, which is the
only reason they can be tested at all.
"""

import pytest

from open_refinery.pipeline import phases
from open_refinery.models_port import provider_of
from open_refinery.pipeline.agent import INTERRUPTS, interrupts_for
from open_refinery.pipeline.middleware import Governed
from open_refinery.store import SqliteSink, connect
from open_refinery.users import create_user, ensure_presets


# --- rung 1: a phase is never handed an editor ------------------------------

def test_only_the_run_phase_may_edit():
    """A rule at rung 1 leaves nothing to refuse and nothing to argue past —
    which is why `prove` and `review` need no predicate."""
    assert phases.builtin("run").may_edit
    for name in ("plan", "prove", "review", "security", "improve", "refine"):
        assert not phases.builtin(name).may_edit, name


def test_prove_may_run_things_but_not_repair_them():
    prove = phases.builtin("prove")
    assert prove.may_run and not prove.may_edit


def test_review_may_neither_run_nor_edit():
    """It reads the diff and stamps a verdict. A check that could fix what it
    found would be grading its own work."""
    review = phases.builtin("review")
    assert not review.may_run and not review.may_edit


def test_the_improve_lane_is_read_only():
    """The lane proposing changes to the rules does not get to be the one thing
    escaping the gate everything else goes through."""
    assert not phases.builtin("improve").may_edit


def test_the_ladder_can_withhold_a_tool_from_a_phase():
    run = phases.builtin("run")
    assert "execute" in run.granted()
    assert "execute" not in run.granted(withheld=("execute",))


def test_reading_always_survives_a_withholding():
    """A phase given tools and no way to read them has been given nothing."""
    grant = phases.builtin("run").granted(withheld=phases.ALL_TOOLS)
    assert grant == ("read_file",)


def test_a_phase_a_team_invented_starts_read_only():
    assert phases.builtin("threat-model").tools == phases.READ_ONLY


# --- the prompts say what the contract will enforce -------------------------

def test_prove_is_told_that_a_claim_needs_a_command():
    prompt = phases.builtin("prove").prompt
    assert "PROVEN:" in prompt and "downgraded" in prompt


def test_review_is_told_an_objection_must_name_a_place():
    prompt = phases.builtin("review").prompt
    assert "VERDICT:" in prompt and "name a place" in prompt


def test_review_is_not_given_the_implementers_account():
    """A check fed the work's story is grading a story."""
    assert "grading a story" in phases.builtin("review").prompt


# --- a team's overrides -----------------------------------------------------

def test_an_override_changes_only_what_it_sets():
    """Changing a turn cap must not silently clear the prompt."""
    from open_refinery.models import PhaseConfig

    session = connect("sqlite:///:memory:")
    session.add(PhaseConfig(name="review", max_turns=99))
    session.commit()

    resolved = phases.resolve(session, "review")
    assert resolved.max_turns == 99
    assert resolved.prompt == phases.builtin("review").prompt
    assert resolved.tools == phases.builtin("review").tools


def test_a_team_can_narrow_a_grant():
    from open_refinery.models import PhaseConfig

    session = connect("sqlite:///:memory:")
    session.add(PhaseConfig(name="run", tools=["read_file", "write_file"]))
    session.commit()

    assert not phases.resolve(session, "run").may_run


def test_one_registry_answers_for_every_model_name():
    """There were two provider lists and they disagreed. One of the two call
    sites is gone in 3.0; the registry stays the single answer, because the
    harness, the pipeline validator and the credential catalog all read it."""
    from open_refinery.models_port import PROVIDERS

    assert provider_of("gpt-5.5").key == "openai"
    assert provider_of("claude-opus-5").key == "anthropic"
    assert len(PROVIDERS) >= 5


def test_the_catalog_reports_what_each_phase_may_do():
    rows = {r["name"]: r for r in phases.catalog()}
    assert rows["run"]["may_edit"] is True
    assert rows["review"]["may_edit"] is False
    assert all(r["builtin"] for r in rows.values())


# --- oversight becomes interrupts -------------------------------------------

@pytest.mark.parametrize("level,asked", [
    ("manual", "read_file"), ("assisted", "write_file"), ("supervised", "execute")])
def test_a_watched_level_asks_about_the_right_calls(level, asked):
    assert interrupts_for(level).get(asked) is True


def test_supervised_does_not_ask_about_reads():
    assert interrupts_for("supervised").get("read_file") is not True


def test_the_unattended_levels_ask_nothing():
    """`ask` never becomes `allow` — at these levels it degrades to the ladder
    refusing, not to the call going through unasked."""
    for level in ("autonomous", "dark"):
        assert interrupts_for(level) == {}


def test_an_unknown_level_falls_back_to_watched_not_open():
    """Failing closed: a typo in an oversight level must not silently mean
    'nobody is asked'."""
    assert interrupts_for("not-a-level") == INTERRUPTS["supervised"]


# --- governance, per tool call ----------------------------------------------

@pytest.fixture
def governed():
    session = connect("sqlite:///:memory:")
    ensure_presets(session)
    user, _ = create_user(session, "dev@x.io", "pw", "developer")
    return Governed(session_factory=lambda: connect("sqlite:///:memory:"),
                    actor_id=user.id, run_id="run-1", audit=SqliteSink(session)), session


def test_an_ordinary_call_is_allowed(governed):
    g, _ = governed
    assert g.check("read_file", {"path": "README.md"}) == ""


def test_a_call_carrying_a_secret_is_refused(governed):
    """The filter is not advisory: the call does not run."""
    g, _ = governed
    refused = g.check("write_file", {"path": "x.py",
                                     "content": "AWS_SECRET_ACCESS_KEY=AKIAIOSFODNN7EXAMPLE"})
    assert refused.startswith("refused:")
    assert g.redactions


def test_every_call_is_counted(governed):
    g, _ = governed
    g.check("read_file", {"path": "a"})
    g.check("read_file", {"path": "b"})
    assert g.calls == 2


def test_a_call_is_audited_against_its_run(governed):
    """A run's whole tool history is one query."""
    from open_refinery.store import query_events

    g, session = governed
    g.record("read_file", "", "some contents")
    events = query_events(session, subject="run-1")
    assert [e.recipe for e in events] == ["tool-call"]


def test_a_refusal_is_audited_differently(governed):
    from open_refinery.store import query_events

    g, session = governed
    g.record("write_file", "refused: no secrets")
    events = query_events(session, subject="run-1")
    assert events[0].recipe == "tool-refused"


def test_nested_arguments_are_scanned_not_just_the_top_level(governed):
    """A secret one level down is still a secret."""
    g, _ = governed
    refused = g.check("write_file",
                      {"files": [{"body": "AWS_SECRET_ACCESS_KEY=AKIAIOSFODNN7EXAMPLE"}]})
    assert refused.startswith("refused:")


def test_ordinary_code_is_not_mistaken_for_a_secret(governed):
    """The refusals this seam used to produce were mostly about nothing: an
    email address in a commit author, a thirteen-digit constant. The filter here
    is secrets only now — personal data is caught where text leaves, in
    `actions.open_pull_request`."""
    g, _ = governed
    for args in (
        {"command": 'git commit --author="Ian <ian@example.com>"'},
        {"path": "CODEOWNERS", "content": "* @acme/platform-team\n"},
        {"path": "t.py", "content": "TWITTER_EPOCH = 1288834974657\n"},
        {"path": "package.json", "content": '{"author": "team@acme.dev"}'},
    ):
        assert g.check("write_file", args) == "", args
    assert g.redactions == []


def test_the_refusal_tells_you_what_to_do_instead(governed):
    g, _ = governed
    refused = g.check("write_file", {"content": "key = AKIAIOSFODNN7EXAMPLE"})
    assert "read it from the environment" in refused


# --- the dependency boundary ------------------------------------------------

def test_only_agent_py_imports_deepagents():
    """deepagents is pre-1.0, moves fast, and carries pillar 2 — so an upstream
    API change has to have a one-file blast radius. Mentioning it in a comment
    is fine; importing it is not."""
    import pathlib
    import re

    root = pathlib.Path("src/open_refinery")
    importing = re.compile(r"^\s*(?:from|import)\s+(deepagents|langgraph)",
                           re.MULTILINE)
    offenders = sorted(p.name for p in root.rglob("*.py")
                       if importing.search(p.read_text()) and p.name != "agent.py")
    assert offenders == [], offenders


def test_langchain_is_confined_to_the_two_files_that_need_it():
    """A looser boundary, deliberately: `models_port` exists to be a model
    abstraction, so depending on one is its job. `agent.py` adapts the tool-call
    hook. Nothing else should know either library exists."""
    import pathlib
    import re

    root = pathlib.Path("src/open_refinery")
    importing = re.compile(r"^\s*(?:from|import)\s+langchain", re.MULTILINE)
    offenders = sorted(p.name for p in root.rglob("*.py")
                       if importing.search(p.read_text()))
    assert offenders == ["agent.py", "models_port.py"], offenders


def test_the_pipeline_works_without_the_harness_installed():
    """Everything except `agent.py` must import with no framework present."""
    from open_refinery.pipeline import contracts, document, forge, graph, spec, store
    from open_refinery.pipeline import middleware, phases, runner, workspace
    assert spec and graph and contracts and document and forge and store
    assert middleware and phases and runner and workspace


# --- the agent is assembled correctly (everything short of the call) --------

def test_a_missing_model_key_says_which_connection_is_missing(tmp_path):
    """The common first failure. "401 from Anthropic" is a worse message than
    "you have not connected Anthropic"."""
    import subprocess

    from open_refinery.models import Repository
    from open_refinery.pipeline import store as ps
    from open_refinery.pipeline.agent import HarnessError, model_for
    from open_refinery.pipeline.phases import builtin
    from open_refinery.work_items import create_work_item

    root = tmp_path / "app"
    root.mkdir()
    for args in (["init", "-b", "main"], ["config", "user.email", "t@x.io"],
                 ["config", "user.name", "T"]):
        subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)
    (root / "README.md").write_text("# app\n")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "first"], cwd=root, check=True,
                   capture_output=True)

    session = connect("sqlite:///:memory:")
    ensure_presets(session)
    user, _ = create_user(session, "dev@x.io", "pw", "developer")
    repo = Repository(name="app", git_url=str(root), owner_id=user.id)
    session.add(repo)
    session.commit()
    session.refresh(repo)
    item = create_work_item(session, repo.id, "T", user.id)
    pipeline = ps.ensure_default(session, user.id)
    run = ps.start_run(session, item.id, pipeline, repo.id, user.id)

    with pytest.raises(HarnessError, match="Connections"):
        model_for(session, run, builtin("plan"))


def test_a_phase_with_no_model_anywhere_is_refused():
    from open_refinery.pipeline.agent import HarnessError, model_for
    from open_refinery.pipeline.phases import Phase

    with pytest.raises(HarnessError, match="no model"):
        model_for(None, None, Phase("x"), "")


def test_the_brief_holds_only_what_the_stage_requires():
    """`review` is handed the spec and the diff, and never the run phase's
    account of its own work."""
    from types import SimpleNamespace

    from open_refinery.pipeline.agent import _brief

    run = SimpleNamespace(document=(
        "## What was asked\n\nAdd login\n\n"
        "## What was built\n\nI did a great job\n\n"
        "## What was planned\n\ntouch auth.py\n"))
    stage = SimpleNamespace(requires=("spec",))

    brief = _brief(run, stage)
    assert "Add login" in brief
    assert "great job" not in brief
