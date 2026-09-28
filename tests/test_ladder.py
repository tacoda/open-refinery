"""The ladder — where a rule is carried.

"Money is Decimal" in a markdown file is rung 0, and prose is a request. The
same sentence as a predicate that refuses the write is a guarantee. These tests
are about the difference, and about the one move that makes the system weaker.
"""

import pytest

from open_refinery import ladder
from open_refinery.ladder import (
    CAPABILITY,
    CONSTRAINT,
    OURS,
    PREDICATES,
    RUNGS,
    add,
    evaluate,
    gate,
    move,
    plan_move,
    view,
    withheld,
)
from open_refinery.store import connect
from open_refinery.users import create_user, ensure_presets


@pytest.fixture
def ctx():
    session = connect("sqlite:///:memory:")
    ensure_presets(session)
    author, _ = create_user(session, "lead@x.io", "pw", "lead")
    approver, _ = create_user(session, "ops@x.io", "pw", "platform")
    return session, author, approver


# --- a rung is a place, not a strictness ------------------------------------

def test_every_rung_says_what_it_can_see():
    """"Promote this to rung 4" is a decision somebody has to make with the
    trade-off in front of them."""
    for rung, sees in RUNGS.items():
        assert sees and isinstance(rung, int)


def test_the_product_carries_four_of_the_six():
    """Rung 2 is the target repository's own commit hook and rung 5 is its CI —
    both real, neither ours."""
    assert set(OURS) == {0, 1, 3, 4}
    assert 2 not in OURS and 5 not in OURS


# --- a rule must be carryable at the rung it claims -------------------------

def test_prose_needs_nothing(ctx):
    session, author, _ = ctx
    rule = add(session, "Money is Decimal", layer="code", rung=0, author_id=author.id)
    assert rule.rung == 0 and not rule.predicate


def test_a_mechanical_rung_without_a_predicate_is_refused(ctx):
    """A rule stored at a rung nothing enforces is how a system ends up
    believing it is protected."""
    session, author, _ = ctx
    with pytest.raises(ValueError, match="carried by a predicate"):
        add(session, "No secrets", layer="code", rung=3, author_id=author.id)


def test_rung_one_must_say_what_it_withholds(ctx):
    session, author, _ = ctx
    with pytest.raises(ValueError, match="which tools"):
        add(session, "Checks do not repair", layer="harness", rung=1,
            author_id=author.id)


def test_an_unknown_predicate_is_refused(ctx):
    session, author, _ = ctx
    with pytest.raises(ValueError, match="unknown predicate"):
        add(session, "x", layer="code", rung=3, author_id=author.id,
            predicate_name="wishful-thinking")


# --- rung 1: the grant ------------------------------------------------------

def test_rung_one_withholds_a_tool(ctx):
    session, author, _ = ctx
    add(session, "Checks do not repair", layer="harness", rung=1,
        author_id=author.id, withholds=["write_file", "edit_file"], scope="prove")

    assert withheld(session, phase="prove") == ("edit_file", "write_file")
    assert withheld(session, phase="run") == ()


def test_a_capability_gives_a_tool_back(ctx):
    """The two ladders join at rung 1: a constraint withholds, a capability
    grants, and `withheld` is the net."""
    session, author, _ = ctx
    add(session, "No execution anywhere", layer="harness", rung=1,
        author_id=author.id, withholds=["execute"])
    assert "execute" in withheld(session)

    add(session, "Except in run, which needs it", layer="harness", rung=1,
        author_id=author.id, side=CAPABILITY, withholds=["execute"], scope="run")
    assert "execute" not in withheld(session, phase="run")


def test_a_disabled_rule_withholds_nothing(ctx):
    session, author, _ = ctx
    rule = add(session, "x", layer="harness", rung=1, author_id=author.id,
               withholds=["execute"])
    rule.enabled = False
    session.add(rule)
    session.commit()
    assert withheld(session) == ()


# --- rung 3: inside the turn ------------------------------------------------

def test_rung_three_refuses_in_the_rules_own_words(ctx):
    """Not "policy violation" — the rule's own sentence, so the model can work
    around it correctly."""
    session, author, _ = ctx
    add(session, "No credentials in source", layer="code", rung=3,
        author_id=author.id, predicate_name="no-secrets")

    verdict = evaluate(session, tool="write_file",
                       args={"content": "AWS_SECRET_ACCESS_KEY=AKIAIOSFODNN7EXAMPLE"})
    assert verdict.refused
    assert "No credentials in source" in verdict.why


def test_an_ordinary_call_passes(ctx):
    session, author, _ = ctx
    add(session, "No credentials in source", layer="code", rung=3,
        author_id=author.id, predicate_name="no-secrets")
    assert evaluate(session, tool="write_file",
                    args={"content": "x = 1"}).allowed


def test_a_rule_out_of_scope_does_not_fire(ctx):
    session, author, _ = ctx
    add(session, "No force pushes", layer="code", rung=3, author_id=author.id,
        predicate_name="no-force-push", scope="execute")

    assert evaluate(session, tool="read_file",
                    args={"cmd": "git push --force"}).allowed
    assert evaluate(session, tool="execute",
                    args={"cmd": "git push --force"}).refused


def test_a_rule_at_rung_zero_refuses_nothing(ctx):
    """Prose is a request. That is the whole point of the ladder."""
    session, author, _ = ctx
    add(session, "Please do not commit secrets", layer="code", rung=0,
        author_id=author.id)
    assert evaluate(session, tool="write_file",
                    args={"content": "AWS_SECRET_ACCESS_KEY=AKIAIOSFODNN7EXAMPLE"}).allowed


# --- rung 4: the delivery gate ----------------------------------------------

def test_rung_four_sees_the_diff(ctx):
    """What nothing below it can: rung 3 saw calls and never the finished diff."""
    session, author, _ = ctx
    add(session, "No credentials in the diff", layer="code", rung=4,
        author_id=author.id, predicate_name="no-secrets-in-diff")

    diff = "+api_key = 'AKIAIOSFODNN7EXAMPLE'\n-old = 1\n"
    assert gate(session, diff=diff).refused


def test_the_gate_reads_additions_not_removals(ctx):
    """Deleting a secret is the fix, not the offence."""
    session, author, _ = ctx
    add(session, "No credentials in the diff", layer="code", rung=4,
        author_id=author.id, predicate_name="no-secrets-in-diff")

    removal = "-api_key = 'AKIAIOSFODNN7EXAMPLE'\n+api_key = os.environ['KEY']\n"
    assert gate(session, diff=removal).allowed


def test_a_rung_three_rule_does_not_run_at_the_gate(ctx):
    """A rung is a place. Neither can see what the other sees, which is why a
    rule that matters names both."""
    session, author, _ = ctx
    add(session, "No credentials in source", layer="code", rung=3,
        author_id=author.id, predicate_name="no-secrets")
    assert gate(session, diff="+api_key = 'AKIAIOSFODNN7EXAMPLE'\n").allowed


# --- moving a rule ----------------------------------------------------------

def test_promoting_prose_to_a_predicate_needs_one(ctx):
    """A rule promoted to a rung nothing enforces is worse than one left at
    rung 0, because it looks enforced."""
    session, author, approver = ctx
    rule = add(session, "No secrets", layer="code", rung=0, author_id=author.id)

    planned = plan_move(session, rule.id, 3)
    assert planned.is_promotion and planned.needs_predicate

    with pytest.raises(ValueError, match="looks enforced"):
        move(session, rule.id, 3, approver_id=approver.id)


def test_a_promotion_with_a_predicate_lands(ctx):
    session, author, approver = ctx
    rule = add(session, "No secrets", layer="code", rung=0, author_id=author.id)

    moved = move(session, rule.id, 3, approver_id=approver.id,
                 predicate_name="no-secrets")
    assert moved.rung == 3 and moved.predicate == "no-secrets"
    assert moved.moved_by == approver.id


def test_a_promoted_rule_starts_refusing(ctx):
    """The point of climbing: the same sentence, now a guarantee."""
    session, author, approver = ctx
    rule = add(session, "No secrets", layer="code", rung=0, author_id=author.id)
    args = {"content": "AWS_SECRET_ACCESS_KEY=AKIAIOSFODNN7EXAMPLE"}

    assert evaluate(session, tool="write_file", args=args).allowed
    move(session, rule.id, 3, approver_id=approver.id, predicate_name="no-secrets")
    assert evaluate(session, tool="write_file", args=args).refused


def test_a_demotion_is_recognised_as_one(ctx):
    """It is the one move that makes the system weaker, so it is named rather
    than treated as just another change."""
    session, author, approver = ctx
    rule = add(session, "No secrets", layer="code", rung=3, author_id=author.id,
               predicate_name="no-secrets")

    planned = plan_move(session, rule.id, 0)
    assert planned.direction == "demotion" and not planned.is_promotion


def test_a_demoted_rule_stops_refusing(ctx):
    """Which is exactly why it needs more sign-off, not less."""
    session, author, approver = ctx
    rule = add(session, "No secrets", layer="code", rung=3, author_id=author.id,
               predicate_name="no-secrets")
    args = {"content": "AWS_SECRET_ACCESS_KEY=AKIAIOSFODNN7EXAMPLE"}

    assert evaluate(session, tool="write_file", args=args).refused
    move(session, rule.id, 0, approver_id=approver.id)
    assert evaluate(session, tool="write_file", args=args).allowed


def test_an_unknown_rung_is_refused(ctx):
    session, author, approver = ctx
    rule = add(session, "x", layer="code", rung=0, author_id=author.id)
    with pytest.raises(ValueError, match="rung must be"):
        plan_move(session, rule.id, 9)


# --- the view ---------------------------------------------------------------

def test_the_view_shows_both_ladders_and_the_net_grant(ctx):
    session, author, _ = ctx
    add(session, "No execution", layer="harness", rung=1, author_id=author.id,
        withholds=["execute"])
    add(session, "No secrets", layer="code", rung=3, author_id=author.id,
        predicate_name="no-secrets")

    seen = view(session)
    assert len(seen["constraints"]) == 2
    assert seen["withheld"] == ["execute"]
    assert {p["name"] for p in seen["predicates"]} == set(PREDICATES)


def test_the_view_says_which_rules_are_mechanical(ctx):
    """Prose and a predicate look the same in a list until you say so."""
    session, author, _ = ctx
    add(session, "Be careful", layer="code", rung=0, author_id=author.id)
    add(session, "No secrets", layer="code", rung=3, author_id=author.id,
        predicate_name="no-secrets")

    by_text = {r["text"]: r for r in view(session)["constraints"]}
    assert by_text["Be careful"]["mechanical"] is False
    assert by_text["No secrets"]["mechanical"] is True


# --- predicates are registered, not loaded ----------------------------------

def test_predicates_are_a_registry_not_a_directory():
    """Dropping a .py into a folder is right for a kit you clone and own, and
    is arbitrary code execution as a feature in a multi-user server."""
    for name, spec in PREDICATES.items():
        assert callable(spec["fn"]) and spec["about"], name
        assert spec["sees"] in ("args", "diff"), name
