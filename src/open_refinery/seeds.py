"""Database seeds — a **minimal** sample dataset for local dev and tests.

`seed(conn)` populates an empty store with the three default-role users, one
repository, one board process, and a couple of work items — just enough to sign
in and see the app working. Everything richer (doctrine processes, standards,
workflows like bug-fix) ships as **packs**, enabled on demand. Returns the
created objects and the users' tokens so a caller can sign in.

A fresh production install seeds none of this: it goes to the setup wizard (or
`open-refinery create-admin`). `seed` is dev/eval only.
"""

from __future__ import annotations

import sqlite3

from .processes import create_process
from .repositories import create_repository
from .settings import set_setting
from .store import SqliteSink
from .targets import create_route, create_target
from .users import count_users, create_user
from .work_items import create_work_item, transition

# Dev passwords, fixed and obvious. `seed` is dev/eval only — a production
# install goes to the setup wizard — and a developer who cannot sign in to the
# thing they just seeded has been given a database, not an environment.
PASSWORDS = {"admin": "admin", "platform": "platform", "developer": "dev"}


class AlreadySeeded(Exception):
    """Raised when seeding a store that already has users."""


def seed(conn: sqlite3.Connection) -> dict:
    if count_users(conn) > 0:
        raise AlreadySeeded("seed expects an empty database")

    audit = SqliteSink(conn)
    admin, admin_tok = create_user(conn, "admin@example.com", PASSWORDS["admin"], "admin")
    platform, platform_tok = create_user(conn, "platform@example.com",
                                         PASSWORDS["platform"], "platform")
    dev, dev_tok = create_user(conn, "dev@example.com", PASSWORDS["developer"], "developer")

    web = create_repository(conn, "web-app", "git@github.com:acme/web-app.git", dev.id)

    kanban = create_process(
        conn, "Kanban", "board", ["backlog", "in-progress", "review", "done"],
        platform.id, oversight="supervised", gates=["done"],
    )

    # One item moved partway, one fresh in the backlog — a non-empty board.
    login = create_work_item(conn, web.id, kanban.id, "Add login page", dev.id)
    transition(conn, login.id, "in-progress", dev.id, audit)
    create_work_item(conn, web.id, kanban.id, "Rate-limit the public API", dev.id)

    # A model target with **no credential**, routed to the kanban process. The
    # executor falls back to its echo stub when a target has no key, so
    # `POST /execute` works on a fresh clone with no network and no API key —
    # which is what makes the loop testable before anyone has connected
    # anything. Add a real key in Settings → Connections to make it live.
    model = create_target(conn, "claude (stub until a key is added)", "model",
                          "claude-sonnet-5", platform.id, unit_cost=1)
    create_route(conn, kanban.id, model.id, platform.id, priority=10)

    # seeded orgs are already configured — skip the first-run wizard
    set_setting(conn, "org.onboarded", "true", admin.id)

    return {
        "users": {
            "admin": (admin, admin_tok),
            "platform": (platform, platform_tok),
            "developer": (dev, dev_tok),
        },
        "repositories": [web],
        "processes": [kanban],
        "targets": [model],
    }
