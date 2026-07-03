"""Repositories — the atomic unit the factory operates on.

A `Repository` is one git repo (a "project"), owned by a user. Ownership is the
column the query layer scopes on: developers see their own repos, admins see
all.
"""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from .store import register_schema

register_schema(
    """
    CREATE TABLE IF NOT EXISTS repositories (
        id         TEXT PRIMARY KEY,
        name       TEXT NOT NULL,
        git_url    TEXT NOT NULL UNIQUE,
        owner_id   TEXT NOT NULL REFERENCES users(id),
        created_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS ix_repositories_owner ON repositories(owner_id);
    """
)


class DuplicateRepository(Exception):
    """Raised when a git URL is already registered."""


@dataclass(frozen=True)
class Repository:
    id: str
    name: str
    git_url: str
    owner_id: str
    created_at: str


def _row_to_repo(row: sqlite3.Row) -> Repository:
    return Repository(
        id=row["id"],
        name=row["name"],
        git_url=row["git_url"],
        owner_id=row["owner_id"],
        created_at=row["created_at"],
    )


def create_repository(
    conn: sqlite3.Connection, name: str, git_url: str, owner_id: str
) -> Repository:
    if conn.execute("SELECT 1 FROM users WHERE id = ?", (owner_id,)).fetchone() is None:
        raise ValueError(f"unknown owner: {owner_id!r}")

    repo = Repository(
        id=uuid.uuid4().hex,
        name=name,
        git_url=git_url,
        owner_id=owner_id,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    try:
        conn.execute(
            "INSERT INTO repositories (id, name, git_url, owner_id, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (repo.id, repo.name, repo.git_url, repo.owner_id, repo.created_at),
        )
        conn.commit()
    except sqlite3.IntegrityError as exc:
        raise DuplicateRepository(git_url) from exc
    return repo


def import_or_get(
    conn: sqlite3.Connection, name: str, git_url: str, owner_id: str
) -> Repository:
    """Idempotent import: return the existing repo for this git URL, else create it."""
    row = conn.execute("SELECT * FROM repositories WHERE git_url = ?", (git_url,)).fetchone()
    return _row_to_repo(row) if row else create_repository(conn, name, git_url, owner_id)


def get_repository(conn: sqlite3.Connection, repo_id: str) -> Repository | None:
    row = conn.execute("SELECT * FROM repositories WHERE id = ?", (repo_id,)).fetchone()
    return _row_to_repo(row) if row else None


def list_repositories(
    conn: sqlite3.Connection, *, owner_id: str | None = None
) -> list[Repository]:
    """List repos, newest first. Pass owner_id to scope; omit for all (admin)."""
    if owner_id is None:
        rows = conn.execute("SELECT * FROM repositories ORDER BY created_at DESC")
    else:
        rows = conn.execute(
            "SELECT * FROM repositories WHERE owner_id = ? ORDER BY created_at DESC",
            (owner_id,),
        )
    return [_row_to_repo(row) for row in rows]
