import pytest

from open_refinery import (
    DuplicateRepository,
    connect,
    create_repository,
    create_user,
    get_repository,
    list_repositories,
)


def setup():
    conn = connect("sqlite:///:memory:")
    ian, _ = create_user(conn, "ian@tacoda.dev", "s3cret", "developer")
    return conn, ian


def test_create_and_get():
    conn, ian = setup()
    repo = create_repository(conn, "open-refinery", "git@x:tacoda/or.git", ian.id)
    assert repo.owner_id == ian.id
    assert get_repository(conn, repo.id) == repo


def test_get_missing_returns_none():
    conn, _ = setup()
    assert get_repository(conn, "nope") is None


def test_list_scopes_by_owner():
    conn, ian = setup()
    mal, _ = create_user(conn, "mal@x.dev", "pw", "developer")
    create_repository(conn, "a", "git@x:a.git", ian.id)
    create_repository(conn, "b", "git@x:b.git", mal.id)

    assert len(list_repositories(conn)) == 2  # all (admin view)
    ian_repos = list_repositories(conn, owner_id=ian.id)
    assert len(ian_repos) == 1 and ian_repos[0].name == "a"


def test_duplicate_git_url_rejected():
    conn, ian = setup()
    create_repository(conn, "a", "git@x:a.git", ian.id)
    with pytest.raises(DuplicateRepository):
        create_repository(conn, "dup", "git@x:a.git", ian.id)


def test_unknown_owner_rejected():
    conn, _ = setup()
    with pytest.raises(ValueError):
        create_repository(conn, "a", "git@x:a.git", "ghost")
