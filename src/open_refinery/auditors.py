"""Time-boxed auditor access — a read-only external principal.

An admin mints an auditor grant (a token + expiry). Used as a bearer token it
resolves to a read-only `auditor` principal: it can read evidence packs and the
audit trail, and mutate nothing (the authorization matrix lists only
developer/platform/admin for writes). It expires on its own.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from sqlmodel import Session, select

from .models import AuditorGrant, User, now_iso


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def mint_auditor(session: Session, label: str, created_by: str, *,
                 ttl_days: int = 14) -> tuple[AuditorGrant, str]:
    if session.get(User, created_by) is None:
        raise ValueError(f"unknown creator: {created_by!r}")
    token = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(days=ttl_days)
    grant = AuditorGrant(token_hash=_hash(token), label=label,
                         expires_at=expires.isoformat(), created_by=created_by)
    session.add(grant)
    session.commit()
    session.refresh(grant)
    return grant, token


def resolve_auditor(session: Session, token: str) -> AuditorGrant | None:
    """Return the grant iff the token matches and hasn't expired."""
    grant = session.exec(select(AuditorGrant).where(AuditorGrant.token_hash == _hash(token))).first()
    if grant is None or grant.expires_at < now_iso():
        return None
    return grant


def list_auditors(session: Session) -> list[AuditorGrant]:
    return list(session.exec(select(AuditorGrant).order_by(AuditorGrant.created_at.desc())))


def auditor_view(g: AuditorGrant) -> dict:
    expired = g.expires_at < now_iso()
    return {"id": g.id, "label": g.label, "expires_at": g.expires_at,
            "expired": expired, "created_at": g.created_at}


def revoke_auditor(session: Session, grant_id: str) -> None:
    g = session.get(AuditorGrant, grant_id)
    if g is not None:
        session.delete(g)
        session.commit()
