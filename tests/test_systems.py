import pytest

from open_refinery import (
    connect,
    create_claim,
    create_repository,
    create_system,
    create_user,
    list_systems,
    set_system_repos,
    system_coverage,
)


def setup():
    conn = connect("sqlite:///:memory:")
    plat, _ = create_user(conn, "plat@x.dev", "pw", "platform")
    web = create_repository(conn, "web", "git@x:web.git", plat.id)
    api = create_repository(conn, "api", "git@x:api.git", plat.id)
    return conn, plat, web, api


def test_create_and_list():
    conn, plat, web, api = setup()
    s = create_system(conn, "Checkout", "microservices", plat.id, repo_ids=[web.id, api.id])
    assert s.kind == "microservices" and s.repo_ids == [web.id, api.id]
    assert len(list_systems(conn)) == 1


def test_unknown_repo_rejected():
    conn, plat, web, api = setup()
    with pytest.raises(ValueError):
        create_system(conn, "X", "service", plat.id, repo_ids=["nope"])


def test_set_repos_dedupes():
    conn, plat, web, api = setup()
    s = create_system(conn, "S", "service", plat.id)
    s = set_system_repos(conn, s.id, [web.id, web.id, api.id])
    assert s.repo_ids == [web.id, api.id]


def test_coverage_rollup():
    conn, plat, web, api = setup()
    # web: fully covered (score 100); api: one imitation surface (score 0)
    create_claim(conn, web.id, "charter", "HIPAA", plat.id, has_instruction=True, has_gate=True)
    create_claim(conn, api.id, "harness", "review before merge", plat.id)  # imitation
    s = create_system(conn, "Checkout", "microservices", plat.id, repo_ids=[web.id, api.id])
    roll = system_coverage(conn, s.id)
    assert roll["members"] == 2 and roll["imitation"] == 1
    assert roll["score"] == 50  # avg of 100 and 0
    assert {r["name"] for r in roll["repos"]} == {"web", "api"}
