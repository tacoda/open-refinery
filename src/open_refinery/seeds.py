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
from .store import SqliteSink
from .users import count_users, create_user
from .work_items import create_work_item, transition


class AlreadySeeded(Exception):
    """Raised when seeding a store that already has users."""


def seed(conn: sqlite3.Connection) -> dict:
    if count_users(conn) > 0:
        raise AlreadySeeded("seed expects an empty database")

    audit = SqliteSink(conn)
    admin, admin_tok = create_user(conn, "admin@example.com", "admin", "admin")
    platform, platform_tok = create_user(conn, "platform@example.com", "platform", "platform")
    dev, dev_tok = create_user(conn, "dev@example.com", "dev", "developer")

    web = create_repository(conn, "web-app", "git@github.com:acme/web-app.git", dev.id)

    kanban = create_process(
        conn, "Kanban", "board", ["backlog", "in-progress", "review", "done"],
        platform.id, oversight="supervised", gates=["done"],
    )

    # One item moved partway, one fresh in the backlog — a non-empty board.
    login = create_work_item(conn, web.id, kanban.id, "Add login page", dev.id)
    transition(conn, login.id, "in-progress", dev.id, audit)
    create_work_item(conn, web.id, kanban.id, "Rate-limit the public API", dev.id)

    return {
        "users": {
            "admin": (admin, admin_tok),
            "platform": (platform, platform_tok),
            "developer": (dev, dev_tok),
        },
        "repositories": [web],
        "processes": [kanban],
    }
