"""Governance notifications — turn the audit stream into proactive signals.

A rule matches an audit event recipe (blank = any) and sends a human-readable
message to a channel: Slack (incoming-webhook URL), email (the pluggable email
port), or a plain webhook. Dispatch runs best-effort on every audit write — a
failing channel never blocks the governed action.
"""

from __future__ import annotations

import json
import urllib.request

from sqlmodel import Session, select

from .models import NotificationRule, User

CHANNELS = ("slack", "email", "webhook")


def create_rule(session: Session, label: str, channel: str, target: str, *,
                recipe: str = "", created_by: str | None = None) -> NotificationRule:
    if channel not in CHANNELS:
        raise ValueError(f"unknown channel: {channel!r} (expected {CHANNELS})")
    if created_by is not None and session.get(User, created_by) is None:
        raise ValueError(f"unknown creator: {created_by!r}")
    rule = NotificationRule(label=label, channel=channel, target=target,
                            recipe=recipe, created_by=created_by)
    session.add(rule)
    session.commit()
    session.refresh(rule)
    return rule


def list_rules(session: Session) -> list[NotificationRule]:
    return list(session.exec(select(NotificationRule).order_by(NotificationRule.created_at.desc())))


def delete_rule(session: Session, rule_id: str) -> None:
    r = session.get(NotificationRule, rule_id)
    if r is not None:
        session.delete(r)
        session.commit()


def _post_json(url: str, payload: dict) -> None:
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=10)


def send(rule: NotificationRule, text: str, payload: dict) -> None:
    """Deliver one message over the rule's channel. Raises on transport error."""
    if rule.channel == "slack":
        _post_json(rule.target, {"text": text})           # Slack incoming webhook
    elif rule.channel == "webhook":
        _post_json(rule.target, {"text": text, **payload})
    elif rule.channel == "email":
        from .email import send_email
        send_email(rule.target, "[open-refinery] governance alert", text)


def dispatch(session: Session, record) -> None:
    """Fire every matching rule for an audit record. Best-effort; never raises."""
    try:
        rules = list_rules(session)
    except Exception:
        return
    text = (f"[open-refinery] {record.recipe} by {record.actor}"
            + (f" on {record.subject}" if record.subject else ""))
    payload = {"recipe": record.recipe, "actor": record.actor, "subject": record.subject,
               "at": record.created_at}
    for r in rules:
        if not r.enabled or (r.recipe and r.recipe != record.recipe):
            continue
        try:
            send(r, text, payload)
        except Exception:  # a broken channel must never block the governed action
            pass
