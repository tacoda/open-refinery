from fastapi import APIRouter

from ..deps import *  # noqa: F401,F403
from ..web import *  # noqa: F401,F403

router = APIRouter()


@router.get("/harnesses/catalog")
def harness_catalog(_: User = Depends(current_user)):
    return HARNESS_CATALOG

@router.get("/harnesses")
def get_harnesses(session: Session = Depends(get_session), user: User = Depends(current_user)):
    # platform/admin see all; everyone else sees the agents they own
    scope = None if user.role in ("platform", "admin") else user.id
    return [harness_view(a) for a in list_harnesses(session, owner_id=scope)]

@router.post("/harnesses", status_code=201)
def add_harness(body: NewHarness, request: Request, session: Session = Depends(get_session),
                user: User = Depends(current_user)):
    role = body.role or user.role
    # an agent can't be given more authority than the person registering it
    if role_rank(session, role) > role_rank(session, user.role):
        raise HTTPException(status_code=403, detail="agent role cannot exceed your own")
    agent, token = register_harness(session, body.harness_kind, body.name, user.id, role)
    base = base_url(request)
    return {"harness": harness_view(agent), "token": token,  # token shown once
            "setup": {"OPEN_REFINERY_URL": base, "OPEN_REFINERY_TOKEN": token}}

@router.post("/harnesses/{agent_id}/rotate")
def rotate_a_harness(agent_id: str, session: Session = Depends(get_session),
                     user: User = Depends(current_user)):
    agent = session.get(User, agent_id)
    if agent is None or agent.kind != "agent":
        raise HTTPException(status_code=404, detail="unknown harness")
    if agent.owner_id != user.id and user.role not in ("platform", "admin"):
        raise HTTPException(status_code=403, detail="not your harness")
    return {"token": rotate_harness(session, agent_id)}

@router.delete("/harnesses/{agent_id}")
def remove_harness(agent_id: str, session: Session = Depends(get_session),
                   user: User = Depends(current_user)):
    agent = session.get(User, agent_id)
    if agent is not None and agent.kind == "agent":
        if agent.owner_id != user.id and user.role not in ("platform", "admin"):
            raise HTTPException(status_code=403, detail="not your harness")
        delete_harness(session, agent_id)
    return {"status": "deleted"}

# --- OAuth device flow: the agent gets auth without a human pasting a token ---
@router.post("/agent/device/start")   # called by the agent (unauthenticated)
def device_start_route(body: DeviceStart, request: Request,
                       session: Session = Depends(get_session)):
    grant = device_start(session, body.harness_kind, body.name)
    return {"device_code": grant.device_code, "user_code": grant.user_code,
            "verification_uri": base_url(request) + "/",
            "interval": POLL_INTERVAL_SECONDS, "expires_in": 600}

@router.post("/agent/device/token")   # polled by the agent (unauthenticated)
def device_token_route(body: DeviceToken, session: Session = Depends(get_session)):
    try:
        return {"access_token": device_poll(session, body.device_code), "token_type": "bearer"}
    except DevicePending:
        return {"status": "authorization_pending", "interval": POLL_INTERVAL_SECONDS}
    except DeviceExpired as exc:
        raise HTTPException(status_code=400, detail=str(exc))

@router.post("/agent/device/approve")  # a human authorizes the agent in the UI
def device_approve_route(body: DeviceApprove, session: Session = Depends(get_session),
                         user: User = Depends(current_user)):
    role = body.role or user.role
    grant = device_approve(session, body.user_code, user, role)
    return {"status": "approved", "harness": harness_view(session.get(User, grant.agent_id))}

# --- teams, usage ledger, cost attribution ---
@router.get("/teams")
def get_teams(session: Session = Depends(get_session), _: User = Depends(current_user)):
    return list_teams(session)

@router.post("/teams", status_code=201)
def add_team(body: NewTeam, session: Session = Depends(get_session),
             user: User = Depends(require("platform", "admin"))):
    return create_team(session, body.name, user.id, max_concurrency=body.max_concurrency)

@router.delete("/teams/{team_id}")
def remove_team(team_id: str, session: Session = Depends(get_session),
                _: User = Depends(require("platform", "admin"))):
    delete_team(session, team_id)
    return {"status": "deleted"}

@router.put("/users/{user_id}/team")
def assign_team(user_id: str, body: AssignTeam, session: Session = Depends(get_session),
                _: User = Depends(require("platform", "admin"))):
    u = set_user_team(session, user_id, body.team_id)
    return {"id": u.id, "team_id": u.team_id}

@router.get("/usage")
def get_usage(session: Session = Depends(get_session), _: User = Depends(current_user)):
    return {"by_team": usage_by_team(session), "by_actor": usage_by_actor(session)}

@router.post("/authorize")
def authorize(body: AuthorizeReq, session: Session = Depends(get_session),
              user: User = Depends(current_user)):
    """Pre-action gate for an out-of-process harness: verify the caller's
    identity + declared intent against policy **before** it runs a tool,
    command, or host-egress action. Denials raise 403 and are audited."""
    enforce_policy(session, user.role, body.action, body.resource,
                   audit=SqliteSink(session), actor_id=user.id, subject=body.resource,
                   namespace=body.namespace, intent=body.intent)
    return {"allowed": True, "mode": enforcement_mode(session)}
