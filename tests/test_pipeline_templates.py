"""The templates a team starts from.

Each says what it **gives up**, because a template chosen without knowing that
is a decision nobody made.
"""

import pytest

from open_refinery.pipeline import TEMPLATES, GraphError, parse, template, templates
from open_refinery.pipeline.graph import walk


def test_every_template_parses():
    for name in TEMPLATES:
        assert parse(template(name)).name == name


def test_every_template_reaches_a_pull_request():
    """A workflow that cannot ship is not a workflow."""
    for name in TEMPLATES:
        graph = parse(template(name))
        assert "publish" in walk(graph), name


def test_every_template_ends_with_a_person():
    """Nothing merges itself, in any configuration."""
    for name in TEMPLATES:
        graph = parse(template(name))
        assert walk(graph)[-1] == "waiting", name
        assert dict(graph.stage("waiting").outcomes)["merge"] == "landed"


def test_every_template_keeps_the_commit_gate():
    """Rung 4 is the repository's own hook. Skipping it would ship things the
    repository itself refuses."""
    for name in TEMPLATES:
        assert "commit" in parse(template(name)).stages, name


def test_quick_fix_is_one_turn():
    graph = parse(template("quick-fix"))
    phases = [s.phase for s in graph.stages.values() if s.phase]
    assert phases == ["run"]


def test_quick_fix_says_what_it_gives_up():
    entry = next(t for t in templates() if t["name"] == "quick-fix")
    assert "no plan" in entry["gives_up"].lower()
    assert "review" in entry["gives_up"].lower()


def test_strict_adds_a_second_reader():
    """A general reviewer asked to check everything checks the thing it read
    most recently."""
    graph = parse(template("strict"))
    assert "security" in graph.stages
    assert graph.stage("review").next == "security"
    assert graph.stage("security").next == "commit"


def test_strict_makes_the_checks_mandatory():
    graph = parse(template("strict"))
    assert graph.stage("prove").optional is False
    assert graph.stage("review").optional is False


def test_strict_fails_on_a_failed_plan():
    """A plan that failed is not an empty plan to build from."""
    assert parse(template("strict")).stage("plan").on_error == "fail"


def test_docs_only_has_no_proof_stage():
    """There is nothing to run."""
    graph = parse(template("docs-only"))
    assert "prove" not in graph.stages
    assert "review" in graph.stages


def test_the_default_is_unchanged_by_strict():
    """`strict` builds on the default — it must not mutate the shared dict."""
    from open_refinery.pipeline import default_pipeline

    template("strict")
    assert default_pipeline()["stages"]["prove"]["optional"] is True
    assert "security" not in default_pipeline()["stages"]


def test_the_catalog_describes_each_one():
    for entry in templates():
        assert entry["about"] and entry["stages"] > 0


def test_an_unknown_template_names_the_real_ones():
    with pytest.raises(GraphError, match="ship-a-ticket"):
        template("not-a-template")
