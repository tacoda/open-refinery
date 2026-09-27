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
    return {"stages": list_workflow(session, integ_id)}  # for process-from-columns

@router.post("/integrations/{integ_id}/sync")
def sync_integration(integ_id: str, body: SyncRequest, session: Session = Depends(get_session),
                     user: User = Depends(current_user)):
    return sync_tracker(session, integ_id, body.repo_id, body.process_id,
                        user.id, SqliteSink(session))

# --- targets, routing, quotas (Platform layer) ---
@router.post("/targets", status_code=201)
def add_target(body: NewTarget, session: Session = Depends(get_session),
               user: User = Depends(current_user)):
    return create_target(session, body.name, body.kind, body.endpoint, user.id,
                        credential=body.credential, output_schema=body.output_schema,
                        region=body.region, compliance=body.compliance, unit_cost=body.unit_cost)

@router.get("/targets")
def get_targets(session: Session = Depends(get_session), user: User = Depends(current_user)):
    return list_targets(session, owner_id=owner_scope(session, user))

@router.get("/routing-policy")
def get_routing_policy(session: Session = Depends(get_session), _: User = Depends(current_user)):
    return routing_policy(session)

@router.put("/routing-policy")
def set_routing_policy(body: RoutingPolicyBody, session: Session = Depends(get_session),
                       user: User = Depends(sees_operations)):
    set_setting(session, ROUTING_POLICY_KEY, json.dumps(body.model_dump()), user.id)
    return routing_policy(session)

@router.get("/traffic")
def get_traffic(session: Session = Depends(get_session), _: User = Depends(current_user)):
    return traffic_graph(session)

@router.delete("/targets/{target_id}")
def remove_target(target_id: str, session: Session = Depends(get_session),
                  _: User = Depends(current_user)):
    delete_target(session, target_id)
    return {"status": "deleted"}

@router.post("/routes", status_code=201)
def add_route(body: NewRoute, session: Session = Depends(get_session),
              user: User = Depends(current_user)):
    return create_route(session, body.process_id, body.target_id, user.id,
                       step=body.step, priority=body.priority)

@router.get("/routes")
def get_routes(session: Session = Depends(get_session), user: User = Depends(current_user)):
    return list_routes(session, owner_id=owner_scope(session, user))

@router.delete("/routes/{route_id}")
def remove_route(route_id: str, session: Session = Depends(get_session),
                 _: User = Depends(current_user)):
    delete_route(session, route_id)
    return {"status": "deleted"}

@router.post("/quotas", status_code=201)
def add_quota(body: NewQuota, session: Session = Depends(get_session),
              user: User = Depends(current_user)):
    return create_quota(session, body.target_id, body.limit, user.id,
                        window_seconds=body.window_seconds)

@router.get("/quotas")
def get_quotas(session: Session = Depends(get_session), user: User = Depends(current_user)):
    return list_quotas(session, owner_id=owner_scope(session, user))

# --- policy governance + content filtering ---
