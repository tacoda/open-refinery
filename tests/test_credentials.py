"""The credential store — one catalog, per-user, verified before it is stored."""

import pytest

from open_refinery import credentials as creds
from open_refinery.credentials import (
    FORGE,
    MODEL,
    TRACKER,
    MissingField,
    NoCredential,
    UnknownProvider,
)
from open_refinery.store import connect
from open_refinery.users import create_user, ensure_default_roles


@pytest.fixture
def ctx(monkeypatch):
    """A store, two users, and every provider verifying without a network call."""
    monkeypatch.setattr(creds, "verify_credential",
                        lambda key, cred: {"account": f"{key}-account"})
    session = connect("sqlite:///:memory:")
    ensure_default_roles(session)
    dana, _ = create_user(session, "dana@example.com", "pw", "developer")
    sam, _ = create_user(session, "sam@example.com", "pw", "developer")
    return session, dana, sam


# --- the catalog ------------------------------------------------------------

def test_catalog_covers_all_three_families():
    families = {p["family"] for p in creds.catalog()}
    assert families == {MODEL, FORGE, TRACKER}


def test_catalog_can_be_filtered_by_family():
    assert all(p["family"] == FORGE for p in creds.catalog(FORGE))


def test_every_provider_says_what_its_credential_must_carry():
    """The Connections screen has to answer 'what do I paste here' without the
    reader leaving to go and search for it."""
    for p in creds.catalog():
        assert p["needs"], p["key"]


def test_secret_fields_are_marked_so_the_ui_can_mask_them():
    github = next(p for p in creds.catalog() if p["key"] == "github")
    assert next(f for f in github["fields"] if f["name"] == "token")["secret"] is True


def test_unknown_provider_is_rejected():
    with pytest.raises(UnknownProvider):
        creds.get_provider("not-a-service")


# --- validation -------------------------------------------------------------

def test_a_missing_required_field_names_the_field():
    with pytest.raises(MissingField, match="Personal access token"):
        creds.validate("github", {})


def test_a_blank_required_field_is_missing_not_present():
    with pytest.raises(MissingField):
        creds.validate("github", {"token": "   "})


def test_optional_fields_may_be_omitted():
    assert creds.validate("github-issues", {"token": "t"}) == {"token": "t"}


def test_undeclared_fields_are_dropped_not_stored():
    """A stray key a caller passed should not be quietly encrypted and kept."""
    assert creds.validate("github", {"token": "t", "sneaky": "x"}) == {"token": "t"}


# --- connecting -------------------------------------------------------------

def test_connect_stores_the_resolved_account_and_never_the_secret(ctx):
    session, dana, _ = ctx
    row = creds.connect(session, dana.id, "github", {"token": "ghp_xyz"})

    assert row.account == "github-account"
    assert "ghp_xyz" not in row.secret          # encrypted at rest
    assert "ghp_xyz" not in str(creds.public(row))


def test_connect_refuses_a_credential_that_does_not_authenticate(ctx, monkeypatch):
    """Nothing is saved that was never going to work, so the Connections screen
    never shows a connection that cannot be used."""
    session, dana, _ = ctx

    def boom(key, cred):
        raise RuntimeError("401 Unauthorized")
    monkeypatch.setattr(creds, "verify_credential", boom)

    with pytest.raises(RuntimeError, match="401"):
        creds.connect(session, dana.id, "github", {"token": "bad"})
    assert creds.list_for(session, dana.id) == []


def test_credential_round_trips_through_encryption(ctx):
    session, dana, _ = ctx
    row = creds.connect(session, dana.id, "jira",
                        {"site": "acme.atlassian.net", "email": "d@x.io", "token": "t"})
    assert creds.credential_of(session, row.id) == {
        "site": "acme.atlassian.net", "email": "d@x.io", "token": "t"}


def test_an_identity_credential_cannot_be_shared_org_wide(ctx):
    """A forge token *is* an identity. Sharing it would attribute one person's
    pull requests to everybody."""
    session, dana, _ = ctx
    with pytest.raises(ValueError, match="personal"):
        creds.connect(session, dana.id, "github", {"token": "t"}, shared=True)


def test_a_model_key_may_be_shared_because_it_is_billing_not_identity(ctx):
    session, dana, _ = ctx
    row = creds.connect(session, dana.id, "anthropic", {"api_key": "sk"}, shared=True)
    assert row.shared is True


# --- scoping ----------------------------------------------------------------

def test_credentials_are_scoped_to_their_owner(ctx):
    session, dana, sam = ctx
    creds.connect(session, dana.id, "github", {"token": "dana"})
    creds.connect(session, sam.id, "github", {"token": "sam"})

    assert len(creds.list_for(session, dana.id)) == 1
    assert len(creds.list_for(session, sam.id)) == 1
    assert len(creds.list_for(session, None)) == 2      # oversight sees all


def test_listing_can_be_filtered_by_family(ctx):
    session, dana, _ = ctx
    creds.connect(session, dana.id, "github", {"token": "t"})
    creds.connect(session, dana.id, "anthropic", {"api_key": "sk"})

    assert len(creds.list_for(session, dana.id, family=MODEL)) == 1
    assert len(creds.list_for(session, dana.id, family=FORGE)) == 1


# --- resolution: whose key does a run use -----------------------------------

def test_an_actor_gets_their_own_credential(ctx):
    session, dana, sam = ctx
    creds.connect(session, dana.id, "github", {"token": "dana-token"})
    creds.connect(session, sam.id, "github", {"token": "sam-token"})

    assert creds.for_actor(session, dana.id, "github")["token"] == "dana-token"
    assert creds.for_actor(session, sam.id, "github")["token"] == "sam-token"


def test_an_actor_without_a_credential_never_falls_back_to_someone_elses(ctx):
    """The failure this prevents: Sam's work opening a pull request as Dana, and
    the audit trail naming the wrong person."""
    session, dana, sam = ctx
    creds.connect(session, dana.id, "github", {"token": "dana-token"})

    with pytest.raises(NoCredential):
        creds.for_actor(session, sam.id, "github")


def test_a_shared_model_key_is_the_fallback_when_the_actor_has_none(ctx):
    session, dana, sam = ctx
    creds.connect(session, dana.id, "anthropic", {"api_key": "org-key"}, shared=True)

    assert creds.for_actor(session, sam.id, "anthropic")["api_key"] == "org-key"


def test_an_actors_own_key_beats_the_shared_one(ctx):
    session, dana, sam = ctx
    creds.connect(session, dana.id, "anthropic", {"api_key": "org-key"}, shared=True)
    creds.connect(session, sam.id, "anthropic", {"api_key": "sams-key"})

    assert creds.for_actor(session, sam.id, "anthropic")["api_key"] == "sams-key"


def test_a_non_shareable_provider_has_no_org_fallback(ctx):
    """Even if a row is somehow marked shared, a forge token must not resolve
    for anybody but its owner."""
    session, dana, sam = ctx
    row = creds.connect(session, dana.id, "github", {"token": "dana-token"})
    row.shared = True                      # force it past the connect-time guard
    session.add(row)
    session.commit()

    with pytest.raises(NoCredential):
        creds.for_actor(session, sam.id, "github")


def test_no_credential_error_names_the_provider(ctx):
    session, _, sam = ctx
    with pytest.raises(NoCredential) as exc:
        creds.for_actor(session, sam.id, "linear")
    assert exc.value.provider == "linear"
    assert "Connections" in str(exc.value)


# --- lifecycle --------------------------------------------------------------

def test_recheck_records_a_credential_that_has_stopped_working(ctx, monkeypatch):
    """A key that worked at connect time and was later revoked is invisible
    until something tries to use it."""
    session, dana, _ = ctx
    row = creds.connect(session, dana.id, "github", {"token": "t"})

    def revoked(key, cred):
        raise RuntimeError("401 Unauthorized")
    monkeypatch.setattr(creds, "verify_credential", revoked)

    result = creds.recheck(session, row.id)
    assert result["status"] == "failing"
    assert "401" in result["status_detail"]


def test_recheck_clears_a_failing_status_once_it_works_again(ctx):
    session, dana, _ = ctx
    row = creds.connect(session, dana.id, "github", {"token": "t"})
    row.status, row.status_detail = "failing", "old news"
    session.add(row)
    session.commit()

    assert creds.recheck(session, row.id)["status"] == "ok"


def test_rotate_keeps_the_same_id_so_nothing_referencing_it_breaks(ctx):
    session, dana, _ = ctx
    row = creds.connect(session, dana.id, "github", {"token": "old"})

    rotated = creds.rotate(session, row.id, {"token": "new"})
    assert rotated["id"] == row.id
    assert creds.credential_of(session, row.id) == {"token": "new"}


def test_rotate_refuses_a_replacement_that_does_not_authenticate(ctx, monkeypatch):
    """Rotating to a broken key must not leave the connection worse than it
    was — the old one keeps working until a good one replaces it."""
    session, dana, _ = ctx
    row = creds.connect(session, dana.id, "github", {"token": "good"})

    def boom(key, cred):
        raise RuntimeError("401 Unauthorized")
    monkeypatch.setattr(creds, "verify_credential", boom)

    with pytest.raises(RuntimeError):
        creds.rotate(session, row.id, {"token": "bad"})
    assert creds.credential_of(session, row.id) == {"token": "good"}


def test_revoke_removes_the_credential(ctx):
    session, dana, _ = ctx
    row = creds.connect(session, dana.id, "github", {"token": "t"})
    creds.revoke(session, row.id)

    assert creds.list_for(session, dana.id) == []
    with pytest.raises(NoCredential):
        creds.for_actor(session, dana.id, "github")


def test_public_projection_never_leaks_the_secret(ctx):
    session, dana, _ = ctx
    row = creds.connect(session, dana.id, "jira",
                        {"site": "s", "email": "e", "token": "super-secret"})
    assert "secret" not in creds.public(row)
    assert "super-secret" not in str(creds.public(row))
