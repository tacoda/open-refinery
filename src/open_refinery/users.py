"""Users, authentication, sessions, and API tokens.

Every actor is a `User` with a role and a personal API token. Passwords are
salted + PBKDF2-hashed; tokens (API and session) are stored hashed. Stdlib
crypto only. What a role may *do* lives in `authority.py`.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from .models import Role, User, UserSession

# Roles are DATA, and what a role may do lives on its row — see `authority.py`
# for the standard configuration and why it is not a ladder. This module owns
# the table; `authority` owns the meaning.
ADMIN_ROLE = "admin"
# The default approver for a gated move: a work-item transition is `code`, and
# `lead` is the weakest role above the author that can sign one off.
DEFAULT_MIN_APPROVER_ROLE = "lead"
_PBKDF2_ROUNDS = 600_000


class DuplicateUser(Exception):
    """Raised when an email is already registered."""


class RoleInUse(Exception):
    """Raised when deleting a role still assigned to a user."""


def ensure_default_roles(session: Session) -> None:
    """Seed the shipped **presets** (idempotent).

    A preset is a named bundle of permissions you apply when adding someone —
    nothing authorizes against it. Reconciled on every call rather than only
    when the table is empty, because an install upgrading from an older version
    has rows with no permissions on them.

    Custom presets are never touched.
    """
    from .authority import PRESETS, RANKS

    for name, perms in PRESETS.items():
        row = session.get(Role, name) or Role(name=name)
        row.rank = RANKS.get(name, 1)
        row.permissions = list(perms)
        row.builtin = True
        session.add(row)
    session.commit()


# The presets are what a team starts from; `ensure_presets` is the name that
# says so. The old name stays because `store._init_schema` calls it.
ensure_presets = ensure_default_roles


def list_roles(session: Session) -> list[Role]:
    return list(session.exec(select(Role).order_by(Role.rank)))


def valid_role(session: Session, name: str) -> bool:
    return session.get(Role, name) is not None


def role_rank(session: Session, name: str) -> int:
    role = session.get(Role, name)
    return role.rank if role else 0


def at_least(session: Session, role: str, minimum: str) -> bool:
    """Rank comparison, for genuine orderings such as walking an approval chain.

    **Not an authority check** — use `authority.may_approve` for that.

    Fails closed on an unknown role. It used to not: `role_rank()` returns 0 for
    a role that does not exist, so `at_least(developer, "senior")` was True, and
    every process left on migration v2's `'senior'` default had no effective
    approval minimum at all.
    """
    if not valid_role(session, role) or not valid_role(session, minimum):
        return False
    return role_rank(session, role) >= role_rank(session, minimum)


def create_role(session: Session, name: str, rank: int, *,
                permissions: list[str] | None = None) -> Role:
    """Create or update a **preset** — a named bundle to start people from.

    An unknown permission is dropped rather than stored: one nothing checks is
    one somebody believes they have.
    """
    from .authority import clean

    role = session.get(Role, name) or Role(name=name, permissions=[])
    role.rank = rank
    if permissions is not None:
        role.permissions = clean(permissions)
    session.add(role)
    session.commit()
    session.refresh(role)
    return role


def set_permissions(session: Session, user_id: str, permissions: list[str]) -> User:
    """Replace a user's permissions. The set is what is checked from here on."""
    from .authority import clean

    user = session.get(User, user_id)
    if user is None:
        raise ValueError(f"unknown user: {user_id!r}")
    user.permissions = clean(permissions)
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def delete_role(session: Session, name: str) -> None:
    """Remove a role — admin only. Refuses a built-in or one still in use."""
    row = session.get(Role, name)
    if row is not None and row.builtin:
        raise ValueError(f"{name!r} is a built-in role and cannot be removed")
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


def create_user(session: Session, email: str, password: str, role: str,
                *, permissions: list[str] | None = None) -> tuple[User, str]:
    """Create a user, returning the user and their plaintext token (shown once).

    `role` names the **preset** to start from and is kept only as a label;
    `permissions` overrides it outright. What the user ends up holding is what
    is checked from then on — editing the preset later changes nobody.
    """
    from .authority import clean, of_preset

    if permissions is None:
        if not valid_role(session, role):
            raise ValueError(f"unknown preset: {role!r}")
        row = session.get(Role, role)
        permissions = list(row.permissions or of_preset(role))
    held = clean(permissions)

    salt_hex, hash_hex = _hash_pw(password)
    token = secrets.token_urlsafe(32)
    user = User(email=email, role=role, permissions=held,
                pw_salt=salt_hex, pw_hash=hash_hex,
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
    if user is None:
        return None
    if not user.active:
        return None
    if not _verify_pw(password, user.pw_salt, user.pw_hash):
        return None
    return user


def user_by_token(session: Session, token: str) -> User | None:
    user = session.exec(select(User).where(User.token_hash == _hash_token(token))).first()
    return user if user and user.active else None


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
    """Issue a session token after a password login. Returns plaintext."""
    token = secrets.token_urlsafe(32)
    session.add(UserSession(token_hash=_hash_token(token), user_id=user_id))
    session.commit()
    return token


def session_user(session: Session, token: str) -> User | None:
    row = session.get(UserSession, _hash_token(token))
    if row is None:
        return None
    user = session.get(User, row.user_id)
    return user if user and user.active else None


def set_active(session: Session, user_id: str, active: bool) -> User | None:
    """Activate/deactivate a user (SCIM deprovisioning). Returns the user."""
    user = session.get(User, user_id)
    if user is None:
        return None
    user.active = active
    session.add(user)
    session.commit()
    session.refresh(user)
    return user
