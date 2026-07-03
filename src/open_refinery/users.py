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

from .models import User, UserSession

ROLES = ("developer", "senior", "platform", "admin")
# Authority ladder: developer drives work; senior performs escalated ops and
# approves developers' risky moves; platform sets org policy; admin audits all.
ROLE_RANK = {"developer": 1, "senior": 2, "platform": 3, "admin": 4}
MIN_APPROVER_ROLE = "senior"  # approvals of gated moves need senior or higher
_PBKDF2_ROUNDS = 600_000


def role_rank(role: str) -> int:
    return ROLE_RANK.get(role, 0)


def at_least(role: str, minimum: str) -> bool:
    return role_rank(role) >= role_rank(minimum)


class DuplicateUser(Exception):
    """Raised when an email is already registered."""


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
    if role not in ROLES:
        raise ValueError(f"unknown role: {role!r} (expected one of {ROLES})")
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
