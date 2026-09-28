"""Metrics about the factory, not about a board.

Until 3.0 these aggregated the kanban — work items by the column somebody
dragged them into, and a "lead time" that was the span between a subject's
first and last audit event. What a team asks about is how much shipped, how
much landed, how long it took, and which stage keeps having to be done twice.
"""

from datetime import datetime, timedelta, timezone

from open_refinery import (
    connect,
    create_repository,
    create_user,
    create_work_item,
    delivery,
    stage_health,
    summary,
    wip_by_stage,
)
from open_refinery.pipeline import store as ps


def _at(seconds_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)).isoformat()


def build():
    """Three runs: one landed, one failed, one still going."""
    conn = connect("sqlite:///:memory:")
    ian, _ = create_user(conn, "ian@x.dev", "pw", "developer")
    repo = create_repository(conn, "or", "git@x:or.git", ian.id)
    pipeline = ps.ensure_default(conn, ian.id)

    runs = []
    for title in ("landed", "failed", "running"):
        item = create_work_item(conn, repo.id, title, ian.id)
        runs.append(ps.start_run(conn, item.id, pipeline, repo.id, ian.id, spec=title))
    landed, failed, running = runs

    landed.created_at, landed.updated_at = _at(600), _at(0)
    landed.outcome, landed.stage = "landed", "landed"
    failed.created_at, failed.updated_at = _at(400), _at(200)
    failed.outcome, failed.stage = "failed", "failed"
    for r in (landed, failed):
        conn.add(r)
    conn.commit()

    # the landed run reached a pull request; the failed one never did
    ps.record_step(conn, landed, "publish", outcome="ok", why="",
                   action="open_pull_request", units=40)
    ps.record_step(conn, failed, "run", outcome="refused", why="hook says no", units=100)
    ps.record_step(conn, failed, "run", outcome="error", why="gave up",
                   attempt=2, units=60)
    ps.record_step(conn, running, "plan", outcome="ok", why="", units=10)
    return conn, ian, repo, runs


# --- delivery ---------------------------------------------------------------

def test_delivery_counts_runs_by_outcome():
    conn, _, _, _ = build()
    d = delivery(conn)
    assert d["runs"] == 3 and d["finished"] == 2 and d["in_flight"] == 1
    assert (d["landed"], d["failed"], d["closed"]) == (1, 1, 0)


def test_landed_pct_is_over_finished_runs_only():
    """Counting a run that is still going as a failure to land would make the
    number sag whenever the factory is busy."""
    conn, _, _, _ = build()
    assert delivery(conn)["landed_pct"] == 50      # 1 of 2 finished, not 1 of 3


def test_time_to_a_pull_request_is_measured_to_the_step_that_opened_one():
    conn, _, _, _ = build()
    d = delivery(conn)
    assert d["reached_a_pull_request"] == 1
    assert 590 <= d["avg_seconds_to_pull_request"] <= 610


def test_time_to_an_outcome_is_measured_over_finished_runs():
    conn, _, _, _ = build()
    # landed took 600s, failed took 200s
    assert 395 <= delivery(conn)["avg_seconds_to_outcome"] <= 405


def test_a_held_run_is_counted_as_held():
    conn, _, _, runs = build()
    running = runs[2]
    running.held = True
    conn.add(running); conn.commit()
    assert delivery(conn)["held"] == 1


def test_delivery_scopes_to_the_actor():
    conn, _, repo, _ = build()
    mal, _ = create_user(conn, "mal@x.dev", "pw", "developer")
    assert delivery(conn, owner_id=mal.id)["runs"] == 0
    assert delivery(conn)["runs"] == 3


def test_an_empty_factory_reports_zeroes_rather_than_dividing_by_none():
    conn = connect("sqlite:///:memory:")
    d = delivery(conn)
    assert d["runs"] == 0 and d["landed_pct"] == 0
    assert d["avg_seconds_to_outcome"] == 0.0


# --- stage health -----------------------------------------------------------

def test_stage_health_counts_attempts_outcomes_and_cost():
    conn, _, _, _ = build()
    rows = {r["stage"]: r for r in stage_health(conn)}
    assert rows["run"]["attempts"] == 2
    assert rows["run"]["refused"] == 1 and rows["run"]["error"] == 1
    assert rows["run"]["retries"] == 1                 # the second attempt
    assert rows["run"]["units"] == 160
    assert rows["publish"]["ok"] == 1 and rows["publish"]["trouble_pct"] == 0


def test_the_worst_stage_is_first():
    """It is the row somebody opened this to find."""
    conn, _, _, _ = build()
    assert stage_health(conn)[0]["stage"] == "run"     # 100% trouble
    assert stage_health(conn)[0]["trouble_pct"] == 100


def test_stage_health_is_empty_without_runs():
    assert stage_health(connect("sqlite:///:memory:")) == []


# --- the bundle -------------------------------------------------------------

def test_summary_bundles_what_a_dashboard_needs():
    conn, _, _, _ = build()
    s = summary(conn)
    assert set(s) == {"delivery", "wip_by_stage", "stage_health",
                      "event_counts", "activity_by_actor"}
    assert s["delivery"]["runs"] == 3
    assert s["wip_by_stage"] == {"landed": 1, "failed": 1, "running": 1}


def test_wip_by_stage_still_reads_the_runs():
    conn, ian, repo, _ = build()
    create_work_item(conn, repo.id, "untouched", ian.id)
    assert wip_by_stage(conn)["open"] == 1
