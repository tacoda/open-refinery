from dataclasses import dataclass

from fastapi import APIRouter

from ..anomalies import scan as scan_anomalies
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


@router.post("/work-items/{item_id}/attest", status_code=201)
def add_attestation(item_id: str, body: Attest, session: Session = Depends(get_session),
                    user: User = Depends(current_user)):
    attest(session, item_id, body.check, user.id, body.passed, SqliteSink(session))
    return {"status": "recorded"}

@router.post("/work-items/{item_id}/transition")
def move(item_id: str, body: Move, session: Session = Depends(get_session),
         user: User = Depends(current_user)):
    return transition(session, item_id, body.to, user.id, SqliteSink(session),
                      approver_id=user.id if body.approve else None, changes=body.changes)

# --- async approval queue (chained sign-off) ---
@router.post("/work-items/{item_id}/request-approval", status_code=201)
def request_move_approval(item_id: str, body: RequestApproval,
                          session: Session = Depends(get_session),
                          user: User = Depends(current_user)):
    return request_approval(session, item_id, body.to, user.id, SqliteSink(session))

@router.get("/approvals")
def get_approvals(session: Session = Depends(get_session), _: User = Depends(current_user),
                  status: str | None = "pending"):
    return list_approvals(session, status=status)

@router.get("/approvals/overdue")
def get_overdue_approvals(session: Session = Depends(get_session),
                          _: User = Depends(current_user)):
    return current_overdue(session)

@router.post("/approvals/{request_id}/approve")
def approve_move(request_id: str, session: Session = Depends(get_session),
                 user: User = Depends(current_user)):
    return approve_request(session, request_id, user.id, SqliteSink(session))

@router.post("/approvals/{request_id}/reject")
def reject_move(request_id: str, session: Session = Depends(get_session),
                user: User = Depends(current_user)):
    return reject_request(session, request_id, user.id, SqliteSink(session))

@router.get("/events")
def get_events(q: EventFilter = Depends(), session: Session = Depends(get_session),
               user: User = Depends(current_user)):
    return query_events(session, owner=owner_scope(user), subject=q.subject,
                        actor=q.actor, limit=q.limit)

@router.get("/anomalies", dependencies=[Depends(oversight)])
def get_anomalies(session: Session = Depends(get_session)):
    return scan_anomalies(session)  # behavioral signals over the audit trail

@router.post("/audit/purge")
def purge_audit(days: int, session: Session = Depends(get_session),
                _: User = Depends(require("admin"))):
    return {"purged": purge_events(session, days)}  # retention: drop events older than `days`

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
                       _: User = Depends(require("admin"))):
    return [auditor_view(g) for g in list_auditors(session)]

@router.post("/auditor-grants", status_code=201)
def add_auditor_grant(body: NewAuditor, session: Session = Depends(get_session),
                      user: User = Depends(require("admin"))):
    grant, token = mint_auditor(session, body.label, user.id, ttl_days=body.ttl_days)
    return {"grant": auditor_view(grant), "token": token}  # shown once

@router.delete("/auditor-grants/{grant_id}")
def remove_auditor_grant(grant_id: str, session: Session = Depends(get_session),
                         _: User = Depends(require("admin"))):
    revoke_auditor(session, grant_id)
    return {"status": "revoked"}

@router.get("/metrics")
def metrics(session: Session = Depends(get_session), user: User = Depends(current_user)):
    return summary(session, owner_id=owner_scope(user))

# --- integrations ---
