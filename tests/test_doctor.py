"""Preflight checks. A check that diagnoses without a remedy has done half the job."""

from open_refinery.doctor import (
    FAIL,
    OK,
    WARN,
    check_admin,
    check_audit_chain,
    check_database,
    check_repositories,
    check_secret_key,
    doctor,
)
from open_refinery.repositories import create_repository
from open_refinery.store import connect
from open_refinery.users import create_user, ensure_default_roles


def _session():
    s = connect("sqlite:///:memory:")
    ensure_default_roles(s)
    return s


def test_missing_secret_key_fails_with_a_remedy():
    check = check_secret_key({})
    assert check.status == FAIL
    assert "open-refinery init" in check.remedy


def test_short_secret_key_warns_rather_than_fails():
    """It works — it is just weak. Failing would stop an install that runs."""
    assert check_secret_key({"SECRET_KEY": "short"}).status == WARN


def test_good_secret_key_passes_without_echoing_it():
    check = check_secret_key({"SECRET_KEY": "x" * 43})
    assert check.status == OK
    assert "x" * 43 not in check.detail


def test_unopenable_database_fails():
    check = check_database("sqlite:///nope.db", None)
    assert check.status == FAIL
    assert "migrate" in check.remedy


def test_database_check_reports_schema_and_user_count():
    check = check_database("sqlite:///:memory:", _session())
    assert check.status == OK
    assert "no users yet" in check.detail


def test_no_users_warns_and_names_both_ways_in():
    check = check_admin(_session())
    assert check.status == WARN
    assert "create-admin" in check.remedy


def test_admin_present_passes():
    session = _session()
    create_user(session, "a@example.com", "pw", "admin")
    assert check_admin(session).status == OK


def test_empty_audit_chain_verifies():
    assert check_audit_chain(_session()).status == OK


def test_repository_that_is_not_a_checkout_warns_and_names_it():
    """A run makes a worktree off a local checkout; an un-cloned repo is the
    first thing it fails on, so doctor says so before a run does."""
    session = _session()
    owner, _ = create_user(session, "a@example.com", "pw", "admin")
    create_repository(session, "web", "git@github.com:acme/web.git", owner.id)

    check = check_repositories(session)
    assert check.status == WARN
    assert "web" in check.detail
    assert "clone" in check.remedy


def test_repository_with_a_local_checkout_passes(tmp_path):
    session = _session()
    owner, _ = create_user(session, "a@example.com", "pw", "admin")
    (tmp_path / ".git").mkdir()
    create_repository(session, "web", str(tmp_path), owner.id)
    assert check_repositories(session).status == OK


def test_no_repositories_warns_with_a_remedy():
    check = check_repositories(_session())
    assert check.status == WARN
    assert "add a repository" in check.remedy


def test_report_fails_when_any_check_fails():
    report = doctor(None, environ={}, database_url="sqlite:///nope.db")
    assert report.failed is True


def test_report_counts_every_check():
    report = doctor(_session(), environ={"SECRET_KEY": "x" * 43},
                    database_url="sqlite:///:memory:")
    assert sum(report.counts.values()) == len(report.checks)
    assert report.failed is False


def test_every_non_ok_check_offers_a_remedy_or_says_it_was_skipped():
    """The point of a check is to shorten the search. One that only says
    something is wrong makes the reader go and find the fix themselves."""
    report = doctor(None, environ={}, database_url="sqlite:///nope.db")
    for check in report.checks:
        if check.status != OK:
            assert check.remedy or "skipped" in check.detail, check.name
