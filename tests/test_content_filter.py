"""The content filter, and the two different questions it answers.

Until 3.0 there was one list, scanned over every tool call's arguments. It
refused ordinary work — a `git commit --author`, a `package.json`, a CODEOWNERS
file, any 13-digit literal — with "Secrets do not leave this machine", while
nothing had left anything. These tests pin both halves of the split.
"""

import pytest

from open_refinery.policies import scan_content


# --- what used to be refused and is now ordinary work -----------------------

@pytest.mark.parametrize("text", [
    'git commit --author="Ian <ian@example.com>"',
    '{"author": "team@acme.dev", "name": "my-app"}',      # package.json
    "* @acme/platform-team",                               # CODEOWNERS
    "const TWITTER_EPOCH = 1288834974657;",                # 13 digits
    "see CHANGELOG 2024 01 02 03 04 05 06",
    "x = 12345678901234",
])
def test_local_writes_are_not_refused(text):
    """A run writes files in its own worktree all day. Scanning those for email
    addresses refuses the work rather than protecting anything."""
    clean, hits = scan_content(text)
    assert hits == []
    assert clean == text


# --- what is a secret wherever it appears -----------------------------------

@pytest.mark.parametrize("text,kind", [
    ("AKIAIOSFODNN7EXAMPLE", "aws-key"),
    ("token = ghp_abcdefghijklmnopqrstuvwxyz0123", "bearer-token"),
    ("glpat-abcdefghijklmnopqrstuvwx", "bearer-token"),
    ("-----BEGIN RSA PRIVATE KEY-----", "private-key"),
    ("-----BEGIN PRIVATE KEY-----", "private-key"),
])
def test_a_secret_is_caught_everywhere(text, kind):
    """No legitimate source file contains a live credential, so writing one into
    your own checkout is as much of a mistake as posting it."""
    clean, hits = scan_content(text)
    assert hits == [kind]
    assert f"[redacted:{kind}]" in clean
    # and still caught on the way out
    assert kind in scan_content(text, egress=True)[1]


# --- what only matters on the way out ---------------------------------------

def test_personal_data_passes_locally_and_is_redacted_on_egress():
    text = "ping ian@example.com about it"
    assert scan_content(text)[1] == []
    clean, hits = scan_content(text, egress=True)
    assert hits == ["email"]
    assert "ian@example.com" not in clean


def test_a_real_card_number_is_redacted_on_egress():
    for number in ("4242 4242 4242 4242", "4242424242424242", "4111-1111-1111-1111"):
        clean, hits = scan_content(f"paid with {number}", egress=True)
        assert hits == ["credit-card"], number
        assert number not in clean


def test_a_digit_run_that_is_not_a_card_survives_even_on_egress():
    """The Luhn check is what separates a filter from noise: a random run of
    digits passes about one time in ten without it."""
    for number in ("1234567890123", "12345678901234", "2024 01 02 03 04 05 06"):
        clean, hits = scan_content(f"id = {number}", egress=True)
        assert hits == [], number
        assert number in clean


def test_luhn_rejects_a_near_miss():
    from open_refinery.policies import _luhn

    assert _luhn("4242424242424242") is True
    assert _luhn("4242424242424243") is False      # one digit off
    assert _luhn("42424242") is False              # too short
    assert _luhn("not-a-number") is False


# --- both at once ------------------------------------------------------------

def test_egress_applies_both_sets_and_reports_each_once():
    text = ("mail ian@example.com, key AKIAIOSFODNN7EXAMPLE, "
            "also ops@example.com")
    clean, hits = scan_content(text, egress=True)
    assert sorted(hits) == ["aws-key", "email"]
    assert "example.com" not in clean and "AKIA" not in clean
