"""Shared FastAPI dependencies for the API layer.

Engine comes from ``request.app.state.engine``, so these are all module-level
(no per-app closures) and can be imported by the route modules in ``routers/``.
"""

from __future__ import annotations

import os
from types import SimpleNamespace

from fastapi import Depends, Header, HTTPException, Request
from sqlmodel import Session

from . import oauth
from .auditors import resolve_auditor
from .settings import get_setting
from .users import User, session_user, user_by_token

_SEES_ALL = ("platform", "admin")


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
    def dep(user: User = Depends(current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=403, detail="forbidden for this role")
        return user
    return dep


oversight = require("platform", "admin", "auditor")  # read-only oversight + auditors


def public_user(user: User) -> dict:
    # safe projection — pw_hash / pw_salt / token_hash must never cross the wire
    return {"id": user.id, "email": user.email, "role": user.role,
            "team_id": user.team_id, "created_at": user.created_at}


def owner_scope(user: User) -> str | None:
    """None = see everything (platform/admin); else scope to the user's own."""
    return None if user.role in _SEES_ALL else user.id


def provider_creds(session: Session, kind: str) -> dict | None:
    """OAuth client creds: DB settings first, then env fallback."""
    p = oauth.PROVIDERS.get(kind)
    if not p:
        return None
    cid = get_setting(session, f"{kind}.client_id") or os.environ.get(p["id_env"])
    csec = get_setting(session, f"{kind}.client_secret") or os.environ.get(p["secret_env"])
    return {"client_id": cid, "client_secret": csec} if cid and csec else None


def base_url(request: Request) -> str:
    return os.environ.get("APP_BASE_URL", str(request.base_url)).rstrip("/")


def home_url(request: Request) -> str:
    return base_url(request) + "/"
