"""Systems — compose repositories into services / microservice groups / servers.

A `System` is a platform-level grouping of repos. Beyond organizing work, it
gives a **system-level rollup** of the per-repo coverage/health signals, so
platform can see how well an entire service (not just one repo) is governed.
"""

from __future__ import annotations

from sqlmodel import Session, select

from .models import Repository, System, User
from .repo_governance import coverage


def create_system(session: Session, name: str, kind: str, owner_id: str,
                  *, repo_ids: list[str] | None = None) -> System:
    if session.get(User, owner_id) is None:
        raise ValueError(f"unknown owner: {owner_id!r}")
    ids = _validate_repos(session, repo_ids or [])
    system = System(name=name, kind=kind, repo_ids=ids, owner_id=owner_id)
    session.add(system)
    session.commit()
    session.refresh(system)
    return system


def _validate_repos(session: Session, repo_ids: list[str]) -> list[str]:
    out = []
    for rid in repo_ids:
        if session.get(Repository, rid) is None:
            raise ValueError(f"unknown repository: {rid!r}")
        if rid not in out:
            out.append(rid)
    return out


def get_system(session: Session, system_id: str) -> System | None:
    return session.get(System, system_id)


def list_systems(session: Session) -> list[System]:
    return list(session.exec(select(System).order_by(System.created_at.desc())))


def set_system_repos(session: Session, system_id: str, repo_ids: list[str]) -> System:
    system = session.get(System, system_id)
    if system is None:
        raise ValueError(f"unknown system: {system_id!r}")
    system.repo_ids = _validate_repos(session, repo_ids)
    session.add(system)
    session.commit()
    session.refresh(system)
    return system


def delete_system(session: Session, system_id: str) -> None:
    system = session.get(System, system_id)
    if system is not None:
        session.delete(system)
        session.commit()


def system_coverage(session: Session, system_id: str) -> dict:
    """Roll the member repos' coverage up into one system health score."""
    system = session.get(System, system_id)
    if system is None:
        raise ValueError(f"unknown system: {system_id!r}")
    repos, scores, imitation = [], [], 0
    for rid in system.repo_ids:
        repo = session.get(Repository, rid)
        if repo is None:
            continue
        cov = coverage(session, rid)
        repos.append({"repo_id": rid, "name": repo.name, "score": cov["score"],
                      "imitation": cov["imitation"], "total": cov["total"]})
        if cov["total"]:
            scores.append(cov["score"])
        imitation += cov["imitation"]
    return {"system_id": system_id, "name": system.name, "kind": system.kind,
            "members": len(system.repo_ids),
            "score": round(sum(scores) / len(scores)) if scores else 100,
            "imitation": imitation, "repos": repos}
