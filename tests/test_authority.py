"""Permissions — held on the person, and the only thing ever checked.

Three shapes led here. A rank ladder (`developer < platform < admin`) meant
admin could do everything platform could. Powers on a *role* fixed that but kept
the indirection. Now the set is on the user.
"""

import pytest

from open_refinery import authority as a
from open_refinery.authority import (
    LAYERS,
    PERMISSIONS,
    PRESETS,
    clean,
    of_preset,
)
from open_refinery.store import connect
from open_refinery.users import create_user, ensure_presets


@pytest.fixture
def session():
    s = connect("sqlite:///:memory:")
    ensure_presets(s)
    return s


def _user(session, preset, **kw):
    user, _ = create_user(session, f"{preset}-{kw.get('n', 0)}@x.io", "pw", preset,
                          permissions=kw.get("permissions"))
    return user


# --- the separation ---------------------------------------------------------

def test_a_developer_approves_code_only(session):
    dev = _user(session, "developer")
    assert a.may_approve(dev, "code")
    assert not a.may_approve(dev, "harness")
    assert not a.may_approve(dev, "factory")


def test_a_lead_owns_the_harness(session):
    lead = _user(session, "lead")
    assert a.may_approve(lead, "harness") and a.may_approve(lead, "charter")
    assert not a.may_approve(lead, "factory")


def test_platform_owns_the_factory(session):
    ops = _user(session, "platform")
    assert a.may_approve(ops, "factory")
    assert not a.may_approve(ops, "harness")


def test_neither_lead_nor_platform_approves_ordinary_code(session):
    """That review is a developer's job."""
    for preset in ("lead", "platform"):
        assert not a.may_approve(_user(session, preset), "code"), preset


def test_admin_approves_nothing(session):
    """The account that grants access does not approve what ships: a
    compromised admin can create users and read the log, and cannot merge a
    change or weaken a rule."""
    boss = _user(session, "admin")
    for layer in LAYERS:
        assert not a.may_approve(boss, layer), layer
    assert a.manages_users(boss) and a.reads_audit(boss)


def test_only_platform_sees_other_peoples_work(session):
    assert a.sees_operations(_user(session, "platform"))
    for preset in ("developer", "lead", "admin"):
        assert not a.sees_operations(_user(session, preset)), preset


def test_admin_cannot_trigger_a_run(session):
    assert not a.may_run(_user(session, "admin"))
    assert a.may_run(_user(session, "developer"))


# --- proposing is wider than approving --------------------------------------

def test_a_developer_may_propose_anything_but_approve_only_code(session):
    """The asymmetry the improve lane runs on."""
    dev = _user(session, "developer")
    for layer in LAYERS:
        assert a.may_propose(dev, layer), layer
    assert [l for l in LAYERS if a.may_approve(dev, l)] == ["code"]


# --- fail closed ------------------------------------------------------------

def test_a_user_with_no_permissions_can_do_nothing(session):
    nobody = _user(session, "developer", permissions=[])
    for layer in LAYERS:
        assert not a.may_approve(nobody, layer)
        assert not a.may_propose(nobody, layer)
    assert not a.manages_users(nobody) and not a.reads_audit(nobody)
    assert not a.sees_operations(nobody) and not a.may_run(nobody)


def test_an_unknown_permission_is_dropped_not_stored(session):
    """One nothing checks is one somebody believes they have."""
    u = _user(session, "developer", permissions=["approve:code", "approve:everything"])
    assert u.permissions == ["approve:code"]


def test_an_unknown_layer_is_never_approvable(session):
    dev = _user(session, "developer")
    assert not a.may_approve(dev, "not-a-layer")
    assert not a.may_propose(dev, "not-a-layer")


def test_a_principal_with_no_permissions_attribute_is_denied(session):
    """Anything that reaches a guard without a set — a stub, a bug — is denied
    rather than waved through."""
    class Bare:
        pass
    assert not a.has(Bare(), "read:audit")
    assert not a.manages_users(Bare())


def test_clean_is_deduped_and_ordered(session):
    assert clean(["run:factory", "approve:code", "run:factory"]) == \
        ["approve:code", "run:factory"]


# --- presets are a starting point, not a role -------------------------------

def test_every_preset_applies_only_real_permissions():
    for name, perms in PRESETS.items():
        assert set(perms) <= set(PERMISSIONS), name


def test_the_presets_cover_every_layer():
    """A layer nobody can approve is a layer where nothing ships."""
    approvable = {p.split(":", 1)[1] for perms in PRESETS.values()
                  for p in perms if p.startswith("approve:")}
    assert approvable == set(LAYERS)


def test_editing_a_preset_does_not_change_existing_users(session):
    """The honest cost of putting the set on the user — and the UI says so."""
    from open_refinery.users import create_role

    dev = _user(session, "developer")
    before = list(dev.permissions)

    create_role(session, "developer", 1, permissions=["read:audit"])
    session.refresh(dev)

    assert dev.permissions == before
    assert not a.reads_audit(dev)


def test_a_user_can_be_created_with_permissions_no_preset_offers(session):
    """Two people doing similar jobs can differ without inventing a role."""
    odd = _user(session, "developer",
                permissions=["approve:code", "approve:harness", "read:audit"])
    assert a.may_approve(odd, "code") and a.may_approve(odd, "harness")
    assert a.reads_audit(odd)


def test_an_unknown_preset_applies_nothing():
    assert of_preset("not-a-preset") == []


# --- who do I ask -----------------------------------------------------------

def test_approvers_of_names_the_people_not_the_role(session):
    """What somebody blocked actually needs is a person."""
    lead = _user(session, "lead")
    _user(session, "developer")
    assert a.approvers_of(session, "harness") == [lead.email]


def test_approvers_of_skips_deactivated_people(session):
    from open_refinery.users import set_active

    lead = _user(session, "lead")
    set_active(session, lead.id, False)
    assert a.approvers_of(session, "harness") == []


def test_approvers_of_an_unknown_layer_is_empty(session):
    assert a.approvers_of(session, "not-a-layer") == []


# --- the editor's vocabulary ------------------------------------------------

def test_every_permission_is_described():
    """A checkbox whose meaning you have to guess is one that gets ticked."""
    described = {row["permission"] for row in a.catalog() if row["description"]}
    assert described == set(PERMISSIONS)
