from fastapi import APIRouter

from ..deps import *  # noqa: F401,F403
from ..web import *  # noqa: F401,F403

router = APIRouter()


@router.post("/users", status_code=201)
def add_user(body: NewUser, session: Session = Depends(get_session),
             _: User = Depends(manages_users)):
    user, token = create_user(session, body.email, body.password, body.role)
    return {"user": user, "token": token}  # token shown once

@router.post("/repositories", status_code=201)
def add_repo(body: NewRepo, session: Session = Depends(get_session),
             user: User = Depends(current_user)):
    return create_repository(session, body.name, body.git_url, user.id)

@router.get("/repositories")
def get_repos(session: Session = Depends(get_session), user: User = Depends(current_user)):
    return list_repositories(session, owner_id=owner_scope(session, user))

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
def get_processes(session: Session = Depends(get_session), _: User = Depends(current_user)):
    """Every process, to any authenticated user.

    A process is a **shared workflow definition**, not personal property: it is
    the board everyone's work moves across, so a developer has to be able to
    read the one their own work items sit on. Owner-scoping this meant a
    developer could hold a work item at a stage while being unable to see the
    stages — which is what the seeded dev account hit.

    Authoring stays gated (`POST /processes` is platform+). Reading is not.
    """
    return list_processes(session)

@router.post("/work-items", status_code=201)
def add_work_item(body: NewWorkItem, session: Session = Depends(get_session),
                  user: User = Depends(current_user)):
    return create_work_item(session, body.repo_id, body.process_id, body.title, user.id)

@router.get("/work-items")
def get_work_items(session: Session = Depends(get_session), user: User = Depends(current_user),
                   repo_id: str | None = None):
    return list_work_items(session, owner_id=owner_scope(session, user), repo_id=repo_id)

@router.get("/work-items/{item_id}/logs")
def get_logs(item_id: str, _: User = Depends(current_user)):
    return recent_logs(item_id)

@router.post("/work-items/{item_id}/logs", status_code=201)
def post_log(item_id: str, body: LogLine, _: User = Depends(current_user)):
    return append_log(item_id, body.line, body.level)

@router.get("/users")
def get_users(session: Session = Depends(get_session),
              _: User = Depends(manages_users)):
    return [public_user(u) for u in list_users(session)]  # projected, no hashes

# --- harness identities: auth for coding agents (Claude Code, …) ---
