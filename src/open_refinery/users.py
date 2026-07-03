"""Users, authentication, and API tokens.

Accountability starts here: every actor is a `User` with a role and a personal
API token. Passwords are salted + PBKDF2-hashed; tokens are stored hashed and
shown once. Stdlib crypto only — no external dependency.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from .store import register_schema

ROLES = ("developer", "platform", "admin")
_PBKDF2_ROUNDS = 600_000

register_schema(
    """
    CREATE TABLE IF NOT EXISTS users (
        id         TEXT PRIMARY KEY,
        email      TEXT NOT NULL UNIQUE,
        role       TEXT NOT NULL,
        pw_salt    TEXT NOT NULL,
        pw_hash    TEXT NOT NULL,
        token_hash TEXT NOT NULL UNIQUE,
        created_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS ix_users_token ON users(token_hash);
    """
)

register_schema(
    """
    CREATE TABLE IF NOT EXISTS sessions (
        token_hash TEXT PRIMARY KEY,
        user_id    TEXT NOT NULL REFERENCES users(id),
        created_at TEXT NOT NULL
    );
    """
)


class DuplicateUser(Exception):
    """Raised when an email is already registered."""


@dataclass(frozen=True)
class User:
    """A principal. Secrets (password/token hashes) stay in the store."""

    id: str
    email: str
    role: str
    created_at: str


def _hash_pw(password: str, salt: bytes | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ROUNDS)
    return salt.hex(), dk.hex()


def _verify_pw(password: str, salt_hex: str, hash_hex: str) -> bool:
    _, dk = _hash_pw(password, bytes.fromhex(salt_hex))
    return hmac.compare_digest(dk, hash_hex)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _row_to_user(row: sqlite3.Row) -> User:
    return User(id=row["id"], email=row["email"], role=row["role"], created_at=row["created_at"])


def create_user(
    conn: sqlite3.Connection, email: str, password: str, role: str
) -> tuple[User, str]:
    """Create a user, returning the user and their **plaintext token (shown once)**."""
    if role not in ROLES:
        raise ValueError(f"unknown role: {role!r} (expected one of {ROLES})")

    salt_hex, hash_hex = _hash_pw(password)
    token = secrets.token_urlsafe(32)
    user = User(
        id=uuid.uuid4().hex,
        email=email,
        role=role,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    try:
        conn.execute(
            "INSERT INTO users (id, email, role, pw_salt, pw_hash, token_hash, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user.id, email, role, salt_hex, hash_hex, _hash_token(token), user.created_at),
        )
        conn.commit()
    except sqlite3.IntegrityError as exc:
        raise DuplicateUser(email) from exc
    return user, token


def authenticate(conn: sqlite3.Connection, email: str, password: str) -> User | None:
    """Return the user if email + password match, else None."""
    row = conn.execute(
        "SELECT * FROM users WHERE email = ?", (email,)
    ).fetchone()
    if row is None or not _verify_pw(password, row["pw_salt"], row["pw_hash"]):
        return None
    return _row_to_user(row)


def user_by_token(conn: sqlite3.Connection, token: str) -> User | None:
    """Resolve a bearer token to its user, else None."""
    row = conn.execute(
        "SELECT * FROM users WHERE token_hash = ?", (_hash_token(token),)
    ).fetchone()
    return _row_to_user(row) if row else None


def user_by_email(conn: sqlite3.Connection, email: str) -> User | None:
    row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    return _row_to_user(row) if row else None


def count_users(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) n FROM users").fetchone()["n"]


def create_session(conn: sqlite3.Connection, user_id: str) -> str:
    """Issue a session token (e.g. after OAuth login). Returns the plaintext token."""
    token = secrets.token_urlsafe(32)
    conn.execute(
        "INSERT INTO sessions (token_hash, user_id, created_at) VALUES (?, ?, ?)",
        (_hash_token(token), user_id, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    return token


def session_user(conn: sqlite3.Connection, token: str) -> User | None:
    """Resolve a session token to its user, else None."""
    row = conn.execute(
        "SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id "
        "WHERE s.token_hash = ?",
        (_hash_token(token),),
    ).fetchone()
    return _row_to_user(row) if row else None


def rotate_token(conn: sqlite3.Connection, user_id: str) -> str:
    """Issue a fresh token for a user, invalidating the old one. Returns plaintext."""
    token = secrets.token_urlsafe(32)
    conn.execute(
        "UPDATE users SET token_hash = ? WHERE id = ?", (_hash_token(token), user_id)
    )
    conn.commit()
    return token
