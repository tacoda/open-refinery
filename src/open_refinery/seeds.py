"""Database seeds — a **minimal** sample dataset for local dev and tests.

`seed(conn)` populates an empty store with the three default-role users, one
repository, and a couple of work items — just enough to sign in and see the app
working. `owner_email` adds a fourth account holding **every** permission, for
dogfooding against a live account: testing the whole product means reaching all
of it, and no preset does. Everything richer (standards, governed artifacts) ships as **packs**,
enabled on demand. Returns the created objects and the users' tokens so a caller
can sign in.

A fresh production install seeds none of this: it goes to the setup wizard (or
`open-refinery create-admin`). `seed` is dev/eval only.
"""

from __future__ import annotations

import sqlite3

from .repositories import create_repository
from .settings import set_setting
from .users import count_users, create_user
from .work_items import create_work_item

# Dev passwords, fixed and obvious. `seed` is dev/eval only — a production
# install goes to the setup wizard — and a developer who cannot sign in to the
# thing they just seeded has been given a database, not an environment.
PASSWORDS = {"admin": "admin", "platform": "platform", "developer": "dev",
             "owner": "owner"}

# Deliberately generic. A real address here would ship in the package and turn
# up in every contributor's dev database — pass `--owner you@example.com`
# (or `make seed OWNER=…`) to seed your own.
DEFAULT_OWNER = "owner@example.com"


class AlreadySeeded(Exception):
    """Raised when seeding a store that already has users."""


def seed(conn: sqlite3.Connection, *, owner_email: str = DEFAULT_OWNER) -> dict:
    if count_users(conn) > 0:
        raise AlreadySeeded("seed expects an empty database")

    # The owner holds everything, the way `POST /setup`'s first account does.
    # A preset cannot stand in: no single one reaches every screen, which is the
    # point of an account you dogfood with.
    from .authority import PERMISSIONS

    owner, owner_tok = create_user(conn, owner_email, PASSWORDS["owner"], "admin",
                                   permissions=list(PERMISSIONS))
    admin, admin_tok = create_user(conn, "admin@example.com", PASSWORDS["admin"], "admin")
    platform, platform_tok = create_user(conn, "platform@example.com",
                                         PASSWORDS["platform"], "platform")
    dev, dev_tok = create_user(conn, "dev@example.com", PASSWORDS["developer"], "developer")

    web = create_repository(conn, "web-app", "git@github.com:acme/web-app.git", dev.id)

    # The default pipeline, so a seeded environment can actually run something.
    # `POST /setup` does this for a real install; without it here, "Ship work"
    # on a seeded dev box 404s on a pipeline that was never made.
    from .pipeline import store as ps
    pipeline = ps.ensure_default(conn, platform.id)

    # Two tickets, neither run yet: both show as `open` until somebody starts a
    # run, which is what the board now reads off.
    items = [create_work_item(conn, web.id, "Add login page", dev.id),
             create_work_item(conn, web.id, "Rate-limit the public API", dev.id)]

    # seeded orgs are already configured — skip the first-run wizard
    set_setting(conn, "org.onboarded", "true", admin.id)

    return {
        "users": {
            "owner": (owner, owner_tok),
            "admin": (admin, admin_tok),
            "platform": (platform, platform_tok),
            "developer": (dev, dev_tok),
        },
        "repositories": [web],
        "work_items": items,
        "pipelines": [pipeline],
    }
