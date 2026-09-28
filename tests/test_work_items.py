"""A work item is a ticket, not a state machine.

Until 3.0 it sat on a `Process` — a second stage graph with transitions, gates
and checks that a run completely ignored. Its stage is now *derived* from its
runs, so these tests are about what the factory did, not where a card was put.
"""

import pytest

from open_refinery import (
    connect,
    create_repository,
    create_user,
    create_work_item,
    get_work_item,
    list_work_items,
    stage_of,
    stages_for,
)
from open_refinery.pipeline import store as ps


def setup():
    conn = connect("sqlite:///:memory:")
    ian, _ = create_user(conn, "ian@tacoda.dev", "s3cret", "developer")
    repo = create_repository(conn, "or", "git@x:or.git", ian.id)
    return conn, ian, repo


def _run(conn, repo, item, actor):
    pipeline = ps.ensure_default(conn, actor.id)
    return ps.start_run(conn, item.id, pipeline, repo.id, actor.id, spec="do it")


def test_a_new_item_needs_no_process_and_is_open():
    conn, ian, repo = setup()
    item = create_work_item(conn, repo.id, "CVE-123", ian.id)
    assert get_work_item(conn, item.id) == item
    assert stage_of(conn, item.id) == "open"


def test_stage_follows_the_run():
    conn, ian, repo = setup()
    item = create_work_item(conn, repo.id, "CVE-123", ian.id)
    run = _run(conn, repo, item, ian)
    assert stage_of(conn, item.id) == "running"

    run.stage = "waiting"                      # the PR is open, waiting on a human
    conn.add(run); conn.commit()
    assert stage_of(conn, item.id) == "waiting"


def test_an_outcome_is_the_last_word():
    conn, ian, repo = setup()
    item = create_work_item(conn, repo.id, "CVE-123", ian.id)
    run = _run(conn, repo, item, ian)
    run.stage = "waiting"
    run.outcome = "landed"
    conn.add(run); conn.commit()
    assert stage_of(conn, item.id) == "landed"


def test_the_newest_run_wins():
    """A reworked ticket gets a second run; the board shows the latest one."""
    conn, ian, repo = setup()
    item = create_work_item(conn, repo.id, "CVE-123", ian.id)
    first = _run(conn, repo, item, ian)
    first.outcome = "closed"
    conn.add(first); conn.commit()
    assert stage_of(conn, item.id) == "closed"

    _run(conn, repo, item, ian)                # somebody tries again
    assert stage_of(conn, item.id) == "running"


def test_stages_for_matches_stage_of_in_one_query():
    conn, ian, repo = setup()
    a = create_work_item(conn, repo.id, "a", ian.id)
    b = create_work_item(conn, repo.id, "b", ian.id)
    _run(conn, repo, b, ian)
    items = list_work_items(conn)
    assert stages_for(conn, items) == {a.id: "open", b.id: "running"}
    assert stages_for(conn, []) == {}


def test_unknown_repository_and_owner_are_refused():
    conn, ian, repo = setup()
    with pytest.raises(ValueError):
        create_work_item(conn, "ghost-repo", "T", ian.id)
    with pytest.raises(ValueError):
        create_work_item(conn, repo.id, "T", "ghost-actor")


def test_an_item_with_no_runs_reads_open():
    """Including one that does not exist — the board asks about ids it has."""
    conn, _, _ = setup()
    assert stage_of(conn, "ghost") == "open"


def test_list_scoping():
    conn, ian, repo = setup()
    mal, _ = create_user(conn, "mal@x.dev", "pw", "developer")
    create_work_item(conn, repo.id, "a", ian.id)
    create_work_item(conn, repo.id, "b", mal.id)
    assert len(list_work_items(conn)) == 2
    assert len(list_work_items(conn, owner_id=ian.id)) == 1
    assert len(list_work_items(conn, repo_id=repo.id)) == 2
