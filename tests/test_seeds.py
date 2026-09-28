import pytest

from open_refinery import (
    AlreadySeeded,
    connect,
    list_work_items,
    seed,
    stages_for,
)


def test_seed_populates_a_minimal_dataset(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "test-secret")  # seed sets the onboarded flag (encrypted)
    conn = connect("sqlite:///:memory:")
    data = seed(conn)

    assert set(data["users"]) == {"admin", "platform", "developer"}
    assert all(tok for _, tok in data["users"].values())
    items = list_work_items(conn)
    assert len(items) == 2
    # a seeded org is pre-configured → onboarding is marked complete
    from open_refinery import get_setting
    assert get_setting(conn, "org.onboarded") == "true"

    # nothing has run yet, so every seeded ticket reads `open`
    assert set(stages_for(conn, items).values()) == {"open"}


def test_seed_refuses_non_empty_db(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    conn = connect("sqlite:///:memory:")
    seed(conn)
    with pytest.raises(AlreadySeeded):
        seed(conn)


def test_seed_leaves_a_runnable_environment(monkeypatch):
    """`POST /setup` seeds `ship-a-ticket` for a real install. A seeded dev box
    needs it too, or starting a run 404s on a pipeline nobody made."""
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    from open_refinery.pipeline import store as ps

    conn = connect("sqlite:///:memory:")
    data = seed(conn)
    assert ps.latest_pipeline(conn, "ship-a-ticket").id == data["pipelines"][0].id

    item = list_work_items(conn)[0]
    run = ps.start_run(conn, item.id, data["pipelines"][0], item.repo_id, item.owner_id)
    assert run.stage == "prepare"
