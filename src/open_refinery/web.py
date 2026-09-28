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

from .approvals import approve as approve_request
from .approvals import list_approvals, reject as reject_request, request_approval
from .escalations import current_overdue
from .attestations import AttestationFailed, AttestationMissing, attest
from .executor import ExecutionError, execute
from .integrations import (
    connectors,
    create_integration,
    delete_integration,
    list_integrations,
    list_issues,
    list_remote_repos,
    list_workflow,
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
from .improve import (
    proposals as improve_proposals,
    propose_finding as improve_propose,
    score as improve_score,
)
from .experiments import (
    analyze_experiment,
    conclude_experiment,
    create_experiment,
    list_experiments,
    record_eval,
)
from .ingest import charter as repo_charter
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
from .packs import disable_pack, enable_pack, list_packs, list_standards, pack_detail
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
from .provenance import Record
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
    create_role,
    delete_role,
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
    public_user as _public_user,
    require,
)

_STATIC = Path(__file__).parent / "static"
_SEES_ALL = ("platform", "admin")


# --- request bodies -------------------------------------------------------

class NewUser(BaseModel):
    """Adding someone: pick a preset to start from, then edit freely.

    `role` names the preset and is kept as a label. `permissions`, when given,
    replaces it outright — so a person who fits no preset needs no new one.
    """
    email: str
    password: str
    role: str = "developer"
    permissions: list[str] | None = None


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





class Move(BaseModel):
    to: str
    approve: bool = False  # current user signs off, if the process requires it
    changes: dict | None = None  # PR change set: code/migrations + open {name:{old,new}} maps (config/env/libraries/data/services/secrets/infra/dns/…); refs only, never material


class RequestApproval(BaseModel):
    to: str








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











class PresetBody(BaseModel):
    """A preset: a named bundle of permissions to start people from."""
    rank: int = 1
    permissions: list[str] = []


class PermissionsBody(BaseModel):
    """What a person may do. `preset` seeds the set; `permissions` adds to it."""
    permissions: list[str] = []
    preset: str = ""


class RepoSettings(BaseModel):
    """A repository's settings. Omitted fields are left alone."""
    charter_paths: list[str] | None = None   # [] resets to the default
    integration_id: str | None = None
    ingest_interval_hours: int | None = None


class NewRule(BaseModel):
    """A rule, and the rung that carries it."""
    text: str
    layer: str = "code"
    rung: int = 0
    side: str = "constraint"
    predicate: str = ""
    withholds: list[str] = []
    scope: str = "*"


class MoveRule(BaseModel):
    """Carry a rule at a different rung. A demotion needs a second signer."""
    to: int
    predicate: str = ""
    second_signer: str = ""      # email; required for a demotion


class PhaseBody(BaseModel):
    """A team's override of one phase. Omitted fields keep the built-in."""
    prompt: str | None = None
    model: str | None = None
    thinking: str | None = None
    max_turns: int | None = None
    tools: list[str] | None = None
    subagents: bool | None = None


class PipelineBody(BaseModel):
    """A stage graph. `stages` is the only required part."""
    name: str = "pipeline"
    first: str | None = None
    terminal: list[str] | None = None
    model: str | None = None
    stages: dict[str, dict] = {}
    layout: dict | None = None


class NewRun(BaseModel):
    """Put a work item through a pipeline. Name it or take the newest
    `ship-a-ticket`."""
    work_item_id: str
    pipeline_id: str | None = None
    pipeline: str | None = None
    spec: str = ""
    opt_in: list[str] = []
    skip: list[str] = []


class NewCredential(BaseModel):
    provider: str                   # a key from credentials.PROVIDERS
    credential: dict[str, str]      # the provider's declared fields
    shared: bool = False            # org-wide fallback; shareable providers only


class RotateCredential(BaseModel):
    credential: dict[str, str]


class NewIntegration(BaseModel):
    kind: str
    credential: dict[str, str]  # {token} for github/gitlab/linear; {site,email,token} for jira


class ImproveProposal(BaseModel):
    kind: str          # the finding's kind
    detail: str        # its exact detail line — the server re-derives the evidence
    repo_id: str
    process_id: str


class SyncRequest(BaseModel):
    repo_id: str
    process_id: str
    autostart: bool | None = None   # None = whatever the integration is set to


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








class RepoLink(BaseModel):
    integration_id: str | None = None


class RepoSchedule(BaseModel):
    interval_hours: int = 0





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
# NOTE (2.16.0): a regex table mapping paths to role *names* used to run here
# as middleware, on top of the per-route dependencies. Two authorization
# systems, and they drifted the moment permissions moved onto the user — a
# permission grant took effect in `/me` and was still refused by the middleware.
#
# One source of truth now: the `Depends(...)` guard on each route (see
# `deps.py`). It is precise about the route it guards, it is testable, and it
# reads the same permission set everything else does.


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
    from .routers import (core, credentials, harness, intake, ladder, ops, org,
                          pipelines, policy, proposals, roles, routing, workitem)
    for mod in (core, ops, org, harness, workitem, routing, policy,
                credentials, roles, proposals, pipelines, ladder, intake):
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

    app.add_api_websocket_route("/ws", _live_ws)
    _register_exception_handlers(app)
    _include_routers(app)

    if (_STATIC / "index.html").exists():
        app.mount("/", StaticFiles(directory=_STATIC, html=True), name="spa")

    return app


def create_app_from_env() -> FastAPI:
    """The `serve` path: the API, plus the background loops that make it a
    factory rather than a filing cabinet."""
    from .config import get as setting

    app = create_app(database_url=os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL))

    from .scheduler import start_scheduler
    start_scheduler(app.state.engine)   # re-read repo charters on a cadence

    # The factory floor. Runs advance on the server, unattended — which is the
    # difference between supervising agents and running them. Set WORKERS=0 to
    # drive runs by hand instead.
    count = int(setting("WORKERS") or 0)
    if count > 0:
        from .pipeline.workers import start_pool
        start_pool(app.state.engine, workers=count)
    return app
