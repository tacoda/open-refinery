"""HTTP layer — FastAPI over the domain.

Auth: an `Authorization: Bearer <token>` header resolves to a `User`; every
mutation is stamped with that user. Scoping: developers see and act on what they
own; platform and admin see everything. User management is admin-only.
"""

from __future__ import annotations

import os
import secrets
import sqlite3
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import oauth

_STATIC = Path(__file__).parent / "static"

from .attestations import AttestationFailed, AttestationMissing, attest
from .integrations import (
    create_connect_state,
    create_integration,
    list_integrations,
    list_remote_repos,
    pop_connect_state,
)
from .integrations import verify as verify_integration
from .metrics import summary
from .processes import create_process, list_processes
from .repositories import DuplicateRepository, create_repository, list_repositories
from .store import DEFAULT_DATABASE_URL, SqliteSink, connect, query_events
from .users import (
    DuplicateUser,
    User,
    authenticate,
    count_users,
    create_session,
    create_user,
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
    transition,
)

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


class NewWorkItem(BaseModel):
    repo_id: str
    process_id: str
    title: str


class Move(BaseModel):
    to: str
    approve: bool = False  # current user signs off, if the process requires it


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
    token: str


# --- app ------------------------------------------------------------------

def create_app(conn: sqlite3.Connection | None = None, database_url: str = DEFAULT_DATABASE_URL) -> FastAPI:
    app = FastAPI(title="open-refinery")
    app.state.conn = conn or connect(database_url, check_same_thread=False)

    # Dev only: the Vite dev server (localhost) calls the API cross-origin.
    # In production the SPA is served same-origin from _STATIC, so this is a no-op.
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"http://localhost(:\d+)?",
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def db(request: Request) -> sqlite3.Connection:
        return request.app.state.conn

    def current_user(
        request: Request, authorization: str | None = Header(default=None)
    ) -> User:
        token = (authorization or "").removeprefix("Bearer ").strip()
        conn = request.app.state.conn
        user = (user_by_token(conn, token) or session_user(conn, token)) if token else None
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

    # --- exception mapping ---
    for exc, code in (
        (DuplicateUser, 409),
        (DuplicateRepository, 409),
        (InvalidTransition, 409),
        (ApprovalRequired, 409),
        (AttestationMissing, 409),
        (AttestationFailed, 409),
        (UnknownWorkItem, 404),
        (ValueError, 400),
    ):
        app.add_exception_handler(
            exc,
            lambda _req, e, code=code: JSONResponse({"detail": str(e)}, status_code=code),
        )

    # --- routes ---
    @app.get("/health")
    def health():
        return {"status": "ok"}

    # --- first-run setup: create the initial admin in-browser on an empty DB ---
    @app.get("/setup/status")
    def setup_status():
        return {"needs_setup": count_users(db_conn(app)) == 0}

    @app.post("/setup", status_code=201)
    def setup(body: Setup):
        if count_users(db_conn(app)) > 0:
            raise HTTPException(status_code=409, detail="already set up")
        user, token = create_user(db_conn(app), body.email, body.password, "admin")
        return {"user": user, "token": token}

    @app.get("/me")
    def me(user: User = Depends(current_user)):
        return user

    @app.post("/users", status_code=201)
    def add_user(body: NewUser, _: User = Depends(require("admin"))):
        user, token = create_user(db_conn(app), body.email, body.password, body.role)
        return {"user": user, "token": token}  # token shown once

    @app.post("/repositories", status_code=201)
    def add_repo(body: NewRepo, user: User = Depends(current_user)):
        return create_repository(db_conn(app), body.name, body.git_url, user.id)

    @app.get("/repositories")
    def get_repos(user: User = Depends(current_user)):
        return list_repositories(db_conn(app), owner_id=owner_scope(user))

    @app.post("/processes", status_code=201)
    def add_process(body: NewProcess, user: User = Depends(current_user)):
        return create_process(
            db_conn(app), body.name, body.archetype, body.stages, user.id,
            transitions=body.transitions, initial=body.initial,
            oversight=body.oversight, gates=body.gates, checks=body.checks,
        )

    @app.get("/processes")
    def get_processes(user: User = Depends(current_user)):
        return list_processes(db_conn(app), owner_id=owner_scope(user))

    @app.post("/work-items", status_code=201)
    def add_work_item(body: NewWorkItem, user: User = Depends(current_user)):
        return create_work_item(db_conn(app), body.repo_id, body.process_id, body.title, user.id)

    @app.get("/work-items")
    def get_work_items(user: User = Depends(current_user), repo_id: str | None = None):
        return list_work_items(db_conn(app), owner_id=owner_scope(user), repo_id=repo_id)

    @app.post("/work-items/{item_id}/attest", status_code=201)
    def add_attestation(item_id: str, body: Attest, user: User = Depends(current_user)):
        attest(db_conn(app), item_id, body.check, user.id, body.passed, SqliteSink(db_conn(app)))
        return {"status": "recorded"}

    @app.post("/work-items/{item_id}/transition")
    def move(item_id: str, body: Move, user: User = Depends(current_user)):
        return transition(
            db_conn(app), item_id, body.to, user.id, SqliteSink(db_conn(app)),
            approver_id=user.id if body.approve else None,
        )

    @app.get("/events")
    def get_events(
        user: User = Depends(current_user),
        subject: str | None = None,
        actor: str | None = None,
        limit: int = 100,
    ):
        # developers see only their own events; platform/admin see all.
        owner = owner_scope(user)
        return query_events(db_conn(app), owner=owner, subject=subject, actor=actor, limit=limit)

    @app.get("/metrics")
    def metrics(user: User = Depends(current_user)):
        return summary(db_conn(app), owner_id=owner_scope(user))

    # --- integrations (external services) ---
    @app.post("/integrations", status_code=201)
    def add_integration(body: NewIntegration, user: User = Depends(current_user)):
        return create_integration(db_conn(app), body.kind, body.token, user.id)

    @app.get("/integrations")
    def get_integrations(user: User = Depends(current_user)):
        return list_integrations(db_conn(app), owner_id=owner_scope(user))

    # Connect a service via OAuth. The SPA is authenticated, so we bind the flow
    # to the user with a one-time state; the callback (no auth header) resolves
    # the user from that state. Generic over provider kind.
    def _connect_redirect(request: Request, kind: str) -> str:
        base = os.environ.get("APP_BASE_URL", str(request.base_url)).rstrip("/")
        return f"{base}/integrations/{kind}/oauth/callback"

    @app.post("/integrations/{kind}/oauth/start")
    def connect_start(kind: str, request: Request, user: User = Depends(current_user)):
        if not oauth.is_enabled(kind):
            raise HTTPException(status_code=404, detail=f"{kind} oauth not configured")
        state = create_connect_state(db_conn(app), user.id, kind)
        scope = oauth.PROVIDERS[kind]["connect_scope"]
        url = oauth.authorize_url(kind, state, _connect_redirect(request, kind), scope)
        return {"authorize_url": url}

    @app.get("/integrations/{kind}/oauth/callback")
    def connect_callback(kind: str, request: Request, code: str = "", state: str = ""):
        user_id = pop_connect_state(db_conn(app), state)
        if user_id is None:
            return RedirectResponse(_home(request) + "#integration_error=state")
        token = oauth.exchange_code(kind, code, _connect_redirect(request, kind))
        create_integration(db_conn(app), kind, token, user_id)
        return RedirectResponse(_home(request) + f"#connected={kind}")

    @app.post("/integrations/{integ_id}/verify")
    def check_integration(integ_id: str, _: User = Depends(current_user)):
        return verify_integration(db_conn(app), integ_id)

    @app.get("/integrations/{integ_id}/repos")
    def integration_repos(integ_id: str, _: User = Depends(current_user)):
        return list_remote_repos(db_conn(app), integ_id)

    # --- OAuth (GitHub) ---
    def _redirect_uri(request: Request) -> str:
        base = os.environ.get("APP_BASE_URL", str(request.base_url)).rstrip("/")
        return f"{base}/auth/github/callback"

    def _home(request: Request) -> str:
        return os.environ.get("APP_BASE_URL", str(request.base_url)).rstrip("/") + "/"

    @app.post("/auth/login")
    def login(body: Credentials):
        user = authenticate(db_conn(app), body.email, body.password)
        if user is None:
            raise HTTPException(status_code=401, detail="invalid email or password")
        return {"token": create_session(db_conn(app), user.id), "user": user}

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
    def github_callback(request: Request, code: str = "", state: str = ""):
        if not oauth.is_enabled("github"):
            raise HTTPException(status_code=404, detail="github oauth not configured")
        cookie_state = request.cookies.get("or_oauth_state")
        if not state or state != cookie_state:
            raise HTTPException(status_code=400, detail="oauth state mismatch")

        access = oauth.exchange_code("github", code, _redirect_uri(request))
        email = oauth.primary_email(access)
        user = user_by_email(db_conn(app), email) if email else None
        if user is None:
            return RedirectResponse(_home(request) + "#oauth_error=no-account")
        token = create_session(db_conn(app), user.id)
        resp = RedirectResponse(f"{_home(request)}#token={token}")
        resp.delete_cookie("or_oauth_state")
        return resp

    # Serve the built dashboard last so API routes always match first. Absent in a
    # source checkout without a frontend build; present in the shipped wheel.
    if (_STATIC / "index.html").exists():
        app.mount("/", StaticFiles(directory=_STATIC, html=True), name="spa")

    return app


def db_conn(app: FastAPI) -> sqlite3.Connection:
    return app.state.conn


def create_app_from_env() -> FastAPI:
    import os

    return create_app(database_url=os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL))
