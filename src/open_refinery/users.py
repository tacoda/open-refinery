"""Users, authentication, sessions, and API tokens.

Every actor is a `User` with a role and a personal API token. Passwords are
salted + PBKDF2-hashed; tokens (API and OAuth/password session) are stored
hashed. Stdlib crypto only.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from .models import Role, User, UserSession

# Roles are admin-configurable DATA, not a fixed enum. A fresh store is seeded
# with this minimal ladder; admins add/rank more (senior, lead, …) via the UI.
#   developer — drives work on their repos.
#   platform  — org policy + the governance surface; approves gated moves.
#   admin     — audits everything; manages roles + approval workflows.
DEFAULT_ROLES = (("developer", 1), ("platform", 2), ("admin", 3))
ADMIN_ROLE = "admin"
DEFAULT_MIN_APPROVER_ROLE = "platform"  # default approver tier for a gated move
_PBKDF2_ROUNDS = 600_000


class DuplicateUser(Exception):
    """Raised when an email is already registered."""


class RoleInUse(Exception):
    """Raised when deleting a role still assigned to a user."""


def ensure_default_roles(session: Session) -> None:
    """Seed the default role ladder into an empty roles table (idempotent)."""
    if session.exec(select(Role)).first() is not None:
        return
    for name, rank in DEFAULT_ROLES:
        session.add(Role(name=name, rank=rank))
    session.commit()


def list_roles(session: Session) -> list[Role]:
    return list(session.exec(select(Role).order_by(Role.rank)))


def valid_role(session: Session, name: str) -> bool:
    return session.get(Role, name) is not None


def role_rank(session: Session, name: str) -> int:
    role = session.get(Role, name)
    return role.rank if role else 0


def at_least(session: Session, role: str, minimum: str) -> bool:
    return role_rank(session, role) >= role_rank(session, minimum)


def create_role(session: Session, name: str, rank: int) -> Role:
    """Create (or re-rank) a role — admin only."""
    role = session.get(Role, name)
    if role is None:
        role = Role(name=name, rank=rank)
    else:
        role.rank = rank
    session.add(role)
    session.commit()
    session.refresh(role)
    return role


def delete_role(session: Session, name: str) -> None:
    """Remove a role — admin only. Refuses the admin role or one still in use."""
    if name == ADMIN_ROLE:
        raise ValueError("the admin role cannot be removed")
    if session.exec(select(User.id).where(User.role == name)).first() is not None:
        raise RoleInUse(name)
    role = session.get(Role, name)
    if role is not None:
        session.delete(role)
        session.commit()


def _hash_pw(password: str, salt: bytes | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ROUNDS)
    return salt.hex(), dk.hex()


def _verify_pw(password: str, salt_hex: str, hash_hex: str) -> bool:
    _, dk = _hash_pw(password, bytes.fromhex(salt_hex))
    return hmac.compare_digest(dk, hash_hex)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_user(session: Session, email: str, password: str, role: str) -> tuple[User, str]:
    """Create a user, returning the user and their plaintext token (shown once)."""
    if not valid_role(session, role):
        raise ValueError(f"unknown role: {role!r} (not a configured role)")
    salt_hex, hash_hex = _hash_pw(password)
    token = secrets.token_urlsafe(32)
    user = User(email=email, role=role, pw_salt=salt_hex, pw_hash=hash_hex,
                token_hash=_hash_token(token))
    session.add(user)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise DuplicateUser(email) from exc
    session.refresh(user)
    return user, token


def authenticate(session: Session, email: str, password: str) -> User | None:
    user = session.exec(select(User).where(User.email == email)).first()
    if user is None or not _verify_pw(password, user.pw_salt, user.pw_hash):
        return None
    return user


def user_by_token(session: Session, token: str) -> User | None:
    return session.exec(select(User).where(User.token_hash == _hash_token(token))).first()


def user_by_email(session: Session, email: str) -> User | None:
    return session.exec(select(User).where(User.email == email)).first()


def count_users(session: Session) -> int:
    return len(session.exec(select(User.id)).all())


def list_users(session: Session, *, kind: str = "human") -> list[User]:
    """People by default; pass kind='agent' for harness identities (or None for all)."""
    stmt = select(User)
    if kind is not None:
        stmt = stmt.where(User.kind == kind)
    return list(session.exec(stmt.order_by(User.created_at)))


def rotate_token(session: Session, user_id: str) -> str:
    token = secrets.token_urlsafe(32)
    user = session.get(User, user_id)
    user.token_hash = _hash_token(token)
    session.add(user)
    session.commit()
    return token


def create_session(session: Session, user_id: str) -> str:
    """Issue a session token (after OAuth or password login). Returns plaintext."""
    token = secrets.token_urlsafe(32)
    session.add(UserSession(token_hash=_hash_token(token), user_id=user_id))
    session.commit()
    return token


def session_user(session: Session, token: str) -> User | None:
    row = session.get(UserSession, _hash_token(token))
    return session.get(User, row.user_id) if row else None
