from fastapi import APIRouter

from ..deps import *  # noqa: F401,F403
from ..web import *  # noqa: F401,F403

router = APIRouter()


@router.get("/connectors")
def get_connectors(_: User = Depends(current_user)):
    return connectors()  # catalog: kind + label + capabilities + credential fields

@router.post("/integrations", status_code=201)
def add_integration(body: NewIntegration, session: Session = Depends(get_session),
                    user: User = Depends(current_user)):
    return create_integration(session, body.kind, body.credential, user.id)

@router.get("/integrations")
def get_integrations(session: Session = Depends(get_session), user: User = Depends(current_user)):
    return list_integrations(session, owner_id=owner_scope(session, user))

@router.delete("/integrations/{integ_id}")
def remove_integration(integ_id: str, session: Session = Depends(get_session),
                       _: User = Depends(current_user)):
    delete_integration(session, integ_id)
    return {"status": "deleted"}

@router.post("/integrations/{integ_id}/verify")
def check_integration(integ_id: str, session: Session = Depends(get_session),
                      _: User = Depends(current_user)):
    return verify_integration(session, integ_id)

@router.get("/integrations/{integ_id}/repos")
def integration_repos(integ_id: str, session: Session = Depends(get_session),
                      _: User = Depends(current_user)):
    return list_remote_repos(session, integ_id)

@router.get("/integrations/{integ_id}/issues")
def integration_issues(integ_id: str, session: Session = Depends(get_session),
                       _: User = Depends(current_user)):
    return list_issues(session, integ_id)

@router.get("/integrations/{integ_id}/workflow")
def integration_workflow(integ_id: str, session: Session = Depends(get_session),
                         _: User = Depends(current_user)):
    return {"stages": list_workflow(session, integ_id)}  # the tracker's own columns

@router.post("/integrations/{integ_id}/sync")
def sync_integration(integ_id: str, body: SyncRequest, session: Session = Depends(get_session),
                     user: User = Depends(may_run)):
    return sync_tracker(session, integ_id, body.repo_id,
                        user.id, SqliteSink(session), autostart=body.autostart)

# --- policy governance + content filtering ---
