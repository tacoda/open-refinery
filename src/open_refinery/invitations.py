"""User invitations — role-gated email invites with an expiring token.

A user invites their **own level or lower** (admin → anyone; platform → platform
or developer; developer → developer). The invite carries an expiring token (default 1 week,
configurable) and the assigned role; the invitee opens the link and **sets their
own password** to register. The link is emailed (email is a swappable port) and
also returned to the inviter so it works even before email is configured.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from sqlmodel import Session, select

from .email import send_email
from .models import Invitation, User, now_iso
from .policies import PolicyDenied
from .users import DuplicateUser, create_session, create_user, role_rank, valid_role

DEFAULT_TTL_DAYS = 7


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_invitation(session: Session, email: str, role: str, invited_by: str,
                      *, ttl_days: int = DEFAULT_TTL_DAYS) -> tuple[Invitation, str]:
    """Create an invite; returns (invitation, plaintext token). Role-gated."""
    if not valid_role(session, role):
        raise ValueError(f"unknown role: {role!r} (not a configured role)")
    inviter = session.get(User, invited_by)
    if inviter is None:
        raise ValueError(f"unknown inviter: {invited_by!r}")
    if role_rank(session, role) > role_rank(session, inviter.role):
        raise PolicyDenied(f"{inviter.role!r} may only invite their level or lower, not {role!r}")

    token = secrets.token_urlsafe(32)
    expires = (datetime.now(timezone.utc) + timedelta(days=ttl_days)).isoformat()
    inv = Invitation(email=email, role=role, token_hash=_hash(token),
                     invited_by=invited_by, expires_at=expires, status="pending")
    session.add(inv)
    session.commit()
    session.refresh(inv)
    return inv, token


def send_invitation_email(email: str, accept_url: str) -> None:
    send_email(email, "You're invited to open-refinery",
               f"You've been invited. Set your password to join:\n\n{accept_url}\n")


def invitation_email(session: Session, token: str) -> str | None:
    """Email for a valid pending invite token (to prefill the accept form)."""
    inv = session.exec(
        select(Invitation).where(Invitation.token_hash == _hash(token))
    ).first()
    if inv is None or inv.status != "pending" or inv.expires_at < now_iso():
        return None
    return inv.email


def accept_invitation(session: Session, token: str, password: str) -> tuple[User, str]:
    """Register the invitee (they set `password`); returns (user, session token)."""
    inv = session.exec(
        select(Invitation).where(Invitation.token_hash == _hash(token))
    ).first()
    if inv is None:
        raise ValueError("invalid invitation")
    if inv.status != "pending":
        raise ValueError(f"invitation already {inv.status}")
    if inv.expires_at < now_iso():
        raise ValueError("invitation expired")

    try:
        user, _ = create_user(session, inv.email, password, inv.role)
    except DuplicateUser:
        raise ValueError("an account for this email already exists") from None
    inv.status = "accepted"
    session.add(inv)
    session.commit()
    return user, create_session(session, user.id)


def list_invitations(session: Session, *, status: str | None = "pending") -> list[Invitation]:
    stmt = select(Invitation)
    if status is not None:
        stmt = stmt.where(Invitation.status == status)
    return list(session.exec(stmt.order_by(Invitation.created_at.desc())))


def revoke_invitation(session: Session, invitation_id: str) -> None:
    inv = session.get(Invitation, invitation_id)
    if inv is not None and inv.status == "pending":
        inv.status = "revoked"
        session.add(inv)
        session.commit()
