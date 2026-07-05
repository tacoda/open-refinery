"""Repositories — the atomic unit the factory operates on (one git repo)."""

from __future__ import annotations

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from .models import Repository, User


class DuplicateRepository(Exception):
    """Raised when a git URL is already registered."""


def create_repository(session: Session, name: str, git_url: str, owner_id: str) -> Repository:
    if session.get(User, owner_id) is None:
        raise ValueError(f"unknown owner: {owner_id!r}")
    repo = Repository(name=name, git_url=git_url, owner_id=owner_id)
    session.add(repo)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise DuplicateRepository(git_url) from exc
    session.refresh(repo)
    return repo


def import_or_get(session: Session, name: str, git_url: str, owner_id: str) -> Repository:
    """Idempotent import: return the existing repo for this git URL, else create it."""
    existing = session.exec(select(Repository).where(Repository.git_url == git_url)).first()
    return existing or create_repository(session, name, git_url, owner_id)


def get_repository(session: Session, repo_id: str) -> Repository | None:
    return session.get(Repository, repo_id)


def list_repositories(session: Session, *, owner_id: str | None = None) -> list[Repository]:
    stmt = select(Repository)
    if owner_id is not None:
        stmt = stmt.where(Repository.owner_id == owner_id)
    return list(session.exec(stmt.order_by(Repository.created_at.desc())))


def link_integration(session: Session, repo_id: str, integration_id: str | None) -> Repository:
    """Set the source integration a repo ingests from (None = fall back by host)."""
    repo = session.get(Repository, repo_id)
    if repo is None:
        raise ValueError(f"unknown repository: {repo_id!r}")
    repo.integration_id = integration_id
    session.add(repo)
    session.commit()
    session.refresh(repo)
    return repo


def set_ingest_schedule(session: Session, repo_id: str, interval_hours: int) -> Repository:
    """Set the auto-ingest cadence in hours (0 = manual only)."""
    repo = session.get(Repository, repo_id)
    if repo is None:
        raise ValueError(f"unknown repository: {repo_id!r}")
    repo.ingest_interval_hours = max(0, int(interval_hours))
    session.add(repo)
    session.commit()
    session.refresh(repo)
    return repo
