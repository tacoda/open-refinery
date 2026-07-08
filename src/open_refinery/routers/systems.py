from fastapi import APIRouter

from ..deps import *  # noqa: F401,F403
from ..web import *  # noqa: F401,F403

router = APIRouter()


@router.get("/systems")
def get_systems(session: Session = Depends(get_session), _: User = Depends(current_user)):
    return list_systems(session)

@router.post("/systems", status_code=201)
def add_system(body: NewSystem, session: Session = Depends(get_session),
               user: User = Depends(require("platform", "admin"))):
    return create_system(session, body.name, body.kind, user.id, repo_ids=body.repo_ids)

@router.post("/systems/{system_id}/repos")
def set_repos(system_id: str, body: SystemRepos, session: Session = Depends(get_session),
              _: User = Depends(require("platform", "admin"))):
    return set_system_repos(session, system_id, body.repo_ids)

@router.get("/systems/{system_id}/coverage")
def sys_coverage(system_id: str, session: Session = Depends(get_session),
                 _: User = Depends(current_user)):
    return system_coverage(session, system_id)

@router.delete("/systems/{system_id}")
def remove_system(system_id: str, session: Session = Depends(get_session),
                  _: User = Depends(require("platform", "admin"))):
    delete_system(session, system_id)
    return {"status": "deleted"}

# --- repo-level drift & coverage ---
@router.get("/repositories/{repo_id}/coverage")
def get_coverage(repo_id: str, session: Session = Depends(get_session),
                 _: User = Depends(current_user)):
    return repo_report(session, repo_id)

@router.get("/repositories/{repo_id}/claims")
def get_claims(repo_id: str, session: Session = Depends(get_session),
               _: User = Depends(current_user)):
    return list_claims(session, repo_id)

@router.post("/repositories/{repo_id}/ingest")
def ingest_repo(repo_id: str, background: bool = False,
                session: Session = Depends(get_session), user: User = Depends(current_user)):
    if background:  # network read off the request path; poll /jobs/{id}
        return enqueue(session, session.get_bind(), f"ingest:{repo_id}", lambda s: ingest(s, repo_id, user.id))
    return ingest(session, repo_id, user.id)  # reads real surfaces via the source integration

@router.post("/repositories/{repo_id}/integration")
def link_repo_integration(repo_id: str, body: RepoLink, session: Session = Depends(get_session),
                          _: User = Depends(current_user)):
    return link_integration(session, repo_id, body.integration_id)

@router.post("/repositories/{repo_id}/schedule")
def schedule_repo_ingest(repo_id: str, body: RepoSchedule, session: Session = Depends(get_session),
                         _: User = Depends(current_user)):
    return set_ingest_schedule(session, repo_id, body.interval_hours)

@router.post("/repositories/{repo_id}/claims", status_code=201)
def add_claim(repo_id: str, body: NewClaim, session: Session = Depends(get_session),
              user: User = Depends(current_user)):
    return create_claim(session, repo_id, body.surface, body.text, user.id,
                        has_instruction=body.has_instruction, has_gate=body.has_gate)

@router.delete("/claims/{claim_id}")
def remove_claim(claim_id: str, session: Session = Depends(get_session),
                 _: User = Depends(current_user)):
    delete_claim(session, claim_id)
    return {"status": "deleted"}

# --- governance analysis (poison flags; per-role visibility) ---
@router.get("/governance/analysis")
def get_analysis(session: Session = Depends(get_session), user: User = Depends(current_user)):
    return analyze(session, viewer_rank=role_rank(session, user.role))

# --- per-layer approval workflows (govern changes to governance) ---
