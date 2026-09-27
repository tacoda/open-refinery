"""The run document — the interface between stages, and the pull request body.

By the time a person reads the pull request the account of the work is already
written. Nothing is summarised into existence at the end.
"""

from open_refinery.pipeline import document as d


def test_it_starts_from_the_spec():
    assert d.start("Add a login page").get("spec") == "Add a login page"


def test_sections_read_in_story_order_not_production_order():
    """A reader wants the story, not the schedule."""
    doc = d.start("asked").with_section("review", "fine").with_section("plan", "planned")
    assert doc.keys() == ("spec", "plan", "review")


def test_a_rerun_replaces_its_section_rather_than_appending():
    """Two contradictory 'What was built' sections is worse than either."""
    doc = d.start("asked").with_section("work", "first attempt")
    doc = doc.with_section("work", "second attempt")

    assert doc.get("work") == "second attempt"
    assert "first attempt" not in doc.text


def test_requirements_are_sections_of_the_document():
    doc = d.start("asked").with_section("work", "built it")
    assert d.satisfied(doc, ("spec", "work")) == ()
    assert d.satisfied(doc, ("spec", "proof")) == ("proof",)


def test_an_empty_section_does_not_count_as_produced():
    doc = d.start("asked").with_section("work", "   ")
    assert doc.has("work") is False
    assert d.satisfied(doc, ("work",)) == ("work",)


def test_it_round_trips_so_a_restarted_run_keeps_its_account():
    doc = (d.start("Add login")
           .with_section("plan", "touch auth.py")
           .with_section("work", "2 files, 1 test"))
    assert d.read(doc.text).sections == doc.sections


def test_a_section_a_team_invented_survives():
    """`requires`/`produces` are strings, so a `threat-model` stage needs no
    change here."""
    doc = d.start("asked").with_section("threat-model", "no new surface")
    assert "threat-model" in doc.keys()
    assert d.read(doc.text).get("threat-model") == "no new surface"


def test_an_empty_document_is_empty_text():
    assert d.start().text == ""
