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
