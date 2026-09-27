"""Preflight checks. A check that diagnoses without a remedy has done half the job."""

from open_refinery.doctor import (
    FAIL,
    OK,
    WARN,
    check_admin,
    check_audit_chain,
    check_database,
    check_secret_key,
    check_targets,
    doctor,
)
from open_refinery.store import connect
from open_refinery.targets import create_target
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


def test_target_without_a_credential_warns_and_names_it():
    session = _session()
    owner, _ = create_user(session, "a@example.com", "pw", "admin")
    create_target(session, "bare-model", "model", "claude-opus-5", owner.id)

    check = check_targets(session)
    assert check.status == WARN
    assert "bare-model" in check.detail


def test_target_with_a_credential_passes():
    session = _session()
    owner, _ = create_user(session, "a@example.com", "pw", "admin")
    create_target(session, "m", "model", "claude-opus-5", owner.id,
                  credential={"api_key": "sk-test"})
    assert check_targets(session).status == OK


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
