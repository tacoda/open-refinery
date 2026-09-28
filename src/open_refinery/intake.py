"""Intake — how work gets in.

Three doors, all arriving at the same place: a `WorkItem`, and optionally a
`Run` started against it.

1. **sync** — pull a tracker's issues on demand (`POST /integrations/{id}/sync`)
2. **webhook** — a tracker pushes one the moment it is filed
3. **by hand** — somebody types a title

A ticket is **untrusted data**. Its title and body are written by whoever filed
it, which on a public tracker is anybody at all, so it reaches a phase as a
quoted spec and never as instructions. Rung 3 governs every call it provokes,
and nothing here interpolates a ticket into a prompt.

The webhook secret is per-integration and compared with `hmac.compare_digest`,
because an early-exit comparison leaks the signature one byte at a time.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass

from sqlmodel import Session, select

from .audit import AuditSink
from .models import Integration, Repository, WorkItem, now_iso
from .provenance import Record
from .work_items import create_work_item, find_by_external_ref


class IntakeError(ValueError):
    """The delivery could not be accepted."""


class BadSignature(IntakeError):
    """The payload did not come from who it claims."""


@dataclass(frozen=True)
class Ticket:
    """One piece of work, however its tracker spells it."""

    key: str
    title: str
    body: str = ""
    url: str = ""
    state: str = ""

    @property
    def is_closed(self) -> bool:
        return self.state.lower() in ("closed", "done", "merged", "resolved")


# --- what each tracker's webhook looks like ---------------------------------
# One parser per tracker, registered like every other adapter. A payload shape
# nobody recognises is refused rather than guessed at.

def _github(payload: dict) -> tuple[str, Ticket | None]:
    issue = payload.get("issue") or {}
    if not issue:
        return payload.get("action", ""), None
    return payload.get("action", ""), Ticket(
        key=f"#{issue.get('number')}", title=issue.get("title") or "",
        body=issue.get("body") or "", url=issue.get("html_url") or "",
        state=issue.get("state") or "")


def _gitlab(payload: dict) -> tuple[str, Ticket | None]:
    attrs = payload.get("object_attributes") or {}
    if payload.get("object_kind") != "issue" or not attrs:
        return "", None
    return attrs.get("action", ""), Ticket(
        key=f"#{attrs.get('iid')}", title=attrs.get("title") or "",
        body=attrs.get("description") or "", url=attrs.get("url") or "",
        state=attrs.get("state") or "")


def _jira(payload: dict) -> tuple[str, Ticket | None]:
    issue = payload.get("issue") or {}
    fields = issue.get("fields") or {}
    if not issue:
        return "", None
    event = (payload.get("webhookEvent") or "").split(":")[-1]
    return event, Ticket(
        key=issue.get("key") or "", title=fields.get("summary") or "",
        body=str(fields.get("description") or ""),
        state=(fields.get("status") or {}).get("name") or "")


def _linear(payload: dict) -> tuple[str, Ticket | None]:
    data = payload.get("data") or {}
    if payload.get("type") != "Issue" or not data:
        return "", None
    return (payload.get("action") or "").lower(), Ticket(
        key=data.get("identifier") or "", title=data.get("title") or "",
        body=data.get("description") or "", url=data.get("url") or "",
        state=(data.get("state") or {}).get("name") or "")


PARSERS = {"github-issues": _github, "gitlab-issues": _gitlab,
           "jira": _jira, "linear": _linear}

# Which deliveries mean "there is new work". A tracker fires on every edit, and
# importing on every one would create a work item each time somebody fixes a
# typo in a title.
OPENING = {"opened", "open", "created", "reopened", "issue_created"}


def parse(kind: str, payload: dict) -> tuple[str, Ticket | None]:
    parser = PARSERS.get(kind)
    if parser is None:
        raise IntakeError(f"no webhook parser for {kind!r} "
                          f"(have {', '.join(sorted(PARSERS))})")
    return parser(payload)


# --- the signature ----------------------------------------------------------

def sign(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def verify(secret: str, body: bytes, header: str) -> None:
    """Refuse anything that did not come from the tracker we gave the secret to.

    Compared with `compare_digest`, because an early-exit comparison leaks the
    signature a byte at a time to anybody who can time it.
    """
    if not secret:
        raise BadSignature("this integration has no webhook secret — set one first")
    given = (header or "").split("=")[-1].strip()
    if not given or not hmac.compare_digest(given, sign(secret, body)):
        raise BadSignature("signature does not match")


# --- accepting a delivery ---------------------------------------------------

def accept(session: Session, integration_id: str, body: bytes, signature: str,
           *, audit: AuditSink) -> dict:
    """Take a webhook delivery and turn it into work, if it is new work.

    Deduped by external ref, so a tracker re-delivering (which they all do) does
    not create a second work item for the same ticket.
    """
    integ = session.get(Integration, integration_id)
    if integ is None:
        raise IntakeError("unknown integration")

    verify(integ.webhook_secret, body, signature)

    try:
        payload = json.loads(body or b"{}")
    except ValueError as exc:
        raise IntakeError(f"payload is not JSON: {exc}") from None

    action, ticket = parse(integ.kind, payload)
    if ticket is None:
        return {"accepted": False, "why": "not an issue event"}
    if action and action not in OPENING:
        return {"accepted": False, "why": f"'{action}' is not new work"}
    if not integ.intake_repo_id:
        return {"accepted": False,
                "why": "this integration has no repo to file into"}

    ref = f"{integ.kind}:{ticket.key}"
    if find_by_external_ref(session, ref):
        return {"accepted": False, "why": "already imported", "ref": ref}

    item = create_work_item(session, integ.intake_repo_id, ticket.title,
                            integ.owner_id, external_ref=ref)
    audit.write(Record.of(
        recipe="intake", actor=integ.owner_id, owner=integ.owner_id,
        inputs={"integration": integ.id, "tracker": integ.kind, "key": ticket.key},
        output=ref, subject=item.id))

    out = {"accepted": True, "work_item": item.id, "ref": ref, "run": None}
    if integ.autostart:
        out["run"], why = _start(session, item, ticket, integ, audit)
        if why:
            out["why"] = why   # autostart was on and nothing ran — say so
    return out


def _start(session: Session, item: WorkItem, ticket: Ticket, integ: Integration,
           audit: AuditSink) -> tuple[str | None, str]:
    """Start a run for a freshly filed ticket.

    The ticket's body becomes the spec — **quoted, never interpolated into a
    prompt**. Whoever filed it wrote that text, and on a public tracker that is
    anybody at all.

    Returns the run, or nothing and the reason. A silent `null` here reads as
    "autostart is broken" when the real answer is "that workflow does not
    exist" — the kind of thing somebody loses a morning to.
    """
    from .pipeline import store as ps

    name = integ.intake_pipeline or "ship-a-ticket"
    try:
        pipeline = ps.latest_pipeline(session, name)
    except ps.UnknownPipeline:
        return None, f"no workflow named {name!r} — nothing started"

    spec = ticket.title if not ticket.body else f"{ticket.title}\n\n{ticket.body}"
    run = ps.start_run(session, item.id, pipeline, item.repo_id, integ.owner_id,
                       spec=spec)
    audit.write(Record.of(
        recipe="run-started", actor=integ.owner_id, owner=integ.owner_id,
        inputs={"from": "intake", "pipeline": pipeline.name, "work_item": item.id},
        output=run.stage, subject=run.id))
    return run.id, ""


def configure(session: Session, integration_id: str, *, repo_id: str = "",
              pipeline: str = "", autostart: bool | None = None,
              rotate_secret: bool = False) -> tuple[Integration, str]:
    """Point an integration at where its tickets should land.

    Returns the integration and, when rotated, the new secret — **shown once**,
    the way every other secret here is.
    """
    import secrets as _secrets

    integ = session.get(Integration, integration_id)
    if integ is None:
        raise IntakeError("unknown integration")
    if repo_id and session.get(Repository, repo_id) is None:
        raise IntakeError(f"unknown repository: {repo_id!r}")

    if repo_id:
        integ.intake_repo_id = repo_id
    if pipeline:
        integ.intake_pipeline = pipeline
    if autostart is not None:
        integ.autostart = autostart

    shown = ""
    if rotate_secret or (integ.autostart and not integ.webhook_secret):
        shown = _secrets.token_urlsafe(32)
        integ.webhook_secret = shown

    session.add(integ)
    session.commit()
    session.refresh(integ)
    return integ, shown
