import pytest

from open_refinery import (
    SqliteSink,
    connect,
    create_integration,
    create_process,
    create_repository,
    create_user,
    find_by_external_ref,
    list_work_items,
    query_events,
    sync_tracker,
)
from open_refinery import integrations


def build(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setitem(integrations.ADAPTERS["linear"], "verify", lambda c: {"account": "me"})
    conn = connect("sqlite:///:memory:")
    ian, _ = create_user(conn, "ian@x.dev", "pw", "developer")
    repo = create_repository(conn, "or", "git@x:or.git", ian.id)
    proc = create_process(conn, "flow", "board", ["todo", "done"], ian.id)
    integ = create_integration(conn, "linear", {"token": "lin_tok"}, ian.id)
    return conn, ian, repo, proc, integ


def test_sync_creates_work_items_and_dedupes(monkeypatch):
    conn, ian, repo, proc, integ = build(monkeypatch)
    issues = [{"key": "ENG-1", "title": "Fix bug", "url": "u", "state": "Todo"},
              {"key": "ENG-2", "title": "Add feature", "url": "u", "state": "Todo"}]
    monkeypatch.setitem(integrations.ADAPTERS["linear"], "list_issues", lambda c: issues)
    audit = SqliteSink(conn)

    assert sync_tracker(conn, integ.id, repo.id, proc.id, ian.id, audit) == {"created": 2, "skipped": 0}
    items = list_work_items(conn)
    assert len(items) == 2 and all(i.external_ref.startswith("linear:") for i in items)
    assert find_by_external_ref(conn, "linear:ENG-1").title == "Fix bug"
    assert any(e.recipe == "sync" for e in query_events(conn))

    # re-syncing the same issues creates nothing new
    assert sync_tracker(conn, integ.id, repo.id, proc.id, ian.id, audit) == {"created": 0, "skipped": 2}
    assert len(list_work_items(conn)) == 2


def test_sync_rejects_non_tracker(monkeypatch):
    conn, ian, repo, proc, _ = build(monkeypatch)
    monkeypatch.setitem(integrations.ADAPTERS["github"], "verify", lambda c: {"account": "gh"})
    gh = create_integration(conn, "github", {"token": "t"}, ian.id)
    with pytest.raises(ValueError):
        sync_tracker(conn, gh.id, repo.id, proc.id, ian.id, SqliteSink(conn))
