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

import subprocess
import sqlite3
from pathlib import Path

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

# A git URL nobody can clone. Used when no checkout is made — tests, mostly.
PLACEHOLDER_GIT_URL = "git@github.com:acme/web-app.git"


def make_checkout(path: str | Path) -> str:
    """A real git repository for the seeded repo to point at.

    **`workspace.root_of` refuses a `git_url` that is not a local checkout**, so
    without this the first thing a new arrival does — name a ticket and ship it
    — fails on a worktree that cannot be made. Seeding a repository the factory
    cannot actually run against is seeding a broken demo.

    Idempotent: an existing checkout is left alone. Returns the path as the
    `git_url`, which is what a `local` repository's git URL *is*.
    """
    root = Path(path).expanduser().resolve()
    if (root / ".git").exists():
        return str(root)
    root.mkdir(parents=True, exist_ok=True)

    def git(*args):
        subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)

    git("init", "-q", "-b", "main")
    # Local identity, so seeding does not depend on the machine's git config.
    git("config", "user.email", "dev@example.com")
    git("config", "user.name", "open-refinery dev")
    (root / "README.md").write_text(
        "# web-app\n\nA throwaway repository, so the factory has something real "
        "to work on.\n")
    (root / "app.py").write_text("def add(a, b):\n    return a + b\n")
    git("add", "-A")
    git("commit", "-q", "-m", "first")
    return str(root)


class AlreadySeeded(Exception):
    """Raised when seeding a store that already has users."""


def seed(conn: sqlite3.Connection, *, owner_email: str = DEFAULT_OWNER,
         git_url: str = PLACEHOLDER_GIT_URL) -> dict:
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

    # `forge` stays "" — a path with no recognisable host resolves to `local`,
    # so a pull request is a markdown file and the loop needs no accounts.
    web = create_repository(conn, "web-app", git_url, dev.id)

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
