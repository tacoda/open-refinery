from fastapi import APIRouter

from ..deps import *  # noqa: F401,F403
from ..web import *  # noqa: F401,F403

router = APIRouter()


@router.post("/invitations", status_code=201)
def invite_user(body: NewInvitation, request: Request,
                session: Session = Depends(get_session),
                user: User = Depends(require("senior", "platform", "admin"))):
    inv, token = create_invitation(session, body.email, body.role, user.id,
                                   ttl_days=body.ttl_days)
    accept_url = f"{home_url(request)}#invite={token}"
    try:
        send_invitation_email(body.email, accept_url)
    except Exception:  # email may be unconfigured; the link is still returned
        pass
    return {"invitation": inv, "accept_url": accept_url}

@router.get("/invitations")
def get_invitations(session: Session = Depends(get_session),
                    _: User = Depends(require("senior", "platform", "admin"))):
    return list_invitations(session, status="pending")

@router.post("/invitations/{invitation_id}/revoke")
def revoke_invite(invitation_id: str, session: Session = Depends(get_session),
                  _: User = Depends(require("senior", "platform", "admin"))):
    revoke_invitation(session, invitation_id)
    return {"status": "revoked"}

@router.get("/invitations/lookup")
def lookup_invite(token: str, session: Session = Depends(get_session)):
    return {"email": invitation_email(session, token)}

@router.post("/invitations/accept")
def accept_invite(body: AcceptInvite, session: Session = Depends(get_session)):
    user, token = accept_invitation(session, body.token, body.password)
    return {"token": token, "user": user}

@router.post("/users", status_code=201)
def add_user(body: NewUser, session: Session = Depends(get_session),
             _: User = Depends(require("admin"))):
    user, token = create_user(session, body.email, body.password, body.role)
    return {"user": user, "token": token}  # token shown once

@router.post("/repositories", status_code=201)
def add_repo(body: NewRepo, session: Session = Depends(get_session),
             user: User = Depends(current_user)):
    return create_repository(session, body.name, body.git_url, user.id)

@router.get("/repositories")
def get_repos(session: Session = Depends(get_session), user: User = Depends(current_user)):
    return list_repositories(session, owner_id=owner_scope(user))

@router.post("/repositories/import", status_code=201)
def import_repo(body: NewRepo, session: Session = Depends(get_session),
                user: User = Depends(current_user)):
    return import_or_get(session, body.name, body.git_url, user.id)

@router.post("/processes", status_code=201)
def add_process(body: NewProcess, session: Session = Depends(get_session),
                user: User = Depends(current_user)):
    return create_process(
        session, body.name, body.archetype, body.stages, user.id,
        transitions=body.transitions, initial=body.initial,
        oversight=body.oversight, gates=body.gates, checks=body.checks,
        min_approver_role=body.min_approver_role, approval_chain=body.approval_chain,
        approval_sla_hours=body.approval_sla_hours,
    )

@router.get("/processes")
def get_processes(session: Session = Depends(get_session), user: User = Depends(current_user)):
    return list_processes(session, owner_id=owner_scope(user))

@router.post("/work-items", status_code=201)
def add_work_item(body: NewWorkItem, session: Session = Depends(get_session),
                  user: User = Depends(current_user)):
    return create_work_item(session, body.repo_id, body.process_id, body.title, user.id)

@router.get("/work-items")
def get_work_items(session: Session = Depends(get_session), user: User = Depends(current_user),
                   repo_id: str | None = None):
    return list_work_items(session, owner_id=owner_scope(user), repo_id=repo_id)

@router.get("/work-items/{item_id}/postmortem")
def work_item_postmortem(item_id: str, session: Session = Depends(get_session),
                         _: User = Depends(current_user)):
    return postmortem(session, item_id)

@router.get("/work-items/{item_id}/history")
def work_item_history(item_id: str, session: Session = Depends(get_session),
                      _: User = Depends(current_user)):
    return {"history": stage_history(session, item_id),
            "rollback_targets": rollback_targets(session, item_id)}

@router.post("/work-items/{item_id}/rollback")
def rollback_item(item_id: str, body: Move, session: Session = Depends(get_session),
                  user: User = Depends(current_user)):
    return rollback_work_item(session, item_id, body.to, user.id, SqliteSink(session))

@router.post("/work-items/{item_id}/rollback/applied")
def rollback_applied(item_id: str, body: RollbackApplied,
                     session: Session = Depends(get_session),
                     user: User = Depends(current_user)):
    return record_rollback_applied(session, item_id, user.id, body.status,
                                   SqliteSink(session), detail=body.detail)

# --- live run logs (ephemeral, streamed over the WS hub) ---
@router.get("/work-items/{item_id}/logs")
def get_logs(item_id: str, _: User = Depends(current_user)):
    return recent_logs(item_id)

@router.post("/work-items/{item_id}/logs", status_code=201)
def post_log(item_id: str, body: LogLine, _: User = Depends(current_user)):
    return append_log(item_id, body.line, body.level)

@router.get("/users")
def get_users(session: Session = Depends(get_session),
              _: User = Depends(require("platform", "admin"))):
    return [public_user(u) for u in list_users(session)]  # projected, no hashes

# --- harness identities: auth for coding agents (Claude Code, …) ---
