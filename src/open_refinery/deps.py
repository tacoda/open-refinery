"""Shared FastAPI dependencies for the API layer.

Engine comes from ``request.app.state.engine``, so these are all module-level
(no per-app closures) and can be imported by the route modules in ``routers/``.
"""

from __future__ import annotations

import os
from types import SimpleNamespace

from fastapi import Depends, Header, HTTPException, Request
from sqlmodel import Session

from . import authority
from .auditors import resolve_auditor
from .settings import get_setting
from .users import User, session_user, user_by_token


def get_session(request: Request):
    with Session(request.app.state.engine) as s:
        yield s


def current_user(
    session: Session = Depends(get_session),
    authorization: str | None = Header(default=None),
) -> User:
    token = (authorization or "").removeprefix("Bearer ").strip()
    user = (user_by_token(session, token) or session_user(session, token)) if token else None
    if user is None and token:  # a time-boxed auditor grant → read-only principal
        grant = resolve_auditor(session, token)
        if grant is not None:
            return SimpleNamespace(id=grant.id, email=grant.label, role="auditor",
                                   team_id=None, kind="auditor", owner_id=None,
                                   created_at=grant.created_at)
    if user is None:
        raise HTTPException(status_code=401, detail="invalid or missing token")
    return user


def require(*roles: str):
    """Guard by role *name*. Prefer the authority guards below — a route that
    names roles cannot be re-pointed by a team that defines its own."""
    def dep(user: User = Depends(current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=403, detail="forbidden for this role")
        return user
    return dep


# --- authority guards: what the role may DO, not what it is called ----------
# These read the powers off the role row (see authority.py), so a team that
# defines `reviewer` or splits `platform` in two gets working routes without a
# code change. Every one fails closed.

def _power(check, detail: str):
    def dep(user: User = Depends(current_user),
            session: Session = Depends(get_session)) -> User:
        if not check(session, user.role):
            raise HTTPException(status_code=403, detail=detail)
        return user
    return dep


manages_users = _power(authority.manages_users,
                       "managing users requires a role with that authority")
reads_audit = _power(authority.reads_audit,
                     "reading the audit trail requires a role with that authority")
sees_operations = _power(authority.sees_operations,
                         "this is an operations surface; your role does not see it")

# Back-compat name for the read-only oversight surface — now "whoever may read
# the audit trail", which is admin and the time-boxed auditor grant.
oversight = reads_audit


def approves(layer: str):
    """Guard a change to one governance layer — `harness` is the lead's,
    `factory` is platform's. Named per-layer so the route says which."""
    def dep(user: User = Depends(current_user),
            session: Session = Depends(get_session)) -> User:
        if not authority.may_approve(session, user.role, layer):
            owners = authority.approvers_for(session, layer) or ["nobody"]
            raise HTTPException(
                status_code=403,
                detail=f"approving a {layer} change is for: {', '.join(owners)}")
        return user
    return dep


def public_user(user: User) -> dict:
    # safe projection — pw_hash / pw_salt / token_hash must never cross the wire
    return {"id": user.id, "email": user.email, "role": user.role,
            "team_id": user.team_id, "created_at": user.created_at}


def owner_scope(session: Session, user: User) -> str | None:
    """None = see everyone's; else scope to the caller's own.

    Keyed on `sees_operations` rather than a role list, so **admin no longer
    sees everyone's operational data** — it manages users and reads audit. That
    is the separation: the account that grants access is not the account that
    watches the work.
    """
    return None if authority.sees_operations(session, user.role) else user.id


def audit_scope(session: Session, user: User) -> str | None:
    """None = read the whole audit trail; else only events the caller owns.

    Separate from `owner_scope` because they answer different questions. Audit
    is admin's and the auditor grant's; operational data is platform's. Using
    the operations scope here locked admin out of the log it is responsible for.
    """
    return None if authority.reads_audit(session, user.role) else user.id


def base_url(request: Request) -> str:
    return os.environ.get("APP_BASE_URL", str(request.base_url)).rstrip("/")


def home_url(request: Request) -> str:
    return base_url(request) + "/"
