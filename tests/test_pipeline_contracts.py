"""Contracts — a check that grades itself is not a check.

`prove` claims the software works and `review` claims the diff is sound. Both
claims are worth exactly what the evidence under them is worth, and these are
the rules that enforce that without asking a model to be honest about its own
output.
"""

import pytest

from open_refinery.pipeline.contracts import BUILT_IN, Answer, contract, read

PROVEN = BUILT_IN["proven"]
VERDICT = BUILT_IN["verdict"]


# --- proof ------------------------------------------------------------------

def test_a_proof_with_a_command_under_it_stands():
    answer = read("PROVEN: yes\n\n$ pytest -q\n40 passed", PROVEN)
    assert answer.value == "yes" and not answer.downgraded
    assert answer.evidence == ("$ pytest -q",)


def test_a_proof_with_no_command_is_downgraded():
    """Evidence or it did not happen."""
    answer = read("PROVEN: yes\n\nEverything works, I checked carefully.", PROVEN)
    assert answer.value == "unproven"
    assert answer.downgraded_from == "yes"
    assert "claim, not a proof" in answer.why


def test_unproven_is_not_the_same_as_no():
    """`no` is a finding; `unproven` is an absence, and a person looks at it."""
    assert read("PROVEN: no\n\nthe suite fails", PROVEN).value == "no"
    assert read("PROVEN: yes\n\nlooks right", PROVEN).value == "unproven"


def test_a_partial_proof_needs_no_evidence():
    """Only `yes` is a claim strong enough to require backing."""
    assert read("PROVEN: partial\n\nthe happy path only", PROVEN).value == "partial"


# --- review -----------------------------------------------------------------

def test_a_finding_that_names_a_place_stands():
    answer = read("VERDICT: concerns\n- app.py:9 unbounded loop", VERDICT)
    assert answer.value == "concerns" and answer.findings


def test_an_objection_naming_nothing_is_a_mood():
    answer = read("VERDICT: blocker\n\nI have a bad feeling about this design.", VERDICT)
    assert answer.value == "unreadable"
    assert answer.downgraded_from == "blocker"
    assert "mood" in answer.why


def test_a_pass_needs_no_findings():
    assert read("VERDICT: pass\n\nlooks good", VERDICT).value == "pass"


# --- the rule that matters most ---------------------------------------------

def test_an_unparseable_answer_is_never_a_pass():
    """The failure this prevents: a check whose output format drifted, reading
    as approval for weeks."""
    assert read("Looks good to me!", VERDICT).value == "unreadable"
    assert read("", VERDICT).value == "unreadable"
    assert read("The tests all pass.", PROVEN).value == "unproven"


def test_a_marker_mid_sentence_does_not_declare_a_verdict():
    """A check explaining itself must not accidentally vote."""
    assert read("I will emit VERDICT: pass once done.", VERDICT).value == "unreadable"


def test_a_marker_at_the_start_of_a_line_does_declare_one():
    assert read("Thinking about it.\nVERDICT: pass\n", VERDICT).value == "pass"


def test_an_unknown_value_is_unreadable():
    assert read("VERDICT: probably fine", VERDICT).value == "unreadable"


# --- what the pipeline does with it -----------------------------------------

@pytest.mark.parametrize("value", ["concerns", "blocker", "no", "unproven", "unreadable"])
def test_these_are_complaints_the_pipeline_acts_on(value):
    assert Answer(value=value).objects is True


@pytest.mark.parametrize("value", ["pass", "yes", "partial"])
def test_these_are_not(value):
    assert Answer(value=value).objects is False


def test_a_downgrade_is_recorded_structurally():
    """Stored queryable, not as prose: "how often did prove claim yes without
    evidence" is a question about the factory, not about one run."""
    stored = read("PROVEN: yes\n\nit works", PROVEN).as_dict()
    assert stored["value"] == "unproven" and stored["downgraded_from"] == "yes"
    assert stored["why"]


# --- a team's own contract --------------------------------------------------

def test_a_team_can_override_a_built_in():
    custom = contract("verdict", {"values": ["ship", "hold"]})
    assert read("VERDICT: ship", custom).value == "ship"
    assert read("VERDICT: pass", custom).value == "unreadable"


def test_an_unknown_contract_with_no_config_is_empty():
    assert contract("not-a-contract") == {}
