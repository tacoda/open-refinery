import pytest

from open_refinery import (
    connect,
    create_repository,
    create_user,
    repo_charter,
)
from open_refinery.ingest import _extract, _parse_repo


def setup():
    conn = connect("sqlite:///:memory:")
    dev, _ = create_user(conn, "dev@x.dev", "pw", "developer")
    repo = create_repository(conn, "app", "git@github.com:acme/app.git", dev.id)
    return conn, dev, repo


def fake_reader(_session, _repo):
    return {
        "charter": ["All code adheres to HIPAA", "TDD everywhere"],
        "harness": ["Use the search tool when unsure"],
        "code": ["Has a tests directory"],
    }


def test_extract_headings_and_bullets():
    md = "# Title\n\n- first rule\n* second rule\nplain line ignored\n## Section head"
    got = _extract(md)
    assert got == ["Title", "first rule", "second rule", "Section head"]


def test_parse_repo_github_and_gitlab():
    assert _parse_repo("git@github.com:acme/app.git") == ("acme", "app")
    assert _parse_repo("https://github.com/acme/app") == ("acme", "app")
    assert _parse_repo("git@gitlab.com:acme/app.git") == ("acme", "app")
    assert _parse_repo("git@bitbucket.org:acme/app.git") is None


def test_integration_resolution_prefers_explicit_link(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    from open_refinery import create_integration, link_integration
    from open_refinery.ingest import _integration_for
    from open_refinery.models import Repository
    import open_refinery.integrations as integrations
    monkeypatch.setitem(integrations.ADAPTERS["github"], "verify", lambda cred: {"account": "acme"})

    conn = connect("sqlite:///:memory:")
    dev, _ = create_user(conn, "dev@x.dev", "pw", "developer")
    repo = create_repository(conn, "app", "git@github.com:acme/app.git", dev.id)
    create_integration(conn, "github", {"token": "t1"}, dev.id)
    i2 = create_integration(conn, "github", {"token": "t2"}, dev.id)

    assert _integration_for(conn, repo).kind == "github"   # falls back by host
    link_integration(conn, repo.id, i2.id)
    assert _integration_for(conn, conn.get(Repository, repo.id)).id == i2.id  # explicit link wins


def test_charter_returns_the_three_surfaces():
    conn, dev, repo = setup()
    got = repo_charter(conn, repo.id, reader=fake_reader)

    assert got["charter"] == ["All code adheres to HIPAA", "TDD everywhere"]
    assert got["harness"] == ["Use the search tool when unsure"]
    assert got["code"] == ["Has a tests directory"]


def test_charter_of_an_unknown_repo_raises():
    conn, _, _ = setup()
    with pytest.raises(ValueError):
        repo_charter(conn, "nope", reader=fake_reader)


def test_a_reader_that_finds_nothing_is_not_an_error():
    """The live path is best-effort — a repo with no agent config is normal."""
    conn, dev, repo = setup()
    got = repo_charter(conn, repo.id, reader=lambda s, r: {})
    assert got == {"repo_id": repo.id, "charter": [], "harness": [], "code": []}


# --- where the charter lives ------------------------------------------------

def test_the_default_is_agents_only():
    """`.agents/` and `AGENTS.md`, and nothing else. Tool-neutral, because the
    charter belongs to the repository rather than to whichever agent reads it."""
    from open_refinery.ingest import charter_paths

    class Repo:
        charter_paths = []
    assert charter_paths(Repo()) == ((".agents",), ("AGENTS.md",))


def test_an_override_replaces_the_default_rather_than_adding_to_it():
    """A team that says where their charter lives means there, not there plus
    a guess — otherwise a stale CLAUDE.md keeps being read forever."""
    from open_refinery.ingest import charter_paths

    class Repo:
        charter_paths = ["docs/agent", "RULES.md"]
    dirs, files = charter_paths(Repo())
    assert dirs == ("docs/agent",) and files == ("RULES.md",)
    assert ".agents" not in dirs and "AGENTS.md" not in files


def test_extensions_decide_directory_versus_file():
    from open_refinery.ingest import charter_paths

    class Repo:
        charter_paths = [".cursor/rules", ".cursorrules"]
    dirs, files = charter_paths(Repo())
    assert dirs == (".cursor/rules",) and files == (".cursorrules",)


@pytest.mark.parametrize("agent", ["claude", "cursor", "copilot", "windsurf", "aider"])
def test_any_agent_can_be_configured_from_a_preset(agent):
    """Overriding is a pick, not research."""
    from open_refinery.ingest import charter_paths, preset

    class Repo:
        charter_paths = list(preset(agent))
    dirs, files = charter_paths(Repo())
    assert dirs or files


def test_an_unknown_preset_is_empty_not_an_error():
    from open_refinery.ingest import preset
    assert preset("not-an-agent") == ()


def test_surfaces_are_read_from_the_configured_paths():
    """The override has to reach the reader, or it is a setting that does
    nothing."""
    from open_refinery.ingest import _surfaces_from

    files = {"docs/agent/style.md": "# House style", "RULES.md": "- be careful"}

    def list_dir(path):
        return [k.split("/")[-1] for k in files if k.startswith(f"{path}/")]

    def read_text(path):
        return files[path]

    class Repo:
        charter_paths = ["docs/agent", "RULES.md"]

    got = _surfaces_from(list_dir, read_text, Repo())
    assert got["charter"] == ["House style"]
    assert got["harness"] == ["be careful"]
