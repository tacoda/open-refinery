"""Proposals, approval workflows, and the standards packs.

These lost their routes in 2.15.0 — they shared a router with the governance
landscape view, which was removed, and the suite did not notice because its
tests drive the modules directly. Proposals are one of the four pillars, so
that was a regression rather than a trim.

**Anyone may propose; only the owner of a layer may approve.** That asymmetry is
the whole point: `propose:*` is wide and `approve:*` is narrow, which is what
lets a developer put a harness change forward without being able to sign it.
"""

from fastapi import APIRouter

from .. import authority
from ..deps import *  # noqa: F401,F403
from ..web import *  # noqa: F401,F403

router = APIRouter()


# --- proposals --------------------------------------------------------------

@router.post("/proposals", status_code=201)
def add_proposal(body: ProposeChange, session: Session = Depends(get_session),
                 user: User = Depends(current_user)):
    """Put a change forward. Needs `propose:<layer>` — deliberately wide."""
    if body.layer in authority.LAYERS and not authority.may_propose(user, body.layer):
        raise HTTPException(status_code=403,
                            detail=f"you do not hold propose:{body.layer}")
    return propose(session, body.target_kind, body.action, body.payload,
                   body.layer, user.id)


@router.get("/proposals")
def get_proposals(status: str | None = None, session: Session = Depends(get_session),
                  _: User = Depends(current_user)):
    return list_proposals(session, status=status)


@router.post("/proposals/{proposal_id}/review")
def review_proposal(proposal_id: str, body: ReviewBody,
                    session: Session = Depends(get_session),
                    user: User = Depends(current_user)):
    """Sign, refuse, or send back. `review()` enforces the chain and the
    distinct-signer-per-slot rule."""
    return review(session, proposal_id, user.id, body.decision,
                  SqliteSink(session), note=body.note)


@router.post("/proposals/{proposal_id}/resubmit")
def resubmit_proposal(proposal_id: str, body: ResubmitBody,
                      session: Session = Depends(get_session),
                      user: User = Depends(current_user)):
    return resubmit(session, proposal_id, user.id, payload=body.payload)


# --- who signs what ---------------------------------------------------------

@router.get("/approval-workflows")
def get_workflows(session: Session = Depends(get_session),
                  _: User = Depends(current_user)):
    return list_workflows(session)


@router.post("/approval-workflows", status_code=201)
def put_workflow(body: WorkflowBody, session: Session = Depends(get_session),
                 user: User = Depends(manages_users)):
    """Configuring *who* signs a governance change is meta-governance, so it
    sits with user management rather than with either layer's owner."""
    return set_workflow(session, body.layer, body.chain, user.id)


# --- packs: the standards a team starts from --------------------------------

@router.get("/packs")
def get_packs(session: Session = Depends(get_session), _: User = Depends(current_user)):
    return list_packs(session)


@router.get("/packs/{key}")
def get_pack(key: str, session: Session = Depends(get_session),
             _: User = Depends(current_user)):
    detail = pack_detail(session, key)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"unknown pack: {key}")
    return detail


@router.post("/packs/{key}/enable")
def enable_a_pack(key: str, session: Session = Depends(get_session),
                  user: User = Depends(approves("charter"))):
    """A pack seeds standards the harness reads — a charter change."""
    return enable_pack(session, key, user)


@router.post("/packs/{key}/disable")
def disable_a_pack(key: str, session: Session = Depends(get_session),
                   user: User = Depends(approves("charter"))):
    return disable_pack(session, key, user)


@router.get("/standards")
def get_standards(pack: str | None = None, session: Session = Depends(get_session),
                  _: User = Depends(current_user)):
    return list_standards(session, pack=pack)
