"""HTTP layer — FastAPI over the domain.

Auth: an `Authorization: Bearer <token>` header resolves to a `User`; every
mutation is stamped with that user. Scoping: developers see and act on what they
own; platform and admin see everything. User management is admin-only. Each
request gets its own SQLModel `Session`.
"""

from __future__ import annotations

import json
import os
import re
import secrets
from types import SimpleNamespace
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlmodel import Session

from . import oauth
from .approvals import approve as approve_request
from .approvals import list_approvals, reject as reject_request, request_approval
from .escalations import current_overdue
from .attestations import AttestationFailed, AttestationMissing, attest
from .executor import ExecutionError, execute
from .invitations import (
    accept_invitation,
    create_invitation,
    invitation_email,
    list_invitations,
    revoke_invitation,
    send_invitation_email,
)
from .integrations import (
    connectors,
    create_connect_state,
    create_integration,
    delete_integration,
    list_integrations,
    list_issues,
    list_remote_repos,
    list_workflow,
    pop_connect_state,
)
from .integrations import verify as verify_integration
from .metrics import summary
from .approval_workflows import (
    list_proposals,
    list_workflows,
    propose,
    resubmit,
    review,
    set_workflow,
)
from .analysis import analyze
from .debt import health, list_audits, run_audit
from .experiments import (
    analyze_experiment,
    conclude_experiment,
    create_experiment,
    list_experiments,
    record_eval,
)
from .ingest import ingest
from .jobs import enqueue, get_job, list_jobs
from .harnesses import (
    HARNESS_CATALOG,
    DeviceExpired,
    DevicePending,
    POLL_INTERVAL_SECONDS,
    delete_harness,
    device_approve,
    device_poll,
    device_start,
    harness_view,
    list_harnesses,
    register_harness,
    rotate_harness,
)
from .auditors import auditor_view, list_auditors, mint_auditor, resolve_auditor, revoke_auditor
from .evidence import FRAMEWORKS, evidence_pack
from .notifications import CHANNELS, create_rule, delete_rule, list_rules
from .live import HUB
from .logs import append_log, recent_logs
from .webhooks import create_webhook, delete_webhook, list_webhooks
from .governance import landscape
from .packs import disable_pack, enable_pack, list_packs, list_standards, pack_detail
from .postmortem import postmortem
from .rollback import (
    record_rollback_applied,
    rollback_targets,
    rollback_work_item,
    stage_history,
)
from .policies import (
    PolicyDenied,
    create_policy,
    delete_policy,
    enforce as enforce_policy,
    enforcement_mode,
    list_policies,
    list_policy_versions,
    policies_in_effect_at,
    scan_content,
)
from .processes import create_process, list_processes
from .repo_governance import create_claim, delete_claim, list_claims, report as repo_report
from .systems import (
    create_system,
    delete_system,
    list_systems,
    set_system_repos,
    system_coverage,
)
from .repositories import (
    DuplicateRepository,
    create_repository,
    import_or_get,
    link_integration,
    list_repositories,
    set_ingest_schedule,
)
from .settings import delete_setting, get_setting, list_setting_keys, set_setting
from .store import (
    DEFAULT_DATABASE_URL,
    SqliteSink,
    engine_for,
    events_csv,
    export_chain,
    purge_events,
    query_events,
    verify_chain,
)
from .concurrency import ConcurrencyExceeded
from .ledger import traffic_graph, usage_by_actor, usage_by_team
from .teams import create_team, delete_team, list_teams, set_user_team
from .targets import (
    QuotaExceeded,
    create_quota,
    create_route,
    create_target,
    delete_route,
    delete_target,
    ROUTING_POLICY_KEY,
    list_quotas,
    list_routes,
    list_targets,
    routing_policy,
    set_target_credential,
)
from .users import (
    DEFAULT_MIN_APPROVER_ROLE,
    DuplicateUser,
    RoleInUse,
    User,
    authenticate,
    count_users,
    create_session,
    create_user,
    list_roles,
    list_users,
    role_rank,
    rotate_token,
    session_user,
    user_by_email,
    user_by_token,
)
from .work_items import (
    ApprovalRequired,
    InvalidTransition,
    UnknownWorkItem,
    create_work_item,
    list_work_items,
    sync_tracker,
    transition,
)
from .deps import (
    base_url as _base,
    current_user,
    get_session,
    home_url as _home,
    oversight,
    owner_scope,
    provider_creds,
    public_user as _public_user,
    require,
)

_STATIC = Path(__file__).parent / "static"
_SEES_ALL = ("platform", "admin")


# --- request bodies -------------------------------------------------------

class NewUser(BaseModel):
    email: str
    password: str
    role: str


class NewRepo(BaseModel):
    name: str
    git_url: str


class NewProcess(BaseModel):
    name: str
    archetype: str
    stages: list[str]
    transitions: list[tuple[str, str]] | None = None
    initial: str | None = None
    oversight: str = "dark"
    gates: list[str] | None = None
    checks: dict[str, list[str]] | None = None
    min_approver_role: str = DEFAULT_MIN_APPROVER_ROLE
    approval_chain: list[str] | None = None
    approval_sla_hours: int = Field(0, ge=0)  # hours; validated non-negative at the boundary


class NewWorkItem(BaseModel):
    repo_id: str
    process_id: str
    title: str


class NewTeam(BaseModel):
    name: str
    max_concurrency: int = 0    # 0 = unlimited concurrent invokes


class AssignTeam(BaseModel):
    team_id: str | None = None  # null → unassign


class NewAuditor(BaseModel):
    label: str
    ttl_days: int = 14


class NewNotificationRule(BaseModel):
    label: str
    channel: str = "slack"       # slack | email | webhook
    target: str = ""             # slack/webhook URL or email address
    recipe: str = ""             # match this event recipe; "" = any


class NewHarness(BaseModel):
    harness_kind: str            # e.g. claude-code
    name: str
    role: str | None = None      # defaults to the registrant's role; can't exceed it


class DeviceStart(BaseModel):
    harness_kind: str
    name: str


class DeviceToken(BaseModel):
    device_code: str


class DeviceApprove(BaseModel):
    user_code: str
    role: str | None = None


class AuthorizeReq(BaseModel):
    action: str                 # e.g. tool | command | egress | transition | invoke
    resource: str               # tool name / command / host / target kind / step
    namespace: str = ""         # per-namespace whitelist scope (blank = global)
    intent: str = ""            # declared purpose, recorded for verification/audit


class LogLine(BaseModel):
    line: str
    level: str = "info"     # debug | info | warning | error


class RollbackApplied(BaseModel):
    status: str             # applied | failed
    detail: str = ""


class Move(BaseModel):
    to: str
    approve: bool = False  # current user signs off, if the process requires it
    changes: dict | None = None  # PR change set: code/migrations + open {name:{old,new}} maps (config/env/libraries/data/services/secrets/infra/dns/…); refs only, never material


class RequestApproval(BaseModel):
    to: str


class NewInvitation(BaseModel):
    email: str
    role: str
    ttl_days: int = 7


class AcceptInvite(BaseModel):
    token: str
    password: str


class SettingBody(BaseModel):
    key: str
    value: str


class Attest(BaseModel):
    check: str
    passed: bool = True


class Setup(BaseModel):
    email: str
    password: str


class Credentials(BaseModel):
    email: str
    password: str
    code: str | None = None  # TOTP code, required when the account has MFA enabled


class MfaCode(BaseModel):
    code: str


class ScimGroupMap(BaseModel):
    map: dict[str, str] = {}          # IdP group name → role
    default_role: str = "developer"   # role when no group matches


class SsoConfig(BaseModel):  # OIDC SSO; only provided fields are updated (secret write-only)
    issuer: str | None = None
    client_id: str | None = None
    client_secret: str | None = None
    name: str | None = None


class NewIntegration(BaseModel):
    kind: str
    credential: dict[str, str]  # {token} for github/gitlab/linear; {site,email,token} for jira


class SyncRequest(BaseModel):
    repo_id: str
    process_id: str


class NewTarget(BaseModel):
    name: str
    kind: str
    endpoint: str
    credential: dict[str, str] | None = None
    output_schema: dict | None = None
    region: str = ""
    compliance: list[str] = []
    unit_cost: int = 0


class RoutingPolicyBody(BaseModel):
    require_region: str = ""
    require_compliance: list[str] = []
    prefer: str = "priority"        # priority | cost


class NewRoute(BaseModel):
    process_id: str
    target_id: str
    step: str | None = None
    priority: int = 0


class NewQuota(BaseModel):
    target_id: str
    limit: int
    window_seconds: int = 0   # 0 = lifetime cap; >0 = rolling rate window


class NewPolicy(BaseModel):
    effect: str = "allow"
    role: str = "*"
    action: str = "*"
    resource: str = "*"
    strict: bool | None = None   # None → admin-configured default
    kind: str = "rule"
    content: str = ""
    layer: str = "charter"       # factory | harness | charter
    namespace: str = ""          # per-namespace scope (blank = global)
    note: str = ""               # why (recorded in the version history)


class WorkflowBody(BaseModel):
    layer: str
    chain: list[str]


class ProposeChange(BaseModel):
    target_kind: str
    action: str
    payload: dict
    layer: str


class ReviewBody(BaseModel):
    decision: str          # accept | deny | feedback
    note: str = ""


class ResubmitBody(BaseModel):
    payload: dict | None = None


class NewSystem(BaseModel):
    name: str
    kind: str = "service"
    repo_ids: list[str] = []


class SystemRepos(BaseModel):
    repo_ids: list[str]


class RepoLink(BaseModel):
    integration_id: str | None = None


class RepoSchedule(BaseModel):
    interval_hours: int = 0


class NewClaim(BaseModel):
    surface: str
    text: str
    has_instruction: bool = False
    has_gate: bool = False


class NewWebhook(BaseModel):
    url: str
    events: list[str] = []   # recipe filter; [] = all events


class NewExperiment(BaseModel):
    name: str
    hypothesis: str
    change: str
    layer: str


class NewEval(BaseModel):
    phase: str               # before | after
    metric: str
    samples: list[float]
    round: int = 1


class ScanRequest(BaseModel):
    text: str


class ExecuteRequest(BaseModel):
    process_id: str
    payload: str
    step: str | None = None
    work_item_id: str | None = None
    experiment_id: str | None = None   # tag this run as an experiment sample
    arm: str | None = None             # control | treatment


# --- app ------------------------------------------------------------------

# --- role authorization matrix -------------------------------------------
# Central declaration of who may do what, enforced by middleware (returns 403).
# First matching rule wins; anything unmatched is allowed (reads stay open for
# oversight — dev lists are owner-scoped in their handlers). GET of operational
# data is intentionally open so platform/admin can oversee; only *mutations* and
# oversight/config surfaces are role-gated. Roles:
#   developer — operates dev concerns   platform — platform concerns + authoring
#   admin — oversight only
_DEV = {"developer"}
_DEV_PLAT = {"developer", "platform"}
_PLAT = {"platform"}
_PLAT_ADMIN = {"platform", "admin"}
_OVERSIGHT = {"platform", "admin", "auditor"}  # read-only oversight incl. auditors
_AUTHZ_RULES: list[tuple[set[str], re.Pattern, set[str]]] = [
    # developer operates the dev chain (writes only; reads stay open for oversight)
    ({"POST", "PUT", "DELETE"}, re.compile(r"^/integrations(/|$)"), _DEV),
    ({"POST", "PUT", "DELETE"}, re.compile(r"^/repositories(/|$)"), _DEV),
    ({"POST", "PUT", "DELETE"}, re.compile(r"^/processes(/|$)"), _DEV),
    ({"POST", "PUT", "DELETE"}, re.compile(r"^/work-items(/|$)"), _DEV),
    # approving gated moves: developer or platform
    ({"POST"}, re.compile(r"^/approvals/"), _DEV_PLAT),
    # registering agents / enabling packs: developer or platform
    ({"POST", "PUT", "DELETE"}, re.compile(r"^/harnesses(/|$)"), _DEV_PLAT),
    ({"POST"}, re.compile(r"^/packs/[^/]+/(enable|disable)$"), _DEV_PLAT),
    # platform config + governance authoring: platform only
    ({"POST", "PUT", "DELETE"}, re.compile(r"^/(targets|routes|quotas|systems|policies|proposals|approval-workflows)(/|$)"), _PLAT),
    ({"PUT"}, re.compile(r"^/routing-policy$"), _PLAT),
    # teams + cost: platform or admin
    ({"POST", "PUT", "DELETE"}, re.compile(r"^/teams(/|$)"), _PLAT_ADMIN),
    ({"PUT"}, re.compile(r"^/users/[^/]+/team$"), _PLAT_ADMIN),
    # oversight reads — platform, admin, and read-only auditors
    ({"GET"}, re.compile(r"^/(usage|traffic|experiments|events|governance|evidence)(/|$)"), _OVERSIGHT),
    ({"GET"}, re.compile(r"^/audits(/|$)"), _OVERSIGHT),
    ({"GET"}, re.compile(r"^/audit/(verify|export)"), _OVERSIGHT),
    ({"GET"}, re.compile(r"^/policies/(history|at)"), _OVERSIGHT),
    # running an audit / purge / config are platform-admin (not auditors)
    ({"POST"}, re.compile(r"^/audits(/|$)"), _PLAT_ADMIN),
    ({"POST"}, re.compile(r"^/audit/purge"), _PLAT_ADMIN),
    ({"GET", "PUT", "DELETE"}, re.compile(r"^/settings(/|$)"), _PLAT_ADMIN),
    # minting/revoking auditor grants: admin only
    ({"POST", "DELETE"}, re.compile(r"^/auditor-grants(/|$)"), {"admin"}),
]


def _match_authz_rule(method: str, path: str):
    for methods, pattern, allowed in _AUTHZ_RULES:
        if method in methods and pattern.match(path):
            return allowed
    return None


def _principal_role(session, token: str) -> str | None:
    """The role of whoever holds this token: a user, a time-boxed auditor, or None."""
    if not token:
        return None
    user = user_by_token(session, token) or session_user(session, token)
    if user is not None:
        return user.role
    return "auditor" if resolve_auditor(session, token) else None


async def _enforce_roles(request, call_next):
    """Central role authorization — 403 if the caller's role can't do this."""
    allowed = _match_authz_rule(request.method, request.url.path)
    if allowed is not None:
        token = (request.headers.get("authorization") or "").removeprefix("Bearer ").strip()
        with Session(request.app.state.engine) as s:
            role = _principal_role(s, token)
        if role is not None and role not in allowed:  # authenticated but out of scope
            return JSONResponse({"detail": f"{role} is not authorized for this action"},
                                status_code=403)
    return await call_next(request)


async def _live_ws(websocket: WebSocket, token: str = ""):
    with Session(websocket.app.state.engine) as s:  # bearer via query param (WS can't set headers)
        user = (user_by_token(s, token) or session_user(s, token)) if token else None
    if user is None:
        await websocket.close(code=1008)  # policy violation / unauthorized
        return
    await websocket.accept()
    q = HUB.subscribe()
    try:
        while True:
            await websocket.send_json(await q.get())
    except WebSocketDisconnect:
        pass
    finally:
        HUB.unsubscribe(q)


_EXC_CODES = (
    (DuplicateUser, 409),
    (DuplicateRepository, 409),
    (InvalidTransition, 409),
    (ApprovalRequired, 409),
    (AttestationMissing, 409),
    (AttestationFailed, 409),
    (QuotaExceeded, 429),
    (ConcurrencyExceeded, 429),
    (DeviceExpired, 400),
    (PolicyDenied, 403),
    (RoleInUse, 409),
    (ExecutionError, 502),
    (UnknownWorkItem, 404),
    (ValueError, 400),
)


def _register_exception_handlers(app: FastAPI) -> None:
    for exc, code in _EXC_CODES:
        app.add_exception_handler(
            exc, lambda _req, e, code=code: JSONResponse({"detail": str(e)}, status_code=code))


def _include_routers(app: FastAPI) -> None:
    from .routers import (core, governance, harness, ops, org, policy, routing, scim,
                          systems, workitem)
    for mod in (core, ops, systems, governance, org, harness, workitem, routing, policy, scim):
        app.include_router(mod.router)


def create_app(session: Session | None = None, database_url: str = DEFAULT_DATABASE_URL) -> FastAPI:
    # Self-host API docs at /api-docs (assets bundled at build time — no CDN).
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _lifespan(_app):
        import asyncio
        HUB.bind_loop(asyncio.get_running_loop())  # enable cross-thread publish → WS
        yield

    app = FastAPI(title="open-refinery", docs_url=None, redoc_url=None, lifespan=_lifespan)
    engine = session.get_bind() if session is not None else engine_for(database_url)
    app.state.engine = engine

    # Declare Bearer auth in the schema so Swagger UI's Authorize + "Try it out"
    # can call the live API with a token. (Auth itself is enforced per-route.)
    def _openapi():
        if app.openapi_schema:
            return app.openapi_schema
        from fastapi.openapi.utils import get_openapi
        schema = get_openapi(title="open-refinery", version="1.0", routes=app.routes,
                             description="Self-hosted governance platform API. "
                                         "Click **Authorize** and paste your token to try calls here.")
        schema.setdefault("components", {})["securitySchemes"] = {
            "bearerAuth": {"type": "http", "scheme": "bearer"}}
        schema["security"] = [{"bearerAuth": []}]
        app.openapi_schema = schema
        return schema
    app.openapi = _openapi

    # Dev only: the Vite dev server (localhost) calls the API cross-origin.
    # In production the SPA is served same-origin from _STATIC, so this is a no-op.
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"http://localhost(:\d+)?",
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.middleware("http")(_enforce_roles)
    app.add_api_websocket_route("/ws", _live_ws)
    _register_exception_handlers(app)
    _include_routers(app)

    if (_STATIC / "index.html").exists():
        app.mount("/", StaticFiles(directory=_STATIC, html=True), name="spa")

    return app


def create_app_from_env() -> FastAPI:
    app = create_app(database_url=os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL))
    from .scheduler import start_scheduler
    start_scheduler(app.state.engine)  # auto-ingest loop (serve path only, not tests)
    return app
