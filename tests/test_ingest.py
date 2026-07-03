import pytest

from open_refinery import (
    connect,
    create_policy,
    create_process,
    create_repository,
    create_user,
    ingest,
    list_claims,
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


def test_parse_repo_ssh_and_https():
    assert _parse_repo("git@github.com:acme/app.git") == ("acme", "app")
    assert _parse_repo("https://github.com/acme/app") == ("acme", "app")
    assert _parse_repo("git@gitlab.com:acme/app.git") is None


def test_ingest_creates_claims_per_surface():
    conn, dev, repo = setup()
    res = ingest(conn, repo.id, dev.id, reader=fake_reader)
    assert res["created"] == 4
    claims = list_claims(conn, repo.id)
    assert {c.surface for c in claims} == {"charter", "harness", "code"}


def test_ingest_is_idempotent():
    conn, dev, repo = setup()
    ingest(conn, repo.id, dev.id, reader=fake_reader)
    res2 = ingest(conn, repo.id, dev.id, reader=fake_reader)
    assert res2["created"] == 0 and res2["total_claims"] == 4


def test_backing_heuristic():
    conn, dev, repo = setup()
    # an authored skill echoing "search"; a gated process exists
    create_policy(conn, "allow", dev.id, kind="skill", content="Always use the search tool.")
    create_process(conn, "flow", "board", ["a", "b"], dev.id, gates=["b"])
    ingest(conn, repo.id, dev.id, reader=fake_reader)
    claims = {c.text: c for c in list_claims(conn, repo.id)}
    assert claims["Use the search tool when unsure"].has_instruction is True
    assert claims["All code adheres to HIPAA"].has_instruction is False
    assert all(c.has_gate for c in claims.values())  # org has a gated process


def test_ingest_unknown_repo():
    conn, dev, repo = setup()
    with pytest.raises(ValueError):
        ingest(conn, "nope", dev.id, reader=fake_reader)
