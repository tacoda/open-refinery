"""Authority — what a role may do, and what it must not.

The old model was a rank ladder, so admin could do everything platform could.
These tests pin the separation that replaced it, and the fail-closed behaviour
that the rank model got backwards.
"""

import pytest

from open_refinery import authority
from open_refinery.authority import (
    BUILTIN,
    CODE,
    LAYERS,
    approvers_for,
    describe,
    manages_users,
    may_approve,
    may_propose,
    reads_audit,
    sees_operations,
)
from open_refinery.store import connect
from open_refinery.users import create_role, ensure_default_roles


@pytest.fixture
def session():
    s = connect("sqlite:///:memory:")
    ensure_default_roles(s)
    return s


# --- the separation ---------------------------------------------------------

def test_developer_approves_code_only(session):
    assert may_approve(session, "developer", CODE)
    assert not may_approve(session, "developer", "harness")
    assert not may_approve(session, "developer", "factory")


def test_lead_owns_the_harness(session):
    assert may_approve(session, "lead", "harness")
    assert may_approve(session, "lead", "charter")
    assert not may_approve(session, "lead", "factory")


def test_platform_owns_the_factory(session):
    assert may_approve(session, "platform", "factory")
    assert not may_approve(session, "platform", "harness")


def test_neither_lead_nor_platform_approves_ordinary_code(session):
    """A lead reviewing a teammate's pull request has no special authority over
    it — that review is a developer's job."""
    assert not may_approve(session, "lead", CODE)
    assert not may_approve(session, "platform", CODE)


def test_admin_approves_nothing(session):
    """The role that grants access does not approve what ships. A compromised
    admin account can create users and read the log, and cannot merge a change
    or weaken a rule."""
    for layer in LAYERS:
        assert not may_approve(session, "admin", layer), layer


def test_admin_is_not_a_superset_of_platform(session):
    """The whole point of replacing the rank ladder."""
    assert may_approve(session, "platform", "factory")
    assert not may_approve(session, "admin", "factory")


def test_only_admin_manages_users_and_reads_audit(session):
    assert manages_users(session, "admin") and reads_audit(session, "admin")
    for role in ("developer", "lead", "platform"):
        assert not manages_users(session, role), role
        assert not reads_audit(session, role), role


def test_only_platform_sees_other_peoples_operations(session):
    assert sees_operations(session, "platform")
    for role in ("developer", "lead", "admin"):
        assert not sees_operations(session, role), role


# --- proposing is wider than approving --------------------------------------

def test_a_developer_may_propose_anything_but_approve_only_code(session):
    """That asymmetry is what the improve lane runs on."""
    for layer in LAYERS:
        assert may_propose(session, "developer", layer), layer
    assert [l for l in LAYERS if may_approve(session, "developer", l)] == [CODE]


def test_admin_proposes_nothing_either(session):
    for layer in LAYERS:
        assert not may_propose(session, "admin", layer), layer


# --- fail closed ------------------------------------------------------------

def test_an_unknown_role_has_no_authority(session):
    """The rank model failed OPEN here: role_rank() returned 0 for a role that
    did not exist, so `at_least(developer, "senior")` was True."""
    for layer in LAYERS:
        assert not may_approve(session, "senior", layer)
        assert not may_propose(session, "senior", layer)
    assert not manages_users(session, "senior")
    assert not reads_audit(session, "senior")
    assert not sees_operations(session, "senior")


def test_an_empty_role_name_has_no_authority(session):
    assert not may_approve(session, "", CODE)
    assert not manages_users(session, "")


def test_an_unknown_layer_is_never_approvable(session):
    for role in ("developer", "lead", "platform", "admin"):
        assert not may_approve(session, role, "not-a-layer"), role


def test_a_custom_role_starts_with_no_powers(session):
    """A new role grants nothing until someone says what it may do — rather
    than inheriting authority from where its rank happens to land."""
    create_role(session, "reviewer", 2)
    for layer in LAYERS:
        assert not may_approve(session, "reviewer", layer), layer
    assert not sees_operations(session, "reviewer")


# --- who do I ask -----------------------------------------------------------

def test_approvers_for_names_the_owning_role(session):
    assert approvers_for(session, "harness") == ["lead"]
    assert approvers_for(session, "factory") == ["platform"]
    assert approvers_for(session, CODE) == ["developer"]


def test_approvers_are_ordered_weakest_first(session):
    from open_refinery.models import Role

    create_role(session, "reviewer", 0)          # below developer(1)
    row = session.get(Role, "reviewer")
    row.approves = [CODE]
    session.add(row)
    session.commit()

    assert approvers_for(session, CODE) == ["reviewer", "developer"]


def test_every_layer_has_at_least_one_approver(session):
    """A layer nobody can approve is a layer where nothing ever ships."""
    for layer in LAYERS:
        assert approvers_for(session, layer), layer


# --- the role row is the source of truth ------------------------------------

def test_powers_come_from_the_row_not_the_constant(session):
    """Roles are customizable, so editing the row changes authority — the
    BUILTIN dict is a seed, not a hardcoded check."""
    from open_refinery.models import Role

    row = session.get(Role, "platform")
    row.approves = ["harness"]
    session.add(row)
    session.commit()

    assert may_approve(session, "platform", "harness")
    assert not may_approve(session, "platform", "factory")


def test_seeding_is_idempotent_and_backfills_an_upgraded_install(session):
    """An install from before 2.14.5 has developer/platform/admin rows with no
    powers on them, and a role with no powers can do nothing."""
    from open_refinery.models import Role

    row = session.get(Role, "platform")
    row.approves, row.sees_operations = [], False   # simulate the upgraded row
    session.add(row)
    session.commit()

    ensure_default_roles(session)
    assert may_approve(session, "platform", "factory")
    assert sees_operations(session, "platform")


def test_a_custom_role_survives_reseeding(session):
    create_role(session, "reviewer", 2)
    ensure_default_roles(session)
    assert describe(session, "reviewer")["name"] == "reviewer"


def test_describe_reports_builtin_status(session):
    assert describe(session, "lead")["builtin"] is True
    create_role(session, "reviewer", 2)
    assert describe(session, "reviewer")["builtin"] is False


def test_describe_of_an_unknown_role_is_empty(session):
    assert describe(session, "senior") == {}


def test_the_standard_configuration_covers_every_layer(session):
    """A shipped default where some layer had no owner would be a factory with
    a stage nobody can sign off."""
    owned = {layer for role in BUILTIN for layer in BUILTIN[role]["approves"]}
    assert owned == set(LAYERS)
