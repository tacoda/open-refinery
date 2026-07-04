import pytest

from open_refinery import (
    AlreadySeeded,
    connect,
    list_processes,
    list_work_items,
    query_events,
    seed,
)


def test_seed_populates_a_minimal_dataset():
    conn = connect("sqlite:///:memory:")
    data = seed(conn)

    assert set(data["users"]) == {"admin", "platform", "developer"}
    assert all(tok for _, tok in data["users"].values())
    assert len(list_processes(conn)) == 1          # minimal: one board process
    assert len(list_work_items(conn)) == 2

    # the moved item recorded a transition
    login = next(w for w in list_work_items(conn) if w.title == "Add login page")
    assert login.current_stage == "in-progress"
    assert any(e.recipe == "transition" for e in query_events(conn, subject=login.id))


def test_seed_refuses_non_empty_db():
    conn = connect("sqlite:///:memory:")
    seed(conn)
    with pytest.raises(AlreadySeeded):
        seed(conn)
