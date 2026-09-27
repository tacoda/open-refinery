from fastapi import APIRouter

from .. import authority
from ..deps import *  # noqa: F401,F403
from ..models import Repository
from ..web import *  # noqa: F401,F403

router = APIRouter()


@router.post("/users", status_code=201)
def add_user(body: NewUser, session: Session = Depends(get_session),
             actor: User = Depends(manages_users)):
    """Add a person and give them permissions, in one call."""
    try:
        user, token = create_user(session, body.email, body.password, body.role,
                                  permissions=body.permissions)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except DuplicateUser as exc:
        raise HTTPException(status_code=409,
                            detail=f"{body.email} already has an account") from exc

    SqliteSink(session).write(Record.of(
        recipe="user-added", actor=actor.id, owner=actor.id,
        inputs={"preset": body.role, "permissions": user.permissions},
        output=user.email, subject=user.id))
    return {"user": public_user(user), "token": token}  # token shown once

@router.post("/repositories", status_code=201)
def add_repo(body: NewRepo, session: Session = Depends(get_session),
             user: User = Depends(current_user)):
    return create_repository(session, body.name, body.git_url, user.id)

@router.get("/repositories")
def get_repos(session: Session = Depends(get_session), user: User = Depends(current_user)):
    return list_repositories(session, owner_id=owner_scope(session, user))

@router.put("/repositories/{repo_id}")
def update_repo(repo_id: str, body: RepoSettings, session: Session = Depends(get_session),
                user: User = Depends(current_user)):
    """A repository's settings: where its agent configuration lives, which
    credential reads it, and how often to re-read.

    `charter_paths` is the one worth knowing about: the default is `.agents/`
    and `AGENTS.md`, and a team whose rules live in `.claude/`, `.cursorrules`
    or anywhere else says so here. An override **replaces** the default rather
    than adding to it.
    """
    repo = session.get(Repository, repo_id)
    if repo is None:
        raise HTTPException(status_code=404, detail="unknown repository")
    if repo.owner_id != user.id and not authority.sees_operations(user):
        raise HTTPException(status_code=404, detail="unknown repository")

    if body.charter_paths is not None:
        repo.charter_paths = [p for p in body.charter_paths if p.strip()]
    if body.integration_id is not None:
        repo.integration_id = body.integration_id or None
    if body.ingest_interval_hours is not None:
        repo.ingest_interval_hours = max(0, body.ingest_interval_hours)
    session.add(repo)
    session.commit()
    session.refresh(repo)
    return repo


@router.get("/repositories/charter-presets")
def charter_presets(_: User = Depends(current_user)):
    """Known agents' conventions, so overriding the default is a pick rather
    than research."""
    from ..ingest import AGENT_PRESETS, DEFAULT_CHARTER_DIRS, DEFAULT_CHARTER_FILES
    return {"default": list(DEFAULT_CHARTER_DIRS) + list(DEFAULT_CHARTER_FILES),
            "presets": {k: list(v) for k, v in AGENT_PRESETS.items()}}


@router.get("/repositories/{repo_id}/charter")
def repo_charter_view(repo_id: str, session: Session = Depends(get_session),
                      _: User = Depends(current_user)):
    """What this repository says about how work is done here — the text the
    harness will be handed."""
    try:
        return repo_charter(session, repo_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/repositories/import", status_code=201)
def import_repo(body: NewRepo, session: Session = Depends(get_session),
                user: User = Depends(current_user)):
    return import_or_get(session, body.name, body.git_url, user.id)

@router.post("/processes", status_code=201)
def add_process(body: NewProcess, session: Session = Depends(get_session),
                user: User = Depends(approves("factory"))):
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
                  user: User = Depends(may_run)):
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
