from dataclasses import dataclass

from fastapi import APIRouter

from ..deps import *  # noqa: F401,F403
from ..web import *  # noqa: F401,F403

router = APIRouter()


@dataclass
class EventFilter:  # query params for /events, grouped so the handler stays small
    subject: str | None = None
    actor: str | None = None
    limit: int = 100


@dataclass
class CsvFilter:  # query params for /audit/export.csv
    actor: str | None = None
    recipe: str | None = None
    subject: str | None = None
    since: str | None = None
    until: str | None = None
    limit: int = 10000


@router.get("/approvals")
def get_approvals(session: Session = Depends(get_session), user: User = Depends(current_user),
                  status: str | None = "pending"):
    """What is waiting on a person.

    A run holds at a gated stage and waits; clearing it is
    `POST /runs/{id}/approve`, which needs `approve:code`. Until 3.0 this listed
    a separate queue of kanban-transition approvals, signed by *role rank* — an
    authority model the rest of the product had already left behind.
    """
    from ..pipeline import store as ps

    scope = None if authority.sees_operations(user) else user.id
    runs = ps.list_runs(session, actor_id=scope, active=True)
    if status == "pending":
        runs = [r for r in runs if r.held]
    return [{"run_id": r.id, "work_item_id": r.work_item_id, "stage": r.stage,
             "requested_by": r.actor_id, "held": r.held,
             "approve_with": f"POST /runs/{r.id}/approve",
             "created_at": r.created_at} for r in runs]

@router.get("/events")
def get_events(q: EventFilter = Depends(), session: Session = Depends(get_session),
               _: User = Depends(reads_audit)):
    """The audit trail. `read:audit` and nothing less.

    It used to be open and merely *scoped*, with a role-name middleware
    supplying the refusal. That middleware is gone, and "everyone can read the
    parts about themselves" is the wrong default for an audit log: an actor who
    can see what was recorded about them can see it before deciding what to do
    about it.
    """
    return query_events(session, subject=q.subject, actor=q.actor, limit=q.limit)

@router.post("/audit/purge")
def purge_audit(days: int, session: Session = Depends(get_session),
                _: User = Depends(manages_users)):
    """Retention: drop events older than `days`, leaving a signed checkpoint.

    **`manage:users`, not `read:audit`.** Destroying the record is an
    administrative act, and it was guarded by the permission that reads the
    record — which handed it to the time-boxed auditor grant, the one principal
    whose whole purpose is to read and change nothing.
    """
    return {"purged": purge_events(session, days)}

@router.get("/audit/verify")
def audit_verify(session: Session = Depends(get_session), _: User = Depends(oversight)):
    return verify_chain(session)  # recompute the tamper-evident hash chain

@router.get("/audit/export")
def audit_export(session: Session = Depends(get_session), _: User = Depends(oversight)):
    return export_chain(session)  # portable, signed export for external auditors

@router.get("/audit/export.csv", dependencies=[Depends(oversight)])
def audit_export_csv(q: CsvFilter = Depends(), session: Session = Depends(get_session)):
    csv_text = events_csv(session, actor=q.actor, recipe=q.recipe, subject=q.subject,
                          since=q.since, until=q.until, limit=q.limit)
    return PlainTextResponse(csv_text, media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=audit.csv"})

# --- compliance evidence packs + time-boxed auditor access ---
@router.get("/evidence/frameworks")
def evidence_frameworks(_: User = Depends(oversight)):
    return list(FRAMEWORKS)

@router.get("/evidence")
def evidence(framework: str = "soc2", session: Session = Depends(get_session),
             _: User = Depends(oversight)):
    return evidence_pack(session, framework)

@router.get("/auditor-grants")
def get_auditor_grants(session: Session = Depends(get_session),
                       _: User = Depends(reads_audit)):
    return [auditor_view(g) for g in list_auditors(session)]

@router.post("/auditor-grants", status_code=201)
def add_auditor_grant(body: NewAuditor, session: Session = Depends(get_session),
                      user: User = Depends(manages_users)):
    """Mint a time-boxed read-only credential. **`manage:users`** — handing
    somebody access is the admin act, and under `read:audit` a grant could mint
    itself a fresh one and never expire."""
    grant, token = mint_auditor(session, body.label, user.id, ttl_days=body.ttl_days)
    return {"grant": auditor_view(grant), "token": token}  # shown once

@router.delete("/auditor-grants/{grant_id}")
def remove_auditor_grant(grant_id: str, session: Session = Depends(get_session),
                         _: User = Depends(manages_users)):
    revoke_auditor(session, grant_id)
    return {"status": "revoked"}

@router.get("/metrics")
def metrics(session: Session = Depends(get_session), user: User = Depends(current_user)):
    return summary(session, owner_id=owner_scope(session, user))

# --- integrations ---
