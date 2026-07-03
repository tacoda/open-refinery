"""Database seeds — a realistic sample dataset for local dev and tests.

`seed(conn)` populates an empty store with users (one per role), repositories,
a supervised kanban and an assisted doctrine process, and work items moved
through them (with approvals and attestations recorded). Returns the created
objects and the users' tokens so a caller can sign in.
"""

from __future__ import annotations

import sqlite3

from .attestations import attest
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
    api = create_repository(conn, "api", "git@github.com:acme/api.git", dev.id)

    kanban = create_process(
        conn, "Kanban", "board", ["backlog", "in-progress", "review", "done"],
        platform.id, oversight="supervised", gates=["done"],
    )
    remediation = create_process(
        conn, "Vuln Remediation", "doctrine",
        ["detect", "triage", "patch", "verify", "close"], platform.id,
        transitions=[("detect", "triage"), ("triage", "patch"), ("patch", "verify"),
                     ("verify", "close"), ("verify", "patch")],  # verify->patch feedback loop
        oversight="assisted", checks={"close": ["tests", "security-review"]},
    )

    # Kanban item: free moves; entering the gated "done" step needs approval.
    login = create_work_item(conn, web.id, kanban.id, "Add login page", dev.id)
    transition(conn, login.id, "in-progress", dev.id, audit)
    transition(conn, login.id, "review", dev.id, audit)

    # Doctrine item (assisted): every move needs an approver; closing needs checks.
    cve = create_work_item(conn, api.id, remediation.id, "CVE-2026-1234", dev.id)
    transition(conn, cve.id, "triage", dev.id, audit, approver_id=platform.id)
    transition(conn, cve.id, "patch", dev.id, audit, approver_id=platform.id)
    transition(conn, cve.id, "verify", dev.id, audit, approver_id=platform.id)
    attest(conn, cve.id, "tests", dev.id, True, audit)
    attest(conn, cve.id, "security-review", platform.id, True, audit)
    transition(conn, cve.id, "close", dev.id, audit, approver_id=platform.id)

    # One fresh item left at the start, for a non-empty backlog.
    create_work_item(conn, api.id, kanban.id, "Rate-limit the public API", dev.id)

    return {
        "users": {
            "admin": (admin, admin_tok),
            "platform": (platform, platform_tok),
            "developer": (dev, dev_tok),
        },
        "repositories": [web, api],
        "processes": [kanban, remediation],
    }
