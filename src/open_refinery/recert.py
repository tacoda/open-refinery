"""Access recertification campaigns — periodic "re-attest who has access".

A campaign snapshots every active user into review items; a reviewer certifies
(keep) or revokes (deactivate) each. The campaign closes when nothing is pending;
open campaigns past their due date are overdue and get flagged (scheduler sweep,
deduped like the other alerts). Builds on 3.1/3.2 (SSO/SCIM feed who exists).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlmodel import Session, select

from .audit import AuditSink
from .models import RecertCampaign, RecertItem, now_iso
from .provenance import Record
from .store import query_events
from .users import list_users, set_active

DECISIONS = ("certified", "revoked")


@dataclass
class Verdict:
    """A reviewer's decision on one recert item."""
    decision: str          # certified | revoked
    reviewer_id: str
    note: str = ""


def open_campaign(session: Session, name: str, reviewer_id: str, days: int = 30) -> RecertCampaign:
    """Open a campaign and snapshot every active user into a pending review item."""
    due = (datetime.fromisoformat(now_iso()) + timedelta(days=days)).isoformat()
    campaign = RecertCampaign(name=name, created_by=reviewer_id, due_at=due)
    session.add(campaign)
    session.commit()
    session.refresh(campaign)
    for user in list_users(session, kind="human"):
        if user.active:
            session.add(RecertItem(campaign_id=campaign.id, user_id=user.id,
                                   email=user.email, role=user.role))
    session.commit()
    session.refresh(campaign)  # the items-commit expired it; reload before returning
    return campaign


def list_campaigns(session: Session) -> list[RecertCampaign]:
    return list(session.exec(select(RecertCampaign).order_by(RecertCampaign.created_at.desc())))


def get_campaign(session: Session, campaign_id: str) -> RecertCampaign | None:
    return session.get(RecertCampaign, campaign_id)


def list_items(session: Session, campaign_id: str) -> list[RecertItem]:
    return list(session.exec(select(RecertItem).where(RecertItem.campaign_id == campaign_id)))


def progress(session: Session, campaign_id: str) -> dict:
    items = list_items(session, campaign_id)
    return {"total": len(items),
            "certified": sum(1 for i in items if i.decision == "certified"),
            "revoked": sum(1 for i in items if i.decision == "revoked"),
            "pending": sum(1 for i in items if i.decision == "pending")}


def decide_item(session: Session, item_id: str, verdict: Verdict, audit: AuditSink) -> RecertItem:
    """Certify (keep) or revoke (deactivate the user) one item; close the campaign
    when nothing is left pending."""
    if verdict.decision not in DECISIONS:
        raise ValueError(f"decision must be one of {DECISIONS}")
    item = session.get(RecertItem, item_id)
    if item is None:
        raise ValueError(f"unknown recert item: {item_id!r}")
    if verdict.decision == "revoked":
        set_active(session, item.user_id, False)  # revoke access immediately
    item.decision = verdict.decision
    item.decided_by = verdict.reviewer_id
    item.decided_at = now_iso()
    item.note = verdict.note
    session.add(item)
    session.commit()
    session.refresh(item)
    audit.write(Record.of(recipe="recert-decision", actor=verdict.reviewer_id, owner=item.user_id,
                          inputs={"campaign": item.campaign_id, "decision": verdict.decision},
                          output=verdict.decision, subject=item.user_id))
    _close_if_done(session, item.campaign_id)
    return item


def _close_if_done(session: Session, campaign_id: str) -> None:
    if progress(session, campaign_id)["pending"] == 0:
        campaign = session.get(RecertCampaign, campaign_id)
        if campaign and campaign.status == "open":
            campaign.status = "closed"
            session.add(campaign)
            session.commit()


def overdue_campaigns(session: Session, now: str | None = None) -> list[RecertCampaign]:
    now = now or now_iso()
    stmt = (select(RecertCampaign)
            .where(RecertCampaign.status == "open")
            .where(RecertCampaign.due_at != "")
            .where(RecertCampaign.due_at <= now))
    return list(session.exec(stmt))


def emit_overdue(session: Session, audit: AuditSink, now: str | None = None) -> list[str]:
    """One `recert-overdue` audit event per newly-overdue campaign (deduped off the
    append-only audit via subject = campaign id). Returns the campaign ids flagged."""
    now = now or now_iso()
    prior = {e.subject for e in query_events(session, recipe="recert-overdue", limit=1000)}
    flagged = []
    for c in overdue_campaigns(session, now):
        if c.id in prior:
            continue
        audit.write(Record.of(recipe="recert-overdue", actor="system", owner=c.created_by,
                              inputs={"campaign": c.id, "name": c.name, "due_at": c.due_at},
                              output="overdue", subject=c.id))
        flagged.append(c.id)
    return flagged
