import pathlib
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

    assert set(data["users"]) == {"owner", "admin", "platform", "developer"}
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


def test_the_owner_account_holds_every_permission(monkeypatch):
    """A preset cannot stand in for it: no single one reaches every screen,
    which is the point of an account you dogfood the whole product with."""
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    from open_refinery.authority import PERMISSIONS
    from open_refinery.seeds import DEFAULT_OWNER

    conn = connect("sqlite:///:memory:")
    owner, _ = seed(conn)["users"]["owner"]
    assert owner.email == DEFAULT_OWNER
    assert set(owner.permissions) == set(PERMISSIONS)


def test_the_owner_email_is_yours_to_choose(monkeypatch):
    """The default is deliberately generic: a real address here would ship in
    the package and turn up in every contributor's dev database."""
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    conn = connect("sqlite:///:memory:")
    owner, _ = seed(conn, owner_email="me@example.org")["users"]["owner"]
    assert owner.email == "me@example.org"


def test_the_seeded_repository_is_one_a_run_can_actually_use(tmp_path, monkeypatch):
    """`workspace.root_of` refuses a git_url that is not a local checkout, so a
    seeded repo without one makes the first thing a new arrival does — name a
    ticket and ship it — fail on a worktree that cannot be made."""
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    from open_refinery.pipeline.workspace import root_of
    from open_refinery.seeds import make_checkout

    url = make_checkout(tmp_path / "devrepo")
    conn = connect("sqlite:///:memory:")
    repo = seed(conn, git_url=url)["repositories"][0]

    assert root_of(repo.git_url).exists()          # would raise WorkspaceError
    assert repo.forge == ""                        # "" resolves to `local` by URL

    from open_refinery.pipeline.forge import for_repo
    assert for_repo(repo.git_url, repo.forge).name == "local"


def test_making_a_checkout_twice_leaves_the_first_alone(tmp_path):
    from open_refinery.seeds import make_checkout

    first = make_checkout(tmp_path / "devrepo")
    (pathlib.Path(first) / "app.py").write_text("# edited\n")
    again = make_checkout(tmp_path / "devrepo")
    assert again == first
    assert (pathlib.Path(first) / "app.py").read_text() == "# edited\n"
