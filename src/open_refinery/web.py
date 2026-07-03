"""HTTP layer — FastAPI over the domain.

Auth: an `Authorization: Bearer <token>` header resolves to a `User`; every
mutation is stamped with that user. Scoping: developers see and act on what they
own; platform and admin see everything. User management is admin-only. Each
request gets its own SQLModel `Session`.
"""

from __future__ import annotations

import os
import secrets
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import JSONResponse, RedirectResponse
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
    create_connect_state,
    create_integration,
    delete_integration,
    list_integrations,
    list_issues,
    list_remote_repos,
    pop_connect_state,
)
from .integrations import verify as verify_integration
from .metrics import summary
from .policies import (
    PolicyDenied,
    create_policy,
    delete_policy,
    list_policies,
    scan_content,
)
from .processes import create_process, list_processes
from .repositories import DuplicateRepository, create_repository, import_or_get, list_repositories
from .store import DEFAULT_DATABASE_URL, SqliteSink, engine_for, query_events
from .targets import (
    QuotaExceeded,
    create_quota,
    create_route,
    create_target,
    delete_route,
    delete_target,
    list_quotas,
    list_routes,
    list_targets,
)
from .users import (
    DuplicateUser,
    User,
    authenticate,
    count_users,
    create_session,
    create_user,
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
    min_approver_role: str = "senior"
    approval_chain: list[str] | None = None


class NewWorkItem(BaseModel):
    repo_id: str
    process_id: str
    title: str


class Move(BaseModel):
    to: str
    approve: bool = False  # current user signs off, if the process requires it


class RequestApproval(BaseModel):
    to: str


class NewInvitation(BaseModel):
    email: str
    role: str
    ttl_days: int = 7


class AcceptInvite(BaseModel):
    token: str
    password: str


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


class NewRoute(BaseModel):
    process_id: str
    target_id: str
    step: str | None = None
    priority: int = 0


class NewQuota(BaseModel):
    target_id: str
    limit: int


class NewPolicy(BaseModel):
    effect: str
    role: str = "*"
    action: str = "*"
    resource: str = "*"


class ScanRequest(BaseModel):
    text: str


class ExecuteRequest(BaseModel):
    process_id: str
    payload: str
    step: str | None = None
    work_item_id: str | None = None


# --- app ------------------------------------------------------------------

def create_app(session: Session | None = None, database_url: str = DEFAULT_DATABASE_URL) -> FastAPI:
    # Self-host API docs at /api-docs (assets bundled at build time — no CDN).
    app = FastAPI(title="open-refinery", docs_url=None, redoc_url=None)
    engine = session.get_bind() if session is not None else engine_for(database_url)
    app.state.engine = engine

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

    def current_user(
        session: Session = Depends(get_session),
        authorization: str | None = Header(default=None),
    ) -> User:
        token = (authorization or "").removeprefix("Bearer ").strip()
        user = (user_by_token(session, token) or session_user(session, token)) if token else None
        if user is None:
            raise HTTPException(status_code=401, detail="invalid or missing token")
        return user

    def require(*roles: str):
        def dep(user: User = Depends(current_user)) -> User:
            if user.role not in roles:
                raise HTTPException(status_code=403, detail="forbidden for this role")
            return user
        return dep

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
        (PolicyDenied, 403),
        (ExecutionError, 502),
        (UnknownWorkItem, 404),
        (ValueError, 400),
    ):
        app.add_exception_handler(
            exc,
            lambda _req, e, code=code: JSONResponse({"detail": str(e)}, status_code=code),
        )

    def _base(request: Request) -> str:
        return os.environ.get("APP_BASE_URL", str(request.base_url)).rstrip("/")

    def _home(request: Request) -> str:
        return _base(request) + "/"

    # --- routes ---
    @app.get("/health")
    def health():
        return {"status": "ok"}

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
        return user

    @app.post("/me/token/rotate")
    def rotate_my_token(session: Session = Depends(get_session), user: User = Depends(current_user)):
        return {"token": rotate_token(session, user.id)}  # old API token invalidated

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

    @app.post("/work-items/{item_id}/attest", status_code=201)
    def add_attestation(item_id: str, body: Attest, session: Session = Depends(get_session),
                        user: User = Depends(current_user)):
        attest(session, item_id, body.check, user.id, body.passed, SqliteSink(session))
        return {"status": "recorded"}

    @app.post("/work-items/{item_id}/transition")
    def move(item_id: str, body: Move, session: Session = Depends(get_session),
             user: User = Depends(current_user)):
        return transition(session, item_id, body.to, user.id, SqliteSink(session),
                          approver_id=user.id if body.approve else None)

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

    @app.get("/metrics")
    def metrics(session: Session = Depends(get_session), user: User = Depends(current_user)):
        return summary(session, owner_id=owner_scope(user))

    # --- integrations ---
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
        if not oauth.is_enabled(kind):
            raise HTTPException(status_code=404, detail=f"{kind} oauth not configured")
        state = create_connect_state(session, user.id, kind)
        scope = oauth.PROVIDERS[kind]["connect_scope"]
        return {"authorize_url": oauth.authorize_url(kind, state, _connect_redirect(request, kind), scope)}

    @app.get("/integrations/{kind}/oauth/callback")
    def connect_callback(kind: str, request: Request, code: str = "", state: str = "",
                         session: Session = Depends(get_session)):
        user_id = pop_connect_state(session, state)
        if user_id is None:
            return RedirectResponse(_home(request) + "#integration_error=state")
        token = oauth.exchange_code(kind, code, _connect_redirect(request, kind))
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
                            credential=body.credential, output_schema=body.output_schema)

    @app.get("/targets")
    def get_targets(session: Session = Depends(get_session), user: User = Depends(current_user)):
        return list_targets(session, owner_id=owner_scope(user))

    @app.delete("/targets/{target_id}")
    def remove_target(target_id: str, session: Session = Depends(get_session),
                      _: User = Depends(current_user)):
        delete_target(session, target_id)
        return {"status": "deleted"}

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
        return create_quota(session, body.target_id, body.limit, user.id)

    @app.get("/quotas")
    def get_quotas(session: Session = Depends(get_session), user: User = Depends(current_user)):
        return list_quotas(session, owner_id=owner_scope(user))

    # --- policy governance + content filtering ---
    @app.post("/policies", status_code=201)
    def add_policy(body: NewPolicy, session: Session = Depends(get_session),
                   user: User = Depends(require("platform", "admin"))):
        return create_policy(session, body.effect, user.id, role=body.role,
                           action=body.action, resource=body.resource)

    @app.get("/policies")
    def get_policies(session: Session = Depends(get_session), _: User = Depends(current_user)):
        return list_policies(session)

    @app.delete("/policies/{policy_id}")
    def remove_policy(policy_id: str, session: Session = Depends(get_session),
                      _: User = Depends(require("platform", "admin"))):
        delete_policy(session, policy_id)
        return {"status": "deleted"}

    @app.post("/content/scan")
    def content_scan(body: ScanRequest, _: User = Depends(current_user)):
        clean, hits = scan_content(body.text)
        return {"clean": clean, "hits": hits}

    @app.post("/execute")
    def run_execute(body: ExecuteRequest, session: Session = Depends(get_session),
                    user: User = Depends(current_user)):
        return execute(session, user.id, body.process_id, body.payload, SqliteSink(session),
                      step=body.step, work_item_id=body.work_item_id)

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
    def providers():
        return oauth.enabled_providers()

    @app.get("/auth/github/login")
    def github_login(request: Request):
        if not oauth.is_enabled("github"):
            raise HTTPException(status_code=404, detail="github oauth not configured")
        state = secrets.token_urlsafe(16)
        scope = oauth.PROVIDERS["github"]["login_scope"]
        resp = RedirectResponse(oauth.authorize_url("github", state, _redirect_uri(request), scope))
        resp.set_cookie("or_oauth_state", state, httponly=True, max_age=600, samesite="lax")
        return resp

    @app.get("/auth/github/callback")
    def github_callback(request: Request, code: str = "", state: str = "",
                        session: Session = Depends(get_session)):
        if not oauth.is_enabled("github"):
            raise HTTPException(status_code=404, detail="github oauth not configured")
        if not state or state != request.cookies.get("or_oauth_state"):
            raise HTTPException(status_code=400, detail="oauth state mismatch")
        access = oauth.exchange_code("github", code, _redirect_uri(request))
        email = oauth.primary_email(access)
        user = user_by_email(session, email) if email else None
        if user is None:
            return RedirectResponse(_home(request) + "#oauth_error=no-account")
        token = create_session(session, user.id)
        resp = RedirectResponse(f"{_home(request)}#token={token}")
        resp.delete_cookie("or_oauth_state")
        return resp

    # Serve the built dashboard last so API routes always match first.
    if (_STATIC / "index.html").exists():
        app.mount("/", StaticFiles(directory=_STATIC, html=True), name="spa")

    return app


def create_app_from_env() -> FastAPI:
    return create_app(database_url=os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL))
