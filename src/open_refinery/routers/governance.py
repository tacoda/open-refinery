from fastapi import APIRouter

from ..deps import *  # noqa: F401,F403
from ..web import *  # noqa: F401,F403

router = APIRouter()


@router.get("/approval-workflows")
def get_workflows(session: Session = Depends(get_session), _: User = Depends(current_user)):
    return list_workflows(session)

@router.post("/approval-workflows", status_code=201)
def put_workflow(body: WorkflowBody, session: Session = Depends(get_session),
                 user: User = Depends(require("admin"))):
    return set_workflow(session, body.layer, body.chain, user.id)

@router.post("/proposals", status_code=201)
def add_proposal(body: ProposeChange, session: Session = Depends(get_session),
                 user: User = Depends(current_user)):
    return propose(session, body.target_kind, body.action, body.payload, body.layer, user.id)

@router.get("/proposals")
def get_proposals(status: str | None = None, session: Session = Depends(get_session),
                  _: User = Depends(current_user)):
    return list_proposals(session, status=status)

@router.post("/proposals/{proposal_id}/review")
def review_proposal(proposal_id: str, body: ReviewBody,
                    session: Session = Depends(get_session), user: User = Depends(current_user)):
    return review(session, proposal_id, user.id, body.decision, SqliteSink(session), note=body.note)

@router.post("/proposals/{proposal_id}/resubmit")
def resubmit_proposal(proposal_id: str, body: ResubmitBody,
                      session: Session = Depends(get_session), user: User = Depends(current_user)):
    return resubmit(session, proposal_id, user.id, payload=body.payload)

# --- packs (opt-in topic bundles; enable/disable role-gated) ---
@router.get("/packs")
def get_packs(session: Session = Depends(get_session), _: User = Depends(current_user)):
    return list_packs(session)

@router.get("/packs/{key}")
def get_pack(key: str, session: Session = Depends(get_session), _: User = Depends(current_user)):
    detail = pack_detail(session, key)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"unknown pack: {key}")
    return detail

@router.post("/packs/{key}/enable")
def enable_a_pack(key: str, session: Session = Depends(get_session),
                  user: User = Depends(current_user)):
    return enable_pack(session, key, user)  # PolicyDenied → 403 if role too low

@router.post("/packs/{key}/disable")
def disable_a_pack(key: str, session: Session = Depends(get_session),
                   user: User = Depends(current_user)):
    return disable_pack(session, key, user)

@router.get("/standards")
def get_standards(pack: str | None = None, session: Session = Depends(get_session),
                  _: User = Depends(current_user)):
    return list_standards(session, pack=pack)

# --- invitations (role-gated; invitee sets their own password) ---
