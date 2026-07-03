"""HTTP layer — FastAPI over the domain.

Auth: an `Authorization: Bearer <token>` header resolves to a `User`; every
mutation is stamped with that user. Scoping: developers see and act on what they
own; platform and admin see everything. User management is admin-only.
"""

from __future__ import annotations

import sqlite3

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .processes import create_process, list_processes
from .repositories import DuplicateRepository, create_repository, list_repositories
from .store import DEFAULT_DATABASE_URL, SqliteSink, connect, query_events
from .users import DuplicateUser, User, create_user, user_by_token
from .work_items import (
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


class NewWorkItem(BaseModel):
    repo_id: str
    process_id: str
    title: str


class Move(BaseModel):
    to: str


# --- app ------------------------------------------------------------------

def create_app(conn: sqlite3.Connection | None = None, database_url: str = DEFAULT_DATABASE_URL) -> FastAPI:
    app = FastAPI(title="open-refinery")
    app.state.conn = conn or connect(database_url, check_same_thread=False)

    def db(request: Request) -> sqlite3.Connection:
        return request.app.state.conn

    def current_user(
        request: Request, authorization: str | None = Header(default=None)
    ) -> User:
        token = (authorization or "").removeprefix("Bearer ").strip()
        user = user_by_token(request.app.state.conn, token) if token else None
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

    @app.post("/work-items/{item_id}/transition")
    def move(item_id: str, body: Move, user: User = Depends(current_user)):
        return transition(db_conn(app), item_id, body.to, user.id, SqliteSink(db_conn(app)))

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

    return app


def db_conn(app: FastAPI) -> sqlite3.Connection:
    return app.state.conn


def create_app_from_env() -> FastAPI:
    import os

    return create_app(database_url=os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL))
