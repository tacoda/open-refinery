"""Webhooks — fan audit events out to external endpoints, HMAC-signed.

Register a URL with an optional **event filter** (recipe names; empty = all) and
a generated **signing secret** (shown once, stored encrypted). When an audit
`Event` is written, `deliver()` POSTs a JSON payload to each matching active
endpoint with an `X-OpenRefinery-Signature: sha256=<hmac>` header so receivers
can verify authenticity.

Delivery is synchronous best-effort today (errors are swallowed, the last HTTP
status is recorded) — moving it onto a background runner is the post-1.0 job-queue
item. The sender is injectable, so signing/filtering/dispatch are tested offline.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import urllib.request

from sqlmodel import Session, select

from .crypto import decrypt, encrypt
from .models import Webhook
from .provenance import Record


def sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _default_sender(url: str, body: bytes, headers: dict) -> int:
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=5) as r:
        return r.status


def create_webhook(session: Session, url: str, events: list[str], owner_id: str) -> tuple[Webhook, str]:
    """Register an endpoint; returns (webhook, plaintext secret shown once)."""
    secret = secrets.token_urlsafe(32)
    wh = Webhook(url=url, events=list(events or []), secret=encrypt(secret), owner_id=owner_id)
    session.add(wh)
    session.commit()
    session.refresh(wh)
    return wh, secret


def list_webhooks(session: Session, *, owner_id: str | None = None) -> list[Webhook]:
    stmt = select(Webhook)
    if owner_id is not None:
        stmt = stmt.where(Webhook.owner_id == owner_id)
    return list(session.exec(stmt.order_by(Webhook.created_at.desc())))


def delete_webhook(session: Session, webhook_id: str) -> None:
    wh = session.get(Webhook, webhook_id)
    if wh is not None:
        session.delete(wh)
        session.commit()


def deliver(session: Session, record: Record, *, sender=None) -> int:
    """POST the event to every active webhook whose filter matches. Best-effort.

    Returns the number of endpoints attempted. The sender is (url, body, headers)
    -> status; defaults to a short-timeout urllib POST.
    """
    sender = sender or _default_sender
    hooks = [w for w in session.exec(select(Webhook).where(Webhook.active == True))  # noqa: E712
             if not w.events or record.recipe in w.events]
    if not hooks:
        return 0

    payload = {"id": record.artifact_id, "recipe": record.recipe, "actor": record.actor,
               "owner": record.owner, "subject": record.subject, "created_at": record.created_at}
    body = json.dumps(payload, sort_keys=True).encode()

    for wh in hooks:
        headers = {"Content-Type": "application/json",
                   "X-OpenRefinery-Signature": sign(decrypt(wh.secret), body)}
        try:
            wh.last_status = sender(wh.url, body, headers)
        except Exception:  # best-effort: record failure, never raise into the write path
            wh.last_status = 0
        wh.last_at = record.created_at
        session.add(wh)
    session.commit()
    return len(hooks)
