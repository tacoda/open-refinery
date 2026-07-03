import pytest

from open_refinery import (
    connect,
    create_claim,
    create_repository,
    create_user,
    repo_report,
)


def setup():
    conn = connect("sqlite:///:memory:")
    dev, _ = create_user(conn, "dev@x.dev", "pw", "developer")
    repo = create_repository(conn, "app", "git@x:app.git", dev.id)
    return conn, dev, repo


def test_coverage_classifies_and_scores():
    conn, dev, repo = setup()
    create_claim(conn, repo.id, "charter", "All code adheres to HIPAA", dev.id,
                 has_instruction=True, has_gate=True)      # covered
    create_claim(conn, repo.id, "charter", "TDD everywhere", dev.id,
                 has_instruction=True, has_gate=False)     # partial
    create_claim(conn, repo.id, "harness", "Security review before merge", dev.id)  # imitation

    cov = repo_report(conn, repo.id)["coverage"]
    assert cov["total"] == 3 and cov["covered"] == 1 and cov["partial"] == 1 and cov["imitation"] == 1
    assert cov["score"] == 33
    assert len(cov["imitation_surfaces"]) == 1
    assert cov["imitation_surfaces"][0]["text"] == "Security review before merge"


def test_drift_across_axes():
    conn, dev, repo = setup()
    create_claim(conn, repo.id, "charter", "TDD everywhere", dev.id)
    create_claim(conn, repo.id, "harness", "TDD everywhere", dev.id)   # shared → no drift
    create_claim(conn, repo.id, "charter", "Sign all commits", dev.id)  # charter-only

    drift = repo_report(conn, repo.id)["drift"]
    ch = next(d for d in drift if d["axis"] == "charter↔harness")
    assert "Sign all commits" in ch["only_in"]["charter"]
    assert ch["only_in"]["harness"] == []


def test_empty_repo_scores_100():
    conn, dev, repo = setup()
    assert repo_report(conn, repo.id)["coverage"]["score"] == 100


def test_unknown_repo():
    conn, dev, repo = setup()
    with pytest.raises(ValueError):
        repo_report(conn, "nope")
