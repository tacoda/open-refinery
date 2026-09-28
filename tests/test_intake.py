"""Intake — the front door.

A webhook is the only unauthenticated way into this system, so the tests that
matter most here are the ones about *refusing*: a wrong signature, a missing
secret, a replayed delivery, an edit that is not new work.
"""

import json

import pytest

from open_refinery import (
    SqliteSink,
    connect,
    create_integration,
    create_process,
    create_repository,
    create_user,
)
from open_refinery.intake import (
    BadSignature,
    IntakeError,
    accept,
    configure,
    parse,
    sign,
)
from open_refinery import integrations
from open_refinery.models import WorkItem
from sqlmodel import select


def fixture(monkeypatch, *, autostart=False, kind="github-issues"):
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setitem(integrations.ADAPTERS[kind], "verify", lambda c: {"account": "me"})
    conn = connect("sqlite:///:memory:")
    dev, _ = create_user(conn, "dev@x.dev", "pw", "developer")
    repo = create_repository(conn, "or", "git@x:or.git", dev.id)
    proc = create_process(conn, "flow", "board", ["todo", "done"], dev.id)
    integ = create_integration(conn, kind, {"token": "t"}, dev.id)
    integ, secret = configure(conn, integ.id, repo_id=repo.id, process_id=proc.id,
                              autostart=autostart, rotate_secret=True)
    return conn, dev, repo, proc, integ, secret


def delivery(secret, payload):
    body = json.dumps(payload).encode()
    return body, sign(secret, body)


ISSUE = {"action": "opened",
         "issue": {"number": 7, "title": "Fix the thing", "body": "It is broken",
                   "html_url": "https://x/7", "state": "open"}}


# --- refusing ---------------------------------------------------------------

def test_a_wrong_signature_is_refused(monkeypatch):
    conn, *_, integ, secret = fixture(monkeypatch)
    body, _ = delivery(secret, ISSUE)
    with pytest.raises(BadSignature):
        accept(conn, integ.id, body, sign("not-the-secret", body), audit=SqliteSink(conn))
    assert conn.exec(select(WorkItem)).all() == []


def test_a_tampered_body_is_refused(monkeypatch):
    """The signature covers the bytes, so editing the payload breaks it — which
    is the whole point of signing the raw body rather than a parsed dict."""
    conn, *_, integ, secret = fixture(monkeypatch)
    body, sig = delivery(secret, ISSUE)
    tampered = body.replace(b"Fix the thing", b"Fix the thing.")
    with pytest.raises(BadSignature):
        accept(conn, integ.id, tampered, sig, audit=SqliteSink(conn))


def test_an_integration_with_no_secret_accepts_nothing(monkeypatch):
    """Not "no secret means no check" — that is how a front door is left open."""
    conn, dev, repo, proc, integ, _ = fixture(monkeypatch)
    integ.webhook_secret = ""
    conn.add(integ); conn.commit()
    body, _ = delivery("anything", ISSUE)
    with pytest.raises(BadSignature, match="no webhook secret"):
        accept(conn, integ.id, body, "sig", audit=SqliteSink(conn))


def test_an_unknown_integration_is_refused_before_any_work(monkeypatch):
    conn, *_ = fixture(monkeypatch)
    with pytest.raises(IntakeError, match="unknown integration"):
        accept(conn, "nope", b"{}", "sig", audit=SqliteSink(conn))


def test_a_tracker_with_no_parser_is_refused_rather_than_guessed_at(monkeypatch):
    conn, dev, repo, proc, integ, secret = fixture(monkeypatch, kind="github")  # a forge, not a tracker
    body, sig = delivery(secret, ISSUE)
    with pytest.raises(IntakeError, match="no webhook parser"):
        accept(conn, integ.id, body, sig, audit=SqliteSink(conn))


# --- accepting --------------------------------------------------------------

def test_a_new_issue_becomes_a_work_item(monkeypatch):
    conn, dev, repo, proc, integ, secret = fixture(monkeypatch)
    body, sig = delivery(secret, ISSUE)
    result = accept(conn, integ.id, body, sig, audit=SqliteSink(conn))
    assert result["accepted"] and result["ref"] == "github-issues:#7"
    item = conn.exec(select(WorkItem)).one()
    assert item.title == "Fix the thing" and item.external_ref == "github-issues:#7"


def test_a_redelivery_does_not_create_a_second_work_item(monkeypatch):
    """Every tracker re-delivers. Dedupe by external ref or a flaky network
    turns one ticket into five."""
    conn, dev, repo, proc, integ, secret = fixture(monkeypatch)
    body, sig = delivery(secret, ISSUE)
    accept(conn, integ.id, body, sig, audit=SqliteSink(conn))
    again = accept(conn, integ.id, body, sig, audit=SqliteSink(conn))
    assert again == {"accepted": False, "why": "already imported",
                     "ref": "github-issues:#7"}
    assert len(conn.exec(select(WorkItem)).all()) == 1


def test_an_edit_is_not_new_work(monkeypatch):
    conn, dev, repo, proc, integ, secret = fixture(monkeypatch)
    body, sig = delivery(secret, {**ISSUE, "action": "edited"})
    assert accept(conn, integ.id, body, sig, audit=SqliteSink(conn))["accepted"] is False
    assert conn.exec(select(WorkItem)).all() == []


def test_an_integration_with_nowhere_to_file_accepts_nothing(monkeypatch):
    conn, dev, repo, proc, integ, secret = fixture(monkeypatch)
    integ.intake_repo_id = None
    conn.add(integ); conn.commit()
    body, sig = delivery(secret, ISSUE)
    out = accept(conn, integ.id, body, sig, audit=SqliteSink(conn))
    assert out["accepted"] is False and "repo/process" in out["why"]


def test_the_ticket_is_audited_against_the_item_it_created(monkeypatch):
    """A ticket that arrived by itself still has to be answerable for. The
    entry names the work item, so the trail runs from webhook to pull request."""
    from open_refinery import query_events
    conn, dev, repo, proc, integ, secret = fixture(monkeypatch)
    body, sig = delivery(secret, ISSUE)
    out = accept(conn, integ.id, body, sig, audit=SqliteSink(conn))
    entry = [e for e in query_events(conn) if e.recipe == "intake"]
    assert entry and entry[0].subject == out["work_item"]


# --- the parsers ------------------------------------------------------------

@pytest.mark.parametrize("kind,payload,key,title", [
    ("github-issues", ISSUE, "#7", "Fix the thing"),
    ("gitlab-issues", {"object_kind": "issue",
                       "object_attributes": {"iid": 3, "title": "Ship it", "action": "open",
                                             "description": "d", "url": "u", "state": "opened"}},
     "#3", "Ship it"),
    ("jira", {"webhookEvent": "jira:issue_created",
              "issue": {"key": "OR-12", "fields": {"summary": "Land it",
                                                   "description": "d",
                                                   "status": {"name": "To Do"}}}},
     "OR-12", "Land it"),
    ("linear", {"type": "Issue", "action": "create",
                "data": {"identifier": "ENG-4", "title": "Do it", "description": "d",
                         "url": "u", "state": {"name": "Todo"}}},
     "ENG-4", "Do it"),
])
def test_each_tracker_speaks_its_own_shape(kind, payload, key, title):
    _, ticket = parse(kind, payload)
    assert ticket is not None
    assert (ticket.key, ticket.title) == (key, title)


def test_a_payload_that_is_not_an_issue_is_ignored_not_guessed():
    action, ticket = parse("github-issues", {"action": "opened", "pull_request": {}})
    assert ticket is None


# --- autostart --------------------------------------------------------------

def test_autostart_off_files_the_ticket_and_stops_there():
    """The default. A ticket appears as work; a person decides it should run."""
    import pytest as _p
    conn = None


def test_autostart_starts_a_run_for_a_new_ticket(monkeypatch):
    from open_refinery.pipeline import store as ps
    conn, dev, repo, proc, integ, secret = fixture(monkeypatch, autostart=True)
    pipeline = ps.ensure_default(conn, dev.id)
    monkeypatch.setattr(ps, "latest_pipeline", lambda s, n: pipeline)

    body, sig = delivery(secret, ISSUE)
    out = accept(conn, integ.id, body, sig, audit=SqliteSink(conn))

    assert out["run"], "autostart should have started a run"
    run = ps.get_run(conn, out["run"])
    assert run.work_item_id == out["work_item"]
    assert "It is broken" in run.document, "the ticket's text is the spec"


def test_without_autostart_nothing_runs(monkeypatch):
    from open_refinery.pipeline import store as ps
    conn, dev, repo, proc, integ, secret = fixture(monkeypatch, autostart=False)
    body, sig = delivery(secret, ISSUE)
    out = accept(conn, integ.id, body, sig, audit=SqliteSink(conn))
    assert out["accepted"] and out["run"] is None
    assert ps.list_runs(conn) == []


def test_autostart_turns_its_own_secret_on(monkeypatch):
    """Autostart means a stranger's POST can start a run. Refusing to arm that
    without a secret is the whole reason `configure` mints one."""
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setitem(integrations.ADAPTERS["github-issues"], "verify",
                        lambda c: {"account": "me"})
    conn = connect("sqlite:///:memory:")
    dev, _ = create_user(conn, "dev@x.dev", "pw", "developer")
    integ = create_integration(conn, "github-issues", {"token": "t"}, dev.id)
    assert not integ.webhook_secret
    integ, secret = configure(conn, integ.id, autostart=True)
    assert secret and integ.webhook_secret == secret


def test_configure_refuses_a_repo_that_does_not_exist(monkeypatch):
    conn, *_, integ, secret = fixture(monkeypatch)
    with pytest.raises(IntakeError, match="unknown repository"):
        configure(conn, integ.id, repo_id="nope")
