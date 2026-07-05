import pytest

from open_refinery import (
    PolicyDenied,
    SqliteSink,
    connect,
    create_policy,
    create_process,
    create_repository,
    create_user,
    create_work_item,
    get_work_item,
    rollback_targets,
    rollback_work_item,
    stage_history,
    transition,
)
from open_refinery.settings import set_setting


def setup(monkeypatch=None):
    if monkeypatch:
        monkeypatch.setenv("SECRET_KEY", "test-secret")
    conn = connect("sqlite:///:memory:")
    dev, _ = create_user(conn, "dev@x.dev", "pw", "developer")
    repo = create_repository(conn, "app", "git@x:app.git", dev.id)
    proc = create_process(conn, "flow", "board", ["backlog", "doing", "review", "done"], dev.id)
    item = create_work_item(conn, repo.id, proc.id, "T", dev.id)
    return conn, dev, item


def test_history_records_initial_and_transitions():
    conn, dev, item = setup()
    audit = SqliteSink(conn)
    transition(conn, item.id, "doing", dev.id, audit)
    transition(conn, item.id, "review", dev.id, audit)
    stages = [h.stage for h in stage_history(conn, item.id)]
    assert stages == ["backlog", "doing", "review"]
    assert set(rollback_targets(conn, item.id)) == {"backlog", "doing"}  # not current 'review'


def test_rollback_reverts_to_prior_stage_and_audits():
    conn, dev, item = setup()
    audit = SqliteSink(conn)
    transition(conn, item.id, "doing", dev.id, audit)
    transition(conn, item.id, "review", dev.id, audit)

    result = rollback_work_item(conn, item.id, "backlog", dev.id, audit)
    assert result["item"].current_stage == "backlog"
    assert get_work_item(conn, item.id).current_stage == "backlog"
    # rollback recorded in history + audit trail
    hist = stage_history(conn, item.id)
    assert hist[-1].stage == "backlog" and hist[-1].kind == "rollback"
    from open_refinery import query_events
    assert any(e.recipe == "rollback" for e in query_events(conn, subject=item.id))


def test_reverse_plan_undoes_code_migrations_config_and_libraries():
    conn, dev, item = setup()
    audit = SqliteSink(conn)
    transition(conn, item.id, "doing", dev.id, audit, changes={
        "code": {"commit": "c2", "prev": "c1"},
        "migrations": ["003_add_orders"],
        "config": {"FEATURE_X": {"old": "off", "new": "on"}},
        "env": {"LOG_LEVEL": {"old": "info", "new": "debug"}},
        "libraries": {"requests": {"old": "2.30", "new": "2.31"}},
        "data": {"orders": {"old": "snap-1", "new": "snap-2"}},
        "services": {"payments": {"old": "stripe", "new": "adyen"}},
        "secrets": {"db_password": {"old": "v7", "new": "v8"}},  # version refs, not material
        "infra": {"web_asg": {"old": "tf-42", "new": "tf-43"}},
        "dns": {"api.example.com": {"old": "10.0.0.1", "new": "10.0.0.2"}},
        "queues": {"orders": {"old": "q-v1", "new": "q-v2"}},    # unlisted → reverses generically
    })
    transition(conn, item.id, "review", dev.id, audit, changes={
        "code": {"commit": "c3", "prev": "c2"},
        "migrations": ["004_index_orders"],
        "config": {"FEATURE_X": {"old": "on", "new": "audit"}},
        "data": {"orders": {"old": "snap-2", "new": "snap-3"}},
    })

    plan = rollback_work_item(conn, item.id, "backlog", dev.id, audit)["plan"]
    assert plan["code"] == {"revert_to": "c1"}                 # earliest prev
    # newest migration downgraded first
    assert plan["migrations"] == [{"downgrade": "004_index_orders"},
                                  {"downgrade": "003_add_orders"}]
    assert plan["config"] == {"FEATURE_X": "off"}              # first-seen old
    assert plan["env"] == {"LOG_LEVEL": "info"}                # restore prior env var
    assert plan["libraries"] == {"requests": "2.30"}
    assert plan["data"] == {"orders": "snap-1"}                # restore pre-update snapshot
    assert plan["services"] == {"payments": "stripe"}          # restore prior vendor
    assert plan["secrets"] == {"db_password": "v7"}            # restore prior credential ref
    assert plan["infra"] == {"web_asg": "tf-42"}               # restore prior infra state
    assert plan["dns"] == {"api.example.com": "10.0.0.1"}      # restore prior record
    assert plan["queues"] == {"orders": "q-v1"}                # open category, no code change needed


def test_cannot_rollback_to_unvisited_or_current_stage():
    conn, dev, item = setup()
    audit = SqliteSink(conn)
    transition(conn, item.id, "doing", dev.id, audit)
    with pytest.raises(ValueError):
        rollback_work_item(conn, item.id, "done", dev.id, audit)     # never visited
    with pytest.raises(ValueError):
        rollback_work_item(conn, item.id, "doing", dev.id, audit)    # current stage


def test_rollback_is_policy_gated(monkeypatch):
    conn, dev, item = setup(monkeypatch)
    audit = SqliteSink(conn)
    transition(conn, item.id, "doing", dev.id, audit)
    create_policy(conn, "deny", dev.id, role="developer", action="rollback", resource="*")
    with pytest.raises(PolicyDenied):
        rollback_work_item(conn, item.id, "backlog", dev.id, audit)
