"""SCIM 2.0 provisioning helpers — the IdP creates/updates/deactivates accounts.

Single-tenant, fixed three roles: an IdP group maps to developer/platform/admin
(the most-privileged mapped group wins); unmapped users get the configured
default. Deprovisioning soft-deactivates (see `users.set_active`). SCIM callers
authenticate with a dedicated provisioning token (its hash lives in settings),
never a user token.
"""

from __future__ import annotations

import hashlib
import json
import secrets

from sqlmodel import Session

from .models import User
from .settings import get_setting, set_setting
from .users import role_rank

USER_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:User"
LIST_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:ListResponse"
_TOKEN_KEY = "scim.token_hash"
_MAP_KEY = "scim.group_map"
_DEFAULT_KEY = "scim.default_role"


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def rotate_token(session: Session, actor_id: str) -> str:
    """Issue a new SCIM provisioning token (returned once); store only its hash."""
    token = secrets.token_urlsafe(32)
    set_setting(session, _TOKEN_KEY, _hash(token), actor_id)
    return token


def verify_token(session: Session, token: str) -> bool:
    stored = get_setting(session, _TOKEN_KEY)
    return bool(stored) and bool(token) and secrets.compare_digest(stored, _hash(token))


def configured(session: Session) -> bool:
    return bool(get_setting(session, _TOKEN_KEY))


def group_map(session: Session) -> dict:
    return json.loads(get_setting(session, _MAP_KEY) or "{}")


def default_role(session: Session) -> str:
    return get_setting(session, _DEFAULT_KEY) or "developer"


def set_group_map(session: Session, mapping: dict, default: str, actor_id: str) -> None:
    set_setting(session, _MAP_KEY, json.dumps(mapping), actor_id)
    set_setting(session, _DEFAULT_KEY, default, actor_id)


def role_from_groups(session: Session, groups: list[str]) -> str:
    """The most-privileged role among the user's mapped groups, else the default."""
    mapping = group_map(session)
    roles = [mapping[g] for g in (groups or []) if g in mapping]
    if not roles:
        return default_role(session)
    return max(roles, key=lambda r: role_rank(session, r))


def to_scim(user: User) -> dict:
    """Represent a user as a SCIM 2.0 User resource."""
    return {
        "schemas": [USER_SCHEMA],
        "id": user.id,
        "userName": user.email,
        "active": user.active,
        "emails": [{"value": user.email, "primary": True}],
        "meta": {"resourceType": "User"},
    }


def list_response(users: list[User]) -> dict:
    return {"schemas": [LIST_SCHEMA], "totalResults": len(users),
            "Resources": [to_scim(u) for u in users]}
