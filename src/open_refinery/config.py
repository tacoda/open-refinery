"""Effective configuration, and where each value came from.

Config reaches the app from three places: a built-in default, an environment
variable, or an encrypted row in the `settings` table. `effective()` resolves
all of it and **tags each value with the source that produced it**, so a default
is never a magic number somebody goes hunting for in the code, and "I set that"
can be checked rather than believed.

`KEYS` is the catalog — the one place a setting is declared. A key that is read
somewhere and missing here is a key nobody can discover, which is the failure
this module exists to prevent.

Pure apart from the environment and one optional session read, so the whole
resolution is testable without a server.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from .store import DEFAULT_DATABASE_URL

ENV = "env"          # read from the process environment
DB = "db"            # read from the encrypted settings table

MASK = "(set)"       # what a secret's value shows as; presence is the useful part


@dataclass(frozen=True)
class Key:
    """One declared setting."""

    name: str
    where: str        # ENV | DB
    default: str
    help: str
    secret: bool = False


# The catalog. Environment first (what an operator sets before `serve`), then
# the database (what admin/platform set in the UI).
KEYS: tuple[Key, ...] = (
    Key("SECRET_KEY", ENV, "", secret=True,
        help="signs session tokens and encrypts every stored secret. Required."),
    Key("DATABASE_URL", ENV, DEFAULT_DATABASE_URL,
        help="SQLite URL for the store."),
    Key("HOST", ENV, "0.0.0.0", help="bind address for `serve`."),
    Key("PORT", ENV, "8000", help="bind port for `serve`."),
    Key("LOG_LEVEL", ENV, "info", help="server log level (critical|error|warning|info|debug|trace)."),
    Key("APP_BASE_URL", ENV, "",
        help="public base URL behind a proxy. Blank = derived per request."),

    Key("org.onboarded", DB, "false",
        help="whether the first-run setup wizard has been completed."),
    Key("policy.enforcement", DB, "audit",
        help="audit = record refusals only; strict = enforce them."),
    Key("policy.strict_default", DB, "false",
        help="whether a new policy defaults to strict."),
    Key("routing.policy", DB, "",
        help="org-wide routing inputs as JSON (required region, compliance, cost preference)."),
    Key("scim.default_role", DB, "developer",
        help="role given to a SCIM-provisioned user whose groups map to nothing."),
    Key("scim.group_map", DB, "{}",
        help="IdP group → role mapping, as JSON."),
    Key("scim.token_hash", DB, "", secret=True,
        help="hash of the SCIM bearer token. Rotate in the UI."),
)

_BY_NAME = {k.name: k for k in KEYS}


@dataclass(frozen=True)
class Value:
    """One resolved setting: what it is, and which source won."""

    key: str
    value: str        # masked when `secret`
    source: str       # "default" | "env" | "database"
    secret: bool
    help: str

    @property
    def is_set(self) -> bool:
        return self.source != "default"


def _display(raw: str, key: Key) -> str:
    return MASK if (key.secret and raw) else raw


def resolve(key: Key, environ: dict, db_value: str | None) -> Value:
    """Resolve one key. A blank value does not count as set — an exported but
    empty `SECRET_KEY` is the same problem as an unset one, and reporting it as
    configured is how that hour gets lost."""
    raw, source = key.default, "default"
    if key.where == ENV:
        found = environ.get(key.name)
        if found:
            raw, source = found, "env"
    elif db_value:
        raw, source = db_value, "database"
    return Value(key=key.name, value=_display(raw, key), source=source,
                 secret=key.secret, help=key.help)


def effective(session=None, *, environ: dict | None = None) -> list[Value]:
    """Every setting, resolved, in catalog order.

    `session` is optional so `config` works before the database exists — without
    one, database-backed keys report their default.
    """
    environ = os.environ if environ is None else environ
    out = []
    for key in KEYS:
        db_value = None
        if key.where == DB and session is not None:
            from .settings import get_setting
            db_value = get_setting(session, key.name)
        out.append(resolve(key, environ, db_value))
    return out


def get(name: str, session=None, *, environ: dict | None = None) -> str:
    """One setting's real (unmasked) value — for callers that need to use it."""
    key = _BY_NAME.get(name)
    if key is None:
        raise KeyError(f"unknown setting: {name!r}")
    environ = os.environ if environ is None else environ
    if key.where == ENV:
        return environ.get(name) or key.default
    if session is not None:
        from .settings import get_setting
        return get_setting(session, name) or key.default
    return key.default
