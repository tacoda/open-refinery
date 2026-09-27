"""Preflight checks — what is missing, before it fails at a call site.

`doctor()` answers "why did that not work" in one place. Each check returns a
`Check` with a status and, when something is wrong, **what to do about it**: a
diagnosis with no remedy makes the reader go and find the remedy, which is the
work the check was supposed to save.

Three statuses. `ok` passed. `fail` means something is broken that stops the
product working. `warn` means something is unconfigured that only some of it
needs — no credentials on a fresh install is a warning, because an install with
nothing connected yet is a normal state and not a fault.

Every check is a function of a session (or None) and the environment, so the
whole report is testable without a running server.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field

OK, WARN, FAIL = "ok", "warn", "fail"


@dataclass(frozen=True)
class Check:
    name: str
    status: str
    detail: str
    remedy: str = ""


@dataclass
class Report:
    checks: list[Check] = field(default_factory=list)

    @property
    def failed(self) -> bool:
        return any(c.status == FAIL for c in self.checks)

    @property
    def counts(self) -> dict[str, int]:
        return {s: sum(1 for c in self.checks if c.status == s) for s in (OK, WARN, FAIL)}


def check_secret_key(environ: dict) -> Check:
    secret = environ.get("SECRET_KEY") or ""
    if not secret:
        return Check("secret key", FAIL, "SECRET_KEY is not set",
                     "run `open-refinery init`, or set SECRET_KEY before `serve`. "
                     "Without it nothing encrypted can be read or written.")
    if len(secret) < 32:
        return Check("secret key", WARN, f"SECRET_KEY is short ({len(secret)} chars)",
                     "generate one with: python -c \"import secrets; print(secrets.token_urlsafe(32))\"")
    return Check("secret key", OK, "set")


def check_database(database_url: str, session) -> Check:
    if session is None:
        return Check("database", FAIL, f"could not open {database_url}",
                     "check DATABASE_URL points somewhere writable, then `open-refinery migrate`.")
    try:
        from .migrations import MIGRATIONS
        from .users import count_users
        users = count_users(session)
    except Exception as exc:  # noqa: BLE001 — any store failure is one answer
        return Check("database", FAIL, f"{type(exc).__name__}: {exc}",
                     "run `open-refinery migrate` to bring the schema up to date.")
    who = "no users yet" if users == 0 else f"{users} user(s)"
    return Check("database", OK, f"{database_url} — schema v{len(MIGRATIONS)}, {who}")


def check_admin(session) -> Check:
    """An install with no users cannot be signed into — it needs the wizard."""
    if session is None:
        return Check("admin user", WARN, "skipped — no database")
    from .users import count_users
    if count_users(session) == 0:
        return Check("admin user", WARN, "no users yet",
                     "open the dashboard to run the setup wizard, "
                     "or `open-refinery create-admin --email you@example.com`.")
    return Check("admin user", OK, "present")


def check_git() -> Check:
    """The factory works in a git worktree; without git there is no factory."""
    path = shutil.which("git")
    if not path:
        return Check("git", FAIL, "not on PATH",
                     "install git — the factory works in a git worktree.")
    return Check("git", OK, path)


def check_providers() -> Check:
    """Model SDKs are an optional extra until a real target is called."""
    present = []
    for mod in ("anthropic", "openai"):
        try:
            __import__(mod)
            present.append(mod)
        except ModuleNotFoundError:
            pass
    if not present:
        return Check("model SDKs", WARN, "none installed",
                     "`pip install open-refinery[providers]` to call a real model. "
                     "Without one, model targets fall back to the echo stub.")
    return Check("model SDKs", OK, ", ".join(present))


def check_credentials(session) -> Check:
    """Connected services. Verified lazily — this counts them, it does not call out."""
    if session is None:
        return Check("connections", WARN, "skipped — no database")
    from .integrations import list_integrations
    integs = list_integrations(session)
    if not integs:
        return Check("connections", WARN, "nothing connected",
                     "add a code host or tracker token in the dashboard.")
    kinds = ", ".join(sorted({i.kind for i in integs}))
    return Check("connections", OK, f"{len(integs)} — {kinds}")


def check_targets(session) -> Check:
    if session is None:
        return Check("targets", WARN, "skipped — no database")
    from .targets import list_targets
    targets = list_targets(session)
    if not targets:
        return Check("targets", WARN, "no targets configured",
                     "add a model target so work has somewhere to run.")
    unset = [t.name for t in targets if not t.secret]
    if unset:
        return Check("targets", WARN,
                     f"{len(targets)} configured; no credential on: {', '.join(unset)}",
                     "add an API key to each, or they fall back to the echo stub.")
    return Check("targets", OK, f"{len(targets)} configured, all with credentials")


def check_audit_chain(session) -> Check:
    """The audit log is the product's central claim; a broken chain is a fail."""
    if session is None:
        return Check("audit chain", WARN, "skipped — no database")
    from .store import verify_chain
    try:
        result = verify_chain(session)
    except Exception as exc:  # noqa: BLE001
        return Check("audit chain", FAIL, f"{type(exc).__name__}: {exc}",
                     "the audit chain could not be read — do not trust the log until this is resolved.")
    if not result.get("ok", False):
        return Check("audit chain", FAIL,
                     f"broken at {result.get('broken_at', 'unknown')} "
                     f"({result.get('count', 0)} event(s))",
                     "the append-only log does not verify. Either it was altered — investigate "
                     "before relying on it — or SECRET_KEY was rotated, which looks identical "
                     "from here because the chain is keyed with it. Check that first.")
    return Check("audit chain", OK, f"verified, {result.get('count', 0)} event(s)")


def check_dashboard() -> Check:
    """The SPA is built into the package at release; a source checkout has none."""
    from pathlib import Path
    static = Path(__file__).parent / "static"
    if not (static / "index.html").exists():
        return Check("dashboard", WARN, "not built",
                     "`make ui` to build it. The API works without it; the UI does not.")
    return Check("dashboard", OK, str(static))


def doctor(session=None, *, environ: dict | None = None,
           database_url: str | None = None) -> Report:
    """Run every check. Order is the order a person debugs in: the things
    everything else depends on first."""
    environ = os.environ if environ is None else environ
    database_url = database_url or environ.get("DATABASE_URL") or ""
    return Report([
        check_secret_key(environ),
        check_database(database_url, session),
        check_admin(session),
        check_audit_chain(session),
        check_git(),
        check_providers(),
        check_targets(session),
        check_credentials(session),
        check_dashboard(),
    ])
