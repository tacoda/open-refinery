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
from pydantic import BaseModel
from sqlmodel import Session

from . import oauth
from .approvals import approve as approve_request
from .approvals import list_approvals, reject as reject_request, request_approval
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

    def get_session():
        with Session(engine) as s:
            yield s

    @app.middleware("http")
    async def enforce_roles(request, call_next):
        """Central role authorization — 403 if the caller's role can't do this."""
        method, path = request.method, request.url.path
        rule = next((r for r in _AUTHZ_RULES if method in r[0] and r[1].match(path)), None)
        if rule is not None:
            auth = request.headers.get("authorization") or ""
            token = auth.removeprefix("Bearer ").strip()
            with Session(engine) as s:
                user = (user_by_token(s, token) or session_user(s, token)) if token else None
                role = user.role if user else None
                if role is None and token and resolve_auditor(s, token):
                    role = "auditor"  # read-only external principal
            if role is not None and role not in rule[2]:  # authenticated but out of scope
                return JSONResponse({"detail": f"{role} is not authorized for this action"},
                                    status_code=403)
        return await call_next(request)

    @app.websocket("/ws")
    async def live_ws(websocket: WebSocket, token: str = ""):
        with Session(engine) as s:  # bearer token via query param (browsers can't set WS headers)
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

    def current_user(
        session: Session = Depends(get_session),
        authorization: str | None = Header(default=None),
    ) -> User:
        token = (authorization or "").removeprefix("Bearer ").strip()
        user = (user_by_token(session, token) or session_user(session, token)) if token else None
        if user is None and token:  # a time-boxed auditor grant → read-only principal
            grant = resolve_auditor(session, token)
            if grant is not None:
                return SimpleNamespace(id=grant.id, email=grant.label, role="auditor",
                                       team_id=None, kind="auditor", owner_id=None,
                                       created_at=grant.created_at)
        if user is None:
            raise HTTPException(status_code=401, detail="invalid or missing token")
        return user

    def require(*roles: str):
        def dep(user: User = Depends(current_user)) -> User:
            if user.role not in roles:
                raise HTTPException(status_code=403, detail="forbidden for this role")
            return user
        return dep

    oversight = require("platform", "admin", "auditor")  # read-only oversight + auditors

    def _public_user(user: User) -> dict:
        # safe projection — pw_hash / pw_salt / token_hash must never cross the wire
        return {"id": user.id, "email": user.email, "role": user.role,
                "team_id": user.team_id, "created_at": user.created_at}

    def owner_scope(user: User) -> str | None:
        """None = see everything (platform/admin); else scope to the user's own."""
        return None if user.role in _SEES_ALL else user.id

    for exc, code in (
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
    ):
        app.add_exception_handler(
            exc,
            lambda _req, e, code=code: JSONResponse({"detail": str(e)}, status_code=code),
        )

    def provider_creds(session: Session, kind: str) -> dict | None:
        """OAuth client creds: DB settings first, then env fallback."""
        p = oauth.PROVIDERS.get(kind)
        if not p:
            return None
        cid = get_setting(session, f"{kind}.client_id") or os.environ.get(p["id_env"])
        csec = get_setting(session, f"{kind}.client_secret") or os.environ.get(p["secret_env"])
        return {"client_id": cid, "client_secret": csec} if cid and csec else None

    def _base(request: Request) -> str:
        return os.environ.get("APP_BASE_URL", str(request.base_url)).rstrip("/")

    def _home(request: Request) -> str:
        return _base(request) + "/"

    # --- routes ---
    @app.get("/health")
    def healthcheck():  # not `health` — that name is the imported debt.health scorer
        return {"status": "ok"}

    # --- first-run onboarding: the first admin runs the setup wizard; once
    # complete, later users inherit the configured org and skip it. ---
    @app.get("/onboarding")
    def onboarding_status(session: Session = Depends(get_session), _: User = Depends(current_user)):
        return {"onboarded": (get_setting(session, "org.onboarded") or "").lower() == "true"}

    @app.post("/onboarding/complete")
    def onboarding_complete(session: Session = Depends(get_session),
                            user: User = Depends(require("platform", "admin"))):
        set_setting(session, "org.onboarded", "true", user.id)
        return {"onboarded": True}

    @app.get("/api-docs", include_in_schema=False)
    def api_docs():
        # self-hosted Swagger UI; assets copied into static/api-docs-assets at build
        return get_swagger_ui_html(
            openapi_url="/openapi.json", title="open-refinery API",
            swagger_js_url="/api-docs-assets/swagger-ui-bundle.js",
            swagger_css_url="/api-docs-assets/swagger-ui.css")

    @app.get("/setup/status")
    def setup_status(session: Session = Depends(get_session)):
        return {"needs_setup": count_users(session) == 0}

    @app.post("/setup", status_code=201)
    def setup(body: Setup, session: Session = Depends(get_session)):
        if count_users(session) > 0:
            raise HTTPException(status_code=409, detail="already set up")
        user, token = create_user(session, body.email, body.password, "admin")
        return {"user": user, "token": token}

    @app.get("/me")
    def me(user: User = Depends(current_user)):
        return _public_user(user)  # never expose pw_hash / pw_salt / token_hash

    @app.post("/me/token/rotate")
    def rotate_my_token(session: Session = Depends(get_session), user: User = Depends(current_user)):
        return {"token": rotate_token(session, user.id)}  # old API token invalidated

    # --- roles (admin-configurable authority ladder) ---
    @app.get("/roles")
    def get_roles(session: Session = Depends(get_session), _: User = Depends(current_user)):
        return list_roles(session)  # fixed ladder: developer < platform < admin

    # Roles are a fixed three-tier ladder (developer / platform / admin) — arbitrary
    # roles proved confusing, so creating/deleting them is intentionally not exposed.

    # --- governance landscape (admin read view) ---
    @app.get("/governance")
    def get_governance(session: Session = Depends(get_session), _: User = Depends(oversight)):
        return landscape(session)

    # --- evals & experiments (test if a change's effect is real) ---
    @app.get("/experiments")
    def get_experiments(layer: str | None = None, session: Session = Depends(get_session),
                        _: User = Depends(current_user)):
        return list_experiments(session, layer=layer)

    @app.post("/experiments", status_code=201)
    def add_experiment(body: NewExperiment, session: Session = Depends(get_session),
                       user: User = Depends(current_user)):
        return create_experiment(session, body.name, body.hypothesis, body.change, body.layer, user.id)

    @app.post("/experiments/{experiment_id}/evals", status_code=201)
    def add_eval(experiment_id: str, body: NewEval, session: Session = Depends(get_session),
                 _: User = Depends(current_user)):
        return record_eval(session, experiment_id, body.phase, body.metric, body.samples,
                           round=body.round)

    @app.get("/experiments/{experiment_id}/analysis")
    def get_analysis(experiment_id: str, metric: str | None = None, round: int | None = None,
                     session: Session = Depends(get_session), _: User = Depends(current_user)):
        return analyze_experiment(session, experiment_id, metric=metric, round=round)

    @app.post("/experiments/{experiment_id}/conclude")
    def end_experiment(experiment_id: str, session: Session = Depends(get_session),
                       _: User = Depends(current_user)):
        return conclude_experiment(session, experiment_id)

    # --- webhooks (fan audit events out; HMAC-signed) ---
    @app.get("/webhooks")
    def get_webhooks(session: Session = Depends(get_session),
                     _: User = Depends(require("platform", "admin"))):
        return list_webhooks(session)  # secret is encrypted, never returned

    @app.post("/webhooks", status_code=201)
    def add_webhook(body: NewWebhook, session: Session = Depends(get_session),
                    user: User = Depends(require("platform", "admin"))):
        wh, secret = create_webhook(session, body.url, body.events, user.id)
        return {"webhook": wh, "secret": secret}  # secret shown once

    @app.delete("/webhooks/{webhook_id}")
    def remove_webhook(webhook_id: str, session: Session = Depends(get_session),
                       _: User = Depends(require("platform", "admin"))):
        delete_webhook(session, webhook_id)
        return {"status": "deleted"}

    # --- debt audits & health ---
    @app.get("/health/areas")
    def get_area_health(session: Session = Depends(get_session), _: User = Depends(current_user)):
        return health(session)  # live factory/harness/charter scores

    @app.get("/audits")
    def get_audits(area: str | None = None, session: Session = Depends(get_session),
                   _: User = Depends(current_user)):
        return list_audits(session, area=area)

    @app.post("/audits/run", status_code=201)
    def run_audits(area: str = "all", background: bool = False,
                   session: Session = Depends(get_session), user: User = Depends(current_user)):
        if background:  # run off the request path; poll /jobs/{id}
            return enqueue(session, engine, f"audit:{area}",
                           lambda s: {"audits": [a.id for a in run_audit(s, area, user.id)]})
        return run_audit(session, area, user.id)

    # --- background jobs ---
    @app.get("/jobs")
    def get_jobs(session: Session = Depends(get_session), _: User = Depends(current_user)):
        return list_jobs(session)

    @app.get("/jobs/{job_id}")
    def get_one_job(job_id: str, session: Session = Depends(get_session), _: User = Depends(current_user)):
        job = get_job(session, job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="unknown job")
        return job

    # --- systems (compose repos into services) ---
    @app.get("/systems")
    def get_systems(session: Session = Depends(get_session), _: User = Depends(current_user)):
        return list_systems(session)

    @app.post("/systems", status_code=201)
    def add_system(body: NewSystem, session: Session = Depends(get_session),
                   user: User = Depends(require("platform", "admin"))):
        return create_system(session, body.name, body.kind, user.id, repo_ids=body.repo_ids)

    @app.post("/systems/{system_id}/repos")
    def set_repos(system_id: str, body: SystemRepos, session: Session = Depends(get_session),
                  _: User = Depends(require("platform", "admin"))):
        return set_system_repos(session, system_id, body.repo_ids)

    @app.get("/systems/{system_id}/coverage")
    def sys_coverage(system_id: str, session: Session = Depends(get_session),
                     _: User = Depends(current_user)):
        return system_coverage(session, system_id)

    @app.delete("/systems/{system_id}")
    def remove_system(system_id: str, session: Session = Depends(get_session),
                      _: User = Depends(require("platform", "admin"))):
        delete_system(session, system_id)
        return {"status": "deleted"}

    # --- repo-level drift & coverage ---
    @app.get("/repositories/{repo_id}/coverage")
    def get_coverage(repo_id: str, session: Session = Depends(get_session),
                     _: User = Depends(current_user)):
        return repo_report(session, repo_id)

    @app.get("/repositories/{repo_id}/claims")
    def get_claims(repo_id: str, session: Session = Depends(get_session),
                   _: User = Depends(current_user)):
        return list_claims(session, repo_id)

    @app.post("/repositories/{repo_id}/ingest")
    def ingest_repo(repo_id: str, background: bool = False,
                    session: Session = Depends(get_session), user: User = Depends(current_user)):
        if background:  # network read off the request path; poll /jobs/{id}
            return enqueue(session, engine, f"ingest:{repo_id}", lambda s: ingest(s, repo_id, user.id))
        return ingest(session, repo_id, user.id)  # reads real surfaces via the source integration

    @app.post("/repositories/{repo_id}/integration")
    def link_repo_integration(repo_id: str, body: RepoLink, session: Session = Depends(get_session),
                              _: User = Depends(current_user)):
        return link_integration(session, repo_id, body.integration_id)

    @app.post("/repositories/{repo_id}/schedule")
    def schedule_repo_ingest(repo_id: str, body: RepoSchedule, session: Session = Depends(get_session),
                             _: User = Depends(current_user)):
        return set_ingest_schedule(session, repo_id, body.interval_hours)

    @app.post("/repositories/{repo_id}/claims", status_code=201)
    def add_claim(repo_id: str, body: NewClaim, session: Session = Depends(get_session),
                  user: User = Depends(current_user)):
        return create_claim(session, repo_id, body.surface, body.text, user.id,
                            has_instruction=body.has_instruction, has_gate=body.has_gate)

    @app.delete("/claims/{claim_id}")
    def remove_claim(claim_id: str, session: Session = Depends(get_session),
                     _: User = Depends(current_user)):
        delete_claim(session, claim_id)
        return {"status": "deleted"}

    # --- governance analysis (poison flags; per-role visibility) ---
    @app.get("/governance/analysis")
    def get_analysis(session: Session = Depends(get_session), user: User = Depends(current_user)):
        return analyze(session, viewer_rank=role_rank(session, user.role))

    # --- per-layer approval workflows (govern changes to governance) ---
    @app.get("/approval-workflows")
    def get_workflows(session: Session = Depends(get_session), _: User = Depends(current_user)):
        return list_workflows(session)

    @app.post("/approval-workflows", status_code=201)
    def put_workflow(body: WorkflowBody, session: Session = Depends(get_session),
                     user: User = Depends(require("admin"))):
        return set_workflow(session, body.layer, body.chain, user.id)

    @app.post("/proposals", status_code=201)
    def add_proposal(body: ProposeChange, session: Session = Depends(get_session),
                     user: User = Depends(current_user)):
        return propose(session, body.target_kind, body.action, body.payload, body.layer, user.id)

    @app.get("/proposals")
    def get_proposals(status: str | None = None, session: Session = Depends(get_session),
                      _: User = Depends(current_user)):
        return list_proposals(session, status=status)

    @app.post("/proposals/{proposal_id}/review")
    def review_proposal(proposal_id: str, body: ReviewBody,
                        session: Session = Depends(get_session), user: User = Depends(current_user)):
        return review(session, proposal_id, user.id, body.decision, SqliteSink(session), note=body.note)

    @app.post("/proposals/{proposal_id}/resubmit")
    def resubmit_proposal(proposal_id: str, body: ResubmitBody,
                          session: Session = Depends(get_session), user: User = Depends(current_user)):
        return resubmit(session, proposal_id, user.id, payload=body.payload)

    # --- packs (opt-in topic bundles; enable/disable role-gated) ---
    @app.get("/packs")
    def get_packs(session: Session = Depends(get_session), _: User = Depends(current_user)):
        return list_packs(session)

    @app.get("/packs/{key}")
    def get_pack(key: str, session: Session = Depends(get_session), _: User = Depends(current_user)):
        detail = pack_detail(session, key)
        if detail is None:
            raise HTTPException(status_code=404, detail=f"unknown pack: {key}")
        return detail

    @app.post("/packs/{key}/enable")
    def enable_a_pack(key: str, session: Session = Depends(get_session),
                      user: User = Depends(current_user)):
        return enable_pack(session, key, user)  # PolicyDenied → 403 if role too low

    @app.post("/packs/{key}/disable")
    def disable_a_pack(key: str, session: Session = Depends(get_session),
                       user: User = Depends(current_user)):
        return disable_pack(session, key, user)

    @app.get("/standards")
    def get_standards(pack: str | None = None, session: Session = Depends(get_session),
                      _: User = Depends(current_user)):
        return list_standards(session, pack=pack)

    # --- invitations (role-gated; invitee sets their own password) ---
    @app.post("/invitations", status_code=201)
    def invite_user(body: NewInvitation, request: Request,
                    session: Session = Depends(get_session),
                    user: User = Depends(require("senior", "platform", "admin"))):
        inv, token = create_invitation(session, body.email, body.role, user.id,
                                       ttl_days=body.ttl_days)
        accept_url = f"{_home(request)}#invite={token}"
        try:
            send_invitation_email(body.email, accept_url)
        except Exception:  # email may be unconfigured; the link is still returned
            pass
        return {"invitation": inv, "accept_url": accept_url}

    @app.get("/invitations")
    def get_invitations(session: Session = Depends(get_session),
                        _: User = Depends(require("senior", "platform", "admin"))):
        return list_invitations(session, status="pending")

    @app.post("/invitations/{invitation_id}/revoke")
    def revoke_invite(invitation_id: str, session: Session = Depends(get_session),
                      _: User = Depends(require("senior", "platform", "admin"))):
        revoke_invitation(session, invitation_id)
        return {"status": "revoked"}

    @app.get("/invitations/lookup")
    def lookup_invite(token: str, session: Session = Depends(get_session)):
        return {"email": invitation_email(session, token)}

    @app.post("/invitations/accept")
    def accept_invite(body: AcceptInvite, session: Session = Depends(get_session)):
        user, token = accept_invitation(session, body.token, body.password)
        return {"token": token, "user": user}

    @app.post("/users", status_code=201)
    def add_user(body: NewUser, session: Session = Depends(get_session),
                 _: User = Depends(require("admin"))):
        user, token = create_user(session, body.email, body.password, body.role)
        return {"user": user, "token": token}  # token shown once

    @app.post("/repositories", status_code=201)
    def add_repo(body: NewRepo, session: Session = Depends(get_session),
                 user: User = Depends(current_user)):
        return create_repository(session, body.name, body.git_url, user.id)

    @app.get("/repositories")
    def get_repos(session: Session = Depends(get_session), user: User = Depends(current_user)):
        return list_repositories(session, owner_id=owner_scope(user))

    @app.post("/repositories/import", status_code=201)
    def import_repo(body: NewRepo, session: Session = Depends(get_session),
                    user: User = Depends(current_user)):
        return import_or_get(session, body.name, body.git_url, user.id)

    @app.post("/processes", status_code=201)
    def add_process(body: NewProcess, session: Session = Depends(get_session),
                    user: User = Depends(current_user)):
        return create_process(
            session, body.name, body.archetype, body.stages, user.id,
            transitions=body.transitions, initial=body.initial,
            oversight=body.oversight, gates=body.gates, checks=body.checks,
            min_approver_role=body.min_approver_role, approval_chain=body.approval_chain,
        )

    @app.get("/processes")
    def get_processes(session: Session = Depends(get_session), user: User = Depends(current_user)):
        return list_processes(session, owner_id=owner_scope(user))

    @app.post("/work-items", status_code=201)
    def add_work_item(body: NewWorkItem, session: Session = Depends(get_session),
                      user: User = Depends(current_user)):
        return create_work_item(session, body.repo_id, body.process_id, body.title, user.id)

    @app.get("/work-items")
    def get_work_items(session: Session = Depends(get_session), user: User = Depends(current_user),
                       repo_id: str | None = None):
        return list_work_items(session, owner_id=owner_scope(user), repo_id=repo_id)

    @app.get("/work-items/{item_id}/postmortem")
    def work_item_postmortem(item_id: str, session: Session = Depends(get_session),
                             _: User = Depends(current_user)):
        return postmortem(session, item_id)

    @app.get("/work-items/{item_id}/history")
    def work_item_history(item_id: str, session: Session = Depends(get_session),
                          _: User = Depends(current_user)):
        return {"history": stage_history(session, item_id),
                "rollback_targets": rollback_targets(session, item_id)}

    @app.post("/work-items/{item_id}/rollback")
    def rollback_item(item_id: str, body: Move, session: Session = Depends(get_session),
                      user: User = Depends(current_user)):
        return rollback_work_item(session, item_id, body.to, user.id, SqliteSink(session))

    @app.post("/work-items/{item_id}/rollback/applied")
    def rollback_applied(item_id: str, body: RollbackApplied,
                         session: Session = Depends(get_session),
                         user: User = Depends(current_user)):
        return record_rollback_applied(session, item_id, user.id, body.status,
                                       SqliteSink(session), detail=body.detail)

    # --- live run logs (ephemeral, streamed over the WS hub) ---
    @app.get("/work-items/{item_id}/logs")
    def get_logs(item_id: str, _: User = Depends(current_user)):
        return recent_logs(item_id)

    @app.post("/work-items/{item_id}/logs", status_code=201)
    def post_log(item_id: str, body: LogLine, _: User = Depends(current_user)):
        return append_log(item_id, body.line, body.level)

    @app.get("/users")
    def get_users(session: Session = Depends(get_session),
                  _: User = Depends(require("platform", "admin"))):
        return [_public_user(u) for u in list_users(session)]  # projected, no hashes

    # --- harness identities: auth for coding agents (Claude Code, …) ---
    @app.get("/harnesses/catalog")
    def harness_catalog(_: User = Depends(current_user)):
        return HARNESS_CATALOG

    @app.get("/harnesses")
    def get_harnesses(session: Session = Depends(get_session), user: User = Depends(current_user)):
        # platform/admin see all; everyone else sees the agents they own
        scope = None if user.role in ("platform", "admin") else user.id
        return [harness_view(a) for a in list_harnesses(session, owner_id=scope)]

    @app.post("/harnesses", status_code=201)
    def add_harness(body: NewHarness, request: Request, session: Session = Depends(get_session),
                    user: User = Depends(current_user)):
        role = body.role or user.role
        # an agent can't be given more authority than the person registering it
        if role_rank(session, role) > role_rank(session, user.role):
            raise HTTPException(status_code=403, detail="agent role cannot exceed your own")
        agent, token = register_harness(session, body.harness_kind, body.name, user.id, role)
        base = _base(request)
        return {"harness": harness_view(agent), "token": token,  # token shown once
                "setup": {"OPEN_REFINERY_URL": base, "OPEN_REFINERY_TOKEN": token}}

    @app.post("/harnesses/{agent_id}/rotate")
    def rotate_a_harness(agent_id: str, session: Session = Depends(get_session),
                         user: User = Depends(current_user)):
        agent = session.get(User, agent_id)
        if agent is None or agent.kind != "agent":
            raise HTTPException(status_code=404, detail="unknown harness")
        if agent.owner_id != user.id and user.role not in ("platform", "admin"):
            raise HTTPException(status_code=403, detail="not your harness")
        return {"token": rotate_harness(session, agent_id)}

    @app.delete("/harnesses/{agent_id}")
    def remove_harness(agent_id: str, session: Session = Depends(get_session),
                       user: User = Depends(current_user)):
        agent = session.get(User, agent_id)
        if agent is not None and agent.kind == "agent":
            if agent.owner_id != user.id and user.role not in ("platform", "admin"):
                raise HTTPException(status_code=403, detail="not your harness")
            delete_harness(session, agent_id)
        return {"status": "deleted"}

    # --- OAuth device flow: the agent gets auth without a human pasting a token ---
    @app.post("/agent/device/start")   # called by the agent (unauthenticated)
    def device_start_route(body: DeviceStart, request: Request,
                           session: Session = Depends(get_session)):
        grant = device_start(session, body.harness_kind, body.name)
        return {"device_code": grant.device_code, "user_code": grant.user_code,
                "verification_uri": _base(request) + "/",
                "interval": POLL_INTERVAL_SECONDS, "expires_in": 600}

    @app.post("/agent/device/token")   # polled by the agent (unauthenticated)
    def device_token_route(body: DeviceToken, session: Session = Depends(get_session)):
        try:
            return {"access_token": device_poll(session, body.device_code), "token_type": "bearer"}
        except DevicePending:
            return {"status": "authorization_pending", "interval": POLL_INTERVAL_SECONDS}
        except DeviceExpired as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @app.post("/agent/device/approve")  # a human authorizes the agent in the UI
    def device_approve_route(body: DeviceApprove, session: Session = Depends(get_session),
                             user: User = Depends(current_user)):
        role = body.role or user.role
        grant = device_approve(session, body.user_code, user, role)
        return {"status": "approved", "harness": harness_view(session.get(User, grant.agent_id))}

    # --- teams, usage ledger, cost attribution ---
    @app.get("/teams")
    def get_teams(session: Session = Depends(get_session), _: User = Depends(current_user)):
        return list_teams(session)

    @app.post("/teams", status_code=201)
    def add_team(body: NewTeam, session: Session = Depends(get_session),
                 user: User = Depends(require("platform", "admin"))):
        return create_team(session, body.name, user.id, max_concurrency=body.max_concurrency)

    @app.delete("/teams/{team_id}")
    def remove_team(team_id: str, session: Session = Depends(get_session),
                    _: User = Depends(require("platform", "admin"))):
        delete_team(session, team_id)
        return {"status": "deleted"}

    @app.put("/users/{user_id}/team")
    def assign_team(user_id: str, body: AssignTeam, session: Session = Depends(get_session),
                    _: User = Depends(require("platform", "admin"))):
        u = set_user_team(session, user_id, body.team_id)
        return {"id": u.id, "team_id": u.team_id}

    @app.get("/usage")
    def get_usage(session: Session = Depends(get_session), _: User = Depends(current_user)):
        return {"by_team": usage_by_team(session), "by_actor": usage_by_actor(session)}

    @app.post("/authorize")
    def authorize(body: AuthorizeReq, session: Session = Depends(get_session),
                  user: User = Depends(current_user)):
        """Pre-action gate for an out-of-process harness: verify the caller's
        identity + declared intent against policy **before** it runs a tool,
        command, or host-egress action. Denials raise 403 and are audited."""
        enforce_policy(session, user.role, body.action, body.resource,
                       audit=SqliteSink(session), actor_id=user.id, subject=body.resource,
                       namespace=body.namespace, intent=body.intent)
        return {"allowed": True, "mode": enforcement_mode(session)}

    @app.post("/work-items/{item_id}/attest", status_code=201)
    def add_attestation(item_id: str, body: Attest, session: Session = Depends(get_session),
                        user: User = Depends(current_user)):
        attest(session, item_id, body.check, user.id, body.passed, SqliteSink(session))
        return {"status": "recorded"}

    @app.post("/work-items/{item_id}/transition")
    def move(item_id: str, body: Move, session: Session = Depends(get_session),
             user: User = Depends(current_user)):
        return transition(session, item_id, body.to, user.id, SqliteSink(session),
                          approver_id=user.id if body.approve else None, changes=body.changes)

    # --- async approval queue (chained sign-off) ---
    @app.post("/work-items/{item_id}/request-approval", status_code=201)
    def request_move_approval(item_id: str, body: RequestApproval,
                              session: Session = Depends(get_session),
                              user: User = Depends(current_user)):
        return request_approval(session, item_id, body.to, user.id, SqliteSink(session))

    @app.get("/approvals")
    def get_approvals(session: Session = Depends(get_session), _: User = Depends(current_user),
                      status: str | None = "pending"):
        return list_approvals(session, status=status)

    @app.post("/approvals/{request_id}/approve")
    def approve_move(request_id: str, session: Session = Depends(get_session),
                     user: User = Depends(current_user)):
        return approve_request(session, request_id, user.id, SqliteSink(session))

    @app.post("/approvals/{request_id}/reject")
    def reject_move(request_id: str, session: Session = Depends(get_session),
                    user: User = Depends(current_user)):
        return reject_request(session, request_id, user.id, SqliteSink(session))

    @app.get("/events")
    def get_events(session: Session = Depends(get_session), user: User = Depends(current_user),
                   subject: str | None = None, actor: str | None = None, limit: int = 100):
        return query_events(session, owner=owner_scope(user), subject=subject,
                            actor=actor, limit=limit)

    @app.post("/audit/purge")
    def purge_audit(days: int, session: Session = Depends(get_session),
                    _: User = Depends(require("admin"))):
        return {"purged": purge_events(session, days)}  # retention: drop events older than `days`

    @app.get("/audit/verify")
    def audit_verify(session: Session = Depends(get_session), _: User = Depends(oversight)):
        return verify_chain(session)  # recompute the tamper-evident hash chain

    @app.get("/audit/export")
    def audit_export(session: Session = Depends(get_session), _: User = Depends(oversight)):
        return export_chain(session)  # portable, signed export for external auditors

    @app.get("/audit/export.csv")
    def audit_export_csv(session: Session = Depends(get_session),
                         _: User = Depends(oversight),
                         actor: str | None = None, recipe: str | None = None,
                         subject: str | None = None, since: str | None = None,
                         until: str | None = None, limit: int = 10000):
        csv_text = events_csv(session, actor=actor, recipe=recipe, subject=subject,
                              since=since, until=until, limit=limit)
        return PlainTextResponse(csv_text, media_type="text/csv",
                                 headers={"Content-Disposition": "attachment; filename=audit.csv"})

    # --- compliance evidence packs + time-boxed auditor access ---
    @app.get("/evidence/frameworks")
    def evidence_frameworks(_: User = Depends(oversight)):
        return list(FRAMEWORKS)

    @app.get("/evidence")
    def evidence(framework: str = "soc2", session: Session = Depends(get_session),
                 _: User = Depends(oversight)):
        return evidence_pack(session, framework)

    @app.get("/auditor-grants")
    def get_auditor_grants(session: Session = Depends(get_session),
                           _: User = Depends(require("admin"))):
        return [auditor_view(g) for g in list_auditors(session)]

    @app.post("/auditor-grants", status_code=201)
    def add_auditor_grant(body: NewAuditor, session: Session = Depends(get_session),
                          user: User = Depends(require("admin"))):
        grant, token = mint_auditor(session, body.label, user.id, ttl_days=body.ttl_days)
        return {"grant": auditor_view(grant), "token": token}  # shown once

    @app.delete("/auditor-grants/{grant_id}")
    def remove_auditor_grant(grant_id: str, session: Session = Depends(get_session),
                             _: User = Depends(require("admin"))):
        revoke_auditor(session, grant_id)
        return {"status": "revoked"}

    @app.get("/metrics")
    def metrics(session: Session = Depends(get_session), user: User = Depends(current_user)):
        return summary(session, owner_id=owner_scope(user))

    # --- integrations ---
    @app.get("/connectors")
    def get_connectors(_: User = Depends(current_user)):
        return connectors()  # catalog: kind + label + capabilities + credential fields

    @app.post("/integrations", status_code=201)
    def add_integration(body: NewIntegration, session: Session = Depends(get_session),
                        user: User = Depends(current_user)):
        return create_integration(session, body.kind, body.credential, user.id)

    @app.get("/integrations")
    def get_integrations(session: Session = Depends(get_session), user: User = Depends(current_user)):
        return list_integrations(session, owner_id=owner_scope(user))

    @app.delete("/integrations/{integ_id}")
    def remove_integration(integ_id: str, session: Session = Depends(get_session),
                           _: User = Depends(current_user)):
        delete_integration(session, integ_id)
        return {"status": "deleted"}

    def _connect_redirect(request: Request, kind: str) -> str:
        return f"{_base(request)}/integrations/{kind}/oauth/callback"

    @app.post("/integrations/{kind}/oauth/start")
    def connect_start(kind: str, request: Request, session: Session = Depends(get_session),
                      user: User = Depends(current_user)):
        creds = provider_creds(session, kind)
        if not oauth.is_enabled(creds):
            raise HTTPException(status_code=404, detail=f"{kind} oauth not configured")
        state = create_connect_state(session, user.id, kind)
        scope = oauth.PROVIDERS[kind]["connect_scope"]
        url = oauth.authorize_url(kind, state, _connect_redirect(request, kind), scope,
                                  creds["client_id"])
        return {"authorize_url": url}

    @app.get("/integrations/{kind}/oauth/callback")
    def connect_callback(kind: str, request: Request, code: str = "", state: str = "",
                         session: Session = Depends(get_session)):
        user_id = pop_connect_state(session, state)
        if user_id is None:
            return RedirectResponse(_home(request) + "#integration_error=state")
        creds = provider_creds(session, kind)
        token = oauth.exchange_code(kind, code, _connect_redirect(request, kind),
                                    creds["client_id"], creds["client_secret"])
        create_integration(session, kind, {"token": token}, user_id)
        return RedirectResponse(_home(request) + f"#connected={kind}")

    @app.post("/integrations/{integ_id}/verify")
    def check_integration(integ_id: str, session: Session = Depends(get_session),
                          _: User = Depends(current_user)):
        return verify_integration(session, integ_id)

    @app.get("/integrations/{integ_id}/repos")
    def integration_repos(integ_id: str, session: Session = Depends(get_session),
                          _: User = Depends(current_user)):
        return list_remote_repos(session, integ_id)

    @app.get("/integrations/{integ_id}/issues")
    def integration_issues(integ_id: str, session: Session = Depends(get_session),
                           _: User = Depends(current_user)):
        return list_issues(session, integ_id)

    @app.get("/integrations/{integ_id}/workflow")
    def integration_workflow(integ_id: str, session: Session = Depends(get_session),
                             _: User = Depends(current_user)):
        return {"stages": list_workflow(session, integ_id)}  # for process-from-columns

    @app.post("/integrations/{integ_id}/sync")
    def sync_integration(integ_id: str, body: SyncRequest, session: Session = Depends(get_session),
                         user: User = Depends(current_user)):
        return sync_tracker(session, integ_id, body.repo_id, body.process_id,
                            user.id, SqliteSink(session))

    # --- targets, routing, quotas (Platform layer) ---
    @app.post("/targets", status_code=201)
    def add_target(body: NewTarget, session: Session = Depends(get_session),
                   user: User = Depends(current_user)):
        return create_target(session, body.name, body.kind, body.endpoint, user.id,
                            credential=body.credential, output_schema=body.output_schema,
                            region=body.region, compliance=body.compliance, unit_cost=body.unit_cost)

    @app.get("/targets")
    def get_targets(session: Session = Depends(get_session), user: User = Depends(current_user)):
        return list_targets(session, owner_id=owner_scope(user))

    @app.get("/routing-policy")
    def get_routing_policy(session: Session = Depends(get_session), _: User = Depends(current_user)):
        return routing_policy(session)

    @app.put("/routing-policy")
    def set_routing_policy(body: RoutingPolicyBody, session: Session = Depends(get_session),
                           user: User = Depends(require("platform", "admin"))):
        set_setting(session, ROUTING_POLICY_KEY, json.dumps(body.model_dump()), user.id)
        return routing_policy(session)

    @app.get("/traffic")
    def get_traffic(session: Session = Depends(get_session), _: User = Depends(current_user)):
        return traffic_graph(session)

    @app.delete("/targets/{target_id}")
    def remove_target(target_id: str, session: Session = Depends(get_session),
                      _: User = Depends(current_user)):
        delete_target(session, target_id)
        return {"status": "deleted"}

    # --- connect a target via OAuth (token stored in its credential) ---
    def _target_oauth_redirect(request: Request, target_id: str, provider: str) -> str:
        return f"{_base(request)}/targets/{target_id}/oauth/{provider}/callback"

    @app.post("/targets/{target_id}/oauth/{provider}/start")
    def target_oauth_start(target_id: str, provider: str, request: Request,
                           session: Session = Depends(get_session), user: User = Depends(current_user)):
        creds = provider_creds(session, provider)
        if not oauth.is_enabled(creds):
            raise HTTPException(status_code=404, detail=f"{provider} oauth not configured")
        state = create_connect_state(session, user.id, provider)
        scope = oauth.PROVIDERS[provider]["connect_scope"]
        url = oauth.authorize_url(provider, state, _target_oauth_redirect(request, target_id, provider),
                                  scope, creds["client_id"])
        return {"authorize_url": url}

    @app.get("/targets/{target_id}/oauth/{provider}/callback")
    def target_oauth_callback(target_id: str, provider: str, request: Request,
                              code: str = "", state: str = "",
                              session: Session = Depends(get_session)):
        if pop_connect_state(session, state) is None:   # validates + consumes (CSRF, one-time)
            return RedirectResponse(_home(request) + "#target_error=state")
        creds = provider_creds(session, provider)
        token = oauth.exchange_code(provider, code, _target_oauth_redirect(request, target_id, provider),
                                    creds["client_id"], creds["client_secret"])
        set_target_credential(session, target_id, {"provider": provider, "access_token": token})
        return RedirectResponse(_home(request) + f"#connected={provider}")

    @app.post("/routes", status_code=201)
    def add_route(body: NewRoute, session: Session = Depends(get_session),
                  user: User = Depends(current_user)):
        return create_route(session, body.process_id, body.target_id, user.id,
                           step=body.step, priority=body.priority)

    @app.get("/routes")
    def get_routes(session: Session = Depends(get_session), user: User = Depends(current_user)):
        return list_routes(session, owner_id=owner_scope(user))

    @app.delete("/routes/{route_id}")
    def remove_route(route_id: str, session: Session = Depends(get_session),
                     _: User = Depends(current_user)):
        delete_route(session, route_id)
        return {"status": "deleted"}

    @app.post("/quotas", status_code=201)
    def add_quota(body: NewQuota, session: Session = Depends(get_session),
                  user: User = Depends(current_user)):
        return create_quota(session, body.target_id, body.limit, user.id,
                            window_seconds=body.window_seconds)

    @app.get("/quotas")
    def get_quotas(session: Session = Depends(get_session), user: User = Depends(current_user)):
        return list_quotas(session, owner_id=owner_scope(user))

    # --- policy governance + content filtering ---
    @app.post("/policies", status_code=201)
    def add_policy(body: NewPolicy, session: Session = Depends(get_session),
                   user: User = Depends(require("platform", "admin"))):
        return create_policy(session, body.effect, user.id, role=body.role,
                           action=body.action, resource=body.resource,
                           strict=body.strict, kind=body.kind, content=body.content,
                           layer=body.layer, namespace=body.namespace, note=body.note)

    @app.get("/policies")
    def get_policies(session: Session = Depends(get_session), _: User = Depends(current_user)):
        return list_policies(session)

    @app.get("/policies/history")
    def policy_history(policy_id: str | None = None, session: Session = Depends(get_session),
                       _: User = Depends(oversight)):
        return list_policy_versions(session, policy_id=policy_id)

    @app.get("/policies/at")
    def policy_at(t: str, session: Session = Depends(get_session), _: User = Depends(oversight)):
        return policies_in_effect_at(session, t)  # rule set in effect at ISO time t

    @app.delete("/policies/{policy_id}")
    def remove_policy(policy_id: str, session: Session = Depends(get_session),
                      user: User = Depends(require("platform", "admin")), note: str = ""):
        delete_policy(session, policy_id, changed_by=user.id, note=note)
        return {"status": "deleted"}

    @app.post("/content/scan")
    def content_scan(body: ScanRequest, _: User = Depends(current_user)):
        clean, hits = scan_content(body.text)
        return {"clean": clean, "hits": hits}

    @app.post("/execute")
    def run_execute(body: ExecuteRequest, session: Session = Depends(get_session),
                    user: User = Depends(current_user)):
        return execute(session, user.id, body.process_id, body.payload, SqliteSink(session),
                      step=body.step, work_item_id=body.work_item_id,
                      experiment_id=body.experiment_id, arm=body.arm)

    # --- auth ---
    def _redirect_uri(request: Request) -> str:
        return f"{_base(request)}/auth/github/callback"

    @app.post("/auth/login")
    def login(body: Credentials, session: Session = Depends(get_session)):
        user = authenticate(session, body.email, body.password)
        if user is None:
            raise HTTPException(status_code=401, detail="invalid email or password")
        return {"token": create_session(session, user.id), "user": user}

    @app.get("/auth/providers")
    def providers(session: Session = Depends(get_session)):
        return {kind: oauth.is_enabled(provider_creds(session, kind)) for kind in oauth.PROVIDERS}

    @app.get("/auth/github/login")
    def github_login(request: Request, session: Session = Depends(get_session)):
        creds = provider_creds(session, "github")
        if not oauth.is_enabled(creds):
            raise HTTPException(status_code=404, detail="github oauth not configured")
        state = secrets.token_urlsafe(16)
        scope = oauth.PROVIDERS["github"]["login_scope"]
        resp = RedirectResponse(
            oauth.authorize_url("github", state, _redirect_uri(request), scope, creds["client_id"]))
        resp.set_cookie("or_oauth_state", state, httponly=True, max_age=600, samesite="lax")
        return resp

    @app.get("/auth/github/callback")
    def github_callback(request: Request, code: str = "", state: str = "",
                        session: Session = Depends(get_session)):
        creds = provider_creds(session, "github")
        if not oauth.is_enabled(creds):
            raise HTTPException(status_code=404, detail="github oauth not configured")
        if not state or state != request.cookies.get("or_oauth_state"):
            raise HTTPException(status_code=400, detail="oauth state mismatch")
        access = oauth.exchange_code("github", code, _redirect_uri(request),
                                     creds["client_id"], creds["client_secret"])
        email = oauth.primary_email(access)
        user = user_by_email(session, email) if email else None
        if user is None:
            return RedirectResponse(_home(request) + "#oauth_error=no-account")
        token = create_session(session, user.id)
        resp = RedirectResponse(f"{_home(request)}#token={token}")
        resp.delete_cookie("or_oauth_state")
        return resp

    # --- settings (encrypted config in the DB; admin/platform) ---
    @app.get("/settings")
    def get_settings(session: Session = Depends(get_session),
                     _: User = Depends(require("platform", "admin"))):
        return {"keys": list_setting_keys(session)}  # values never returned

    @app.put("/settings")
    def put_setting(body: SettingBody, session: Session = Depends(get_session),
                    user: User = Depends(require("platform", "admin"))):
        set_setting(session, body.key, body.value, user.id)
        return {"status": "saved", "key": body.key}

    @app.delete("/settings/{key}")
    def remove_setting(key: str, session: Session = Depends(get_session),
                       _: User = Depends(require("platform", "admin"))):
        delete_setting(session, key)
        return {"status": "deleted"}

    # Serve the built dashboard last so API routes always match first.
    if (_STATIC / "index.html").exists():
        app.mount("/", StaticFiles(directory=_STATIC, html=True), name="spa")

    return app


def create_app_from_env() -> FastAPI:
    app = create_app(database_url=os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL))
    from .scheduler import start_scheduler
    start_scheduler(app.state.engine)  # auto-ingest loop (serve path only, not tests)
    return app
