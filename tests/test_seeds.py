import pytest

from open_refinery import (
    AlreadySeeded,
    connect,
    list_processes,
    list_work_items,
    query_events,
    seed,
)


def test_seed_populates_a_usable_dataset():
    conn = connect("sqlite:///:memory:")
    data = seed(conn)

    assert set(data["users"]) == {"admin", "platform", "senior", "developer"}
    assert all(tok for _, tok in data["users"].values())
    assert len(list_processes(conn)) == 2
    assert len(list_work_items(conn)) == 3

    # the closed CVE item has transitions, approvals, and attestations recorded
    cve = next(w for w in list_work_items(conn) if w.title.startswith("CVE"))
    recipes = {e.recipe for e in query_events(conn, subject=cve.id)}
    assert {"transition", "approval", "attestation"} <= recipes
    assert cve.current_stage == "close"


def test_seed_refuses_non_empty_db():
    conn = connect("sqlite:///:memory:")
    seed(conn)
    with pytest.raises(AlreadySeeded):
        seed(conn)
