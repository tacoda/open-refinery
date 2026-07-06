"""Harness identities — auth for the coding agent.

A harness (Claude Code today; LangGraph and others next) is a **service-account
user** (`kind='agent'`) owned by a person and assigned a role. Its token
authenticates the agent's CLI to the platform, so every call it makes — an
`/authorize` pre-action check, a transition, an executor invoke — is attributed
to it and **governed by its role under the current enforcement mode**, exactly
like a human. Registering one is how you get "auth already set" for the binary.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from sqlmodel import Session, select

from .models import DeviceGrant, User
from .users import DuplicateUser, create_user, list_users, role_rank, rotate_token

# Extensible catalog — start with Claude Code; add agents by appending here.
HARNESS_CATALOG: list[dict] = [
    {"kind": "claude-code", "label": "Claude Code"},
    {"kind": "langgraph", "label": "LangGraph"},
    {"kind": "cursor", "label": "Cursor"},
    {"kind": "aider", "label": "Aider"},
    {"kind": "codex", "label": "Codex CLI"},
    {"kind": "generic", "label": "Other / generic agent"},
]
_KINDS = {h["kind"] for h in HARNESS_CATALOG}


def _slug(name: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in name.strip().lower()).strip("-") or "agent"


def register_harness(session: Session, harness_kind: str, name: str, owner_id: str,
                     role: str) -> tuple[User, str]:
    """Create an agent identity and return (agent_user, token). Token shown once."""
    if harness_kind not in _KINDS:
        raise ValueError(f"unknown harness: {harness_kind!r} (expected {sorted(_KINDS)})")
    if session.get(User, owner_id) is None:
        raise ValueError(f"unknown owner: {owner_id!r}")
    email = f"{_slug(name)}@{harness_kind}.agent"  # the agent's stable handle
    if session.exec(select(User).where(User.email == email)).first():
        raise DuplicateUser(email)
    agent, token = create_user(session, email, secrets.token_urlsafe(16), role)
    agent.kind = "agent"
    agent.harness_kind = harness_kind
    agent.owner_id = owner_id
    session.add(agent)
    session.commit()
    session.refresh(agent)
    return agent, token


def list_harnesses(session: Session, *, owner_id: str | None = None) -> list[User]:
    agents = list_users(session, kind="agent")
    return [a for a in agents if owner_id is None or a.owner_id == owner_id]


def harness_view(agent: User) -> dict:
    """Safe projection — never the token/hashes."""
    return {"id": agent.id, "name": agent.email.split("@")[0], "harness_kind": agent.harness_kind,
            "role": agent.role, "owner_id": agent.owner_id, "created_at": agent.created_at}


def rotate_harness(session: Session, agent_id: str) -> str:
    return rotate_token(session, agent_id)


def delete_harness(session: Session, agent_id: str) -> None:
    agent = session.get(User, agent_id)
    if agent is not None and agent.kind == "agent":
        session.delete(agent)
        session.commit()


# --- OAuth device flow ----------------------------------------------------
# The agent starts a grant, a human approves it (minting the agent + token),
# the agent polls to collect the token. RFC 8628 shape, single-tenant.

DEVICE_TTL_SECONDS = 600
POLL_INTERVAL_SECONDS = 5


class DevicePending(Exception):
    """The device grant is awaiting human approval."""


class DeviceExpired(Exception):
    """The device grant expired or was already consumed."""


def _user_code() -> str:
    a = secrets.token_hex(2).upper(); b = secrets.token_hex(2).upper()
    return f"{a}-{b}"


def device_start(session: Session, harness_kind: str, name: str) -> DeviceGrant:
    """Agent-side: open a pending grant, returning device + user codes."""
    if harness_kind not in _KINDS:
        raise ValueError(f"unknown harness: {harness_kind!r} (expected {sorted(_KINDS)})")
    expires = datetime.now(timezone.utc) + timedelta(seconds=DEVICE_TTL_SECONDS)
    grant = DeviceGrant(device_code=secrets.token_urlsafe(32), user_code=_user_code(),
                        harness_kind=harness_kind, name=name, expires_at=expires.isoformat())
    session.add(grant)
    session.commit()
    session.refresh(grant)
    return grant


def _grant_by_user_code(session: Session, user_code: str) -> DeviceGrant | None:
    return session.exec(select(DeviceGrant).where(DeviceGrant.user_code == user_code)).first()


def _expired(grant: DeviceGrant) -> bool:
    return datetime.now(timezone.utc) > datetime.fromisoformat(grant.expires_at)


def device_approve(session: Session, user_code: str, approver: User, role: str) -> DeviceGrant:
    """Human-side: approve a pending grant → mint the agent (owned by approver)."""
    grant = _grant_by_user_code(session, user_code.strip().upper())
    if grant is None or grant.status != "pending":
        raise ValueError(f"no pending device request for code {user_code!r}")
    if _expired(grant):
        raise DeviceExpired("device request expired")
    if role_rank(session, role) > role_rank(session, approver.role):
        raise ValueError("agent role cannot exceed your own")
    agent, token = register_harness(session, grant.harness_kind, grant.name, approver.id, role)
    grant.status = "approved"
    grant.agent_id = agent.id
    grant.token = token          # held until the agent's next poll
    session.add(grant)
    session.commit()
    session.refresh(grant)
    return grant


def device_poll(session: Session, device_code: str) -> str:
    """Agent-side: exchange the device_code for the token once approved.

    Raises DevicePending while awaiting approval, DeviceExpired if expired/used.
    On success returns the token once, then marks the grant consumed.
    """
    grant = session.get(DeviceGrant, device_code)
    if grant is None or grant.status == "consumed":
        raise DeviceExpired("unknown or consumed device code")
    if grant.status == "pending":
        if _expired(grant):
            raise DeviceExpired("device request expired")
        raise DevicePending("awaiting approval")
    token = grant.token or ""
    grant.status = "consumed"
    grant.token = None           # never return it twice
    session.add(grant)
    session.commit()
    return token
