"""CLI — server maintenance runs against the database; everything else goes
through the API (see `client.py`)."""

from __future__ import annotations

import argparse
import json
import logging
import os



def _serve(args: argparse.Namespace) -> int:
    import uvicorn

    from .config import get as setting
    from .web import create_app_from_env

    # precedence: --port flag > PORT env > default 8000
    port = args.port if args.port is not None else int(setting("PORT"))
    host = args.host or setting("HOST")
    uvicorn.run(create_app_from_env(), host=host, port=port,
                log_level=setting("LOG_LEVEL").lower())
    return 0


def _open_session(url: str):
    """A session on the store, or None when it cannot be opened.

    `doctor` and `config` must work on a broken or absent database — reporting
    that it is broken is most of their job — so a failure here is a return
    value rather than a traceback.
    """
    from .store import connect
    try:
        return connect(url)
    except Exception:  # noqa: BLE001 — the caller reports the failure as a check
        return None


def _init(args: argparse.Namespace) -> int:
    """First run: write .env with a generated SECRET_KEY, create and migrate the DB."""
    import secrets as _secrets
    import sys
    from pathlib import Path

    from .config import KEYS
    from .store import DEFAULT_DATABASE_URL, connect

    env_path = Path(args.env_file)
    if env_path.exists() and not args.force:
        print(f"{env_path} already exists — not overwriting (use --force)", file=sys.stderr)
        return 1

    secret = _secrets.token_urlsafe(32)
    url = args.database_url or os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)
    helps = {k.name: k.help for k in KEYS}
    env_path.write_text(
        "# Written by `open-refinery init`. Keep this file out of version control.\n"
        f"# SECRET_KEY: {helps['SECRET_KEY']}\n"
        f"SECRET_KEY={secret}\n"
        f"# DATABASE_URL: {helps['DATABASE_URL']}\n"
        f"DATABASE_URL={url}\n"
        "# PORT=8000\n"
        "# LOG_LEVEL=info\n"
    )
    env_path.chmod(0o600)  # it holds the key every stored secret is encrypted with

    os.environ["SECRET_KEY"] = secret  # so the store can write its encrypted rows
    os.environ["DATABASE_URL"] = url
    connect(url)  # creates tables and runs pending migrations

    print(f"wrote {env_path} (mode 600) with a generated SECRET_KEY")
    print(f"initialized {url}")
    print()
    print("next:")
    load = f"set -a; . ./{env_path}; set +a"
    print(f"  {load:<34} # load it into your shell")
    print(f"  {'open-refinery serve':<34} # then open http://localhost:8000")
    return 0


def _doctor(args: argparse.Namespace) -> int:
    from .doctor import FAIL, OK, WARN, doctor
    from .store import DEFAULT_DATABASE_URL

    url = os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)
    report = doctor(_open_session(url), database_url=url)

    mark = {OK: "ok  ", WARN: "warn", FAIL: "FAIL"}
    for c in report.checks:
        print(f"[{mark[c.status]}] {c.name:<14} {c.detail}")
        if c.remedy:
            print(f"{'':>21}→ {c.remedy}")
    counts = report.counts
    print()
    print(f"{counts[OK]} ok, {counts[WARN]} warning(s), {counts[FAIL]} failure(s)")
    return 1 if report.failed else 0


def _config(args: argparse.Namespace) -> int:
    from .config import effective
    from .store import DEFAULT_DATABASE_URL

    url = os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)
    values = effective(_open_session(url))
    if args.all is False:
        values = [v for v in values if v.is_set]

    width = max((len(v.key) for v in values), default=0)
    for v in values:
        print(f"{v.key:<{width}}  {v.value or '—':<28} [{v.source}]")
        if args.verbose:
            print(f"{'':<{width}}  {v.help}")
    if not values:
        print("nothing configured beyond the built-in defaults (use --all to see them)")
    return 0


# --- application commands: through the API, never around it (see client.py) ---

def _client(args):
    from .client import Client
    return Client(getattr(args, "url", None), getattr(args, "token", None))


def _credentials(args: argparse.Namespace) -> int:
    import sys

    from .client import ApiError

    api = _client(args)
    try:
        if args.cred_cmd == "catalog":
            for p in api.get("/credentials/catalog", **({"family": args.family} if args.family else {})):
                mark = " (shareable)" if p["shareable"] else ""
                print(f"{p['key']:<15} {p['family']:<8} {p['label']}{mark}")
                print(f"{'':<15} needs: {p['needs']}")
                if p["mint_url"]:
                    print(f"{'':<15} mint:  {p['mint_url']}")
            return 0

        if args.cred_cmd == "list":
            rows = api.get("/credentials", **({"family": args.family} if args.family else {}))
            if not rows:
                print("nothing connected. `open-refinery credentials catalog` lists what you can add.")
                return 0
            for r in rows:
                flags = " shared" if r["shared"] else ""
                warn = f"  ← {r['status_detail']}" if r["status"] != "ok" else ""
                print(f"{r['id'][:8]}  {r['provider']:<15} {r['account']:<24} "
                      f"[{r['status']}]{flags}{warn}")
            return 0

        if args.cred_cmd == "add":
            fields = dict(kv.split("=", 1) for kv in args.field)
            row = api.post("/credentials", {"provider": args.provider,
                                            "credential": fields,
                                            "shared": args.shared})
            print(f"connected {row['provider']} as {row['account']} ({row['id'][:8]})")
            return 0

        if args.cred_cmd == "verify":
            row = api.post(f"/credentials/{args.id}/verify")
            print(f"{row['provider']}: {row['status']} {row['status_detail']}".rstrip())
            return 0 if row["status"] == "ok" else 1

        if args.cred_cmd == "rotate":
            fields = dict(kv.split("=", 1) for kv in args.field)
            row = api.put(f"/credentials/{args.id}", {"credential": fields})
            print(f"rotated {row['provider']} ({row['id'][:8]})")
            return 0

        if args.cred_cmd == "rm":
            api.delete(f"/credentials/{args.id}")
            print("revoked")
            return 0
    except ApiError as exc:
        print(f"error: {exc.detail}", file=sys.stderr)
        return 1
    return 0


def _roles(args: argparse.Namespace) -> int:
    import sys

    from .client import ApiError

    api = _client(args)
    try:
        if args.role_cmd == "list":
            for r in api.get("/roles"):
                powers = []
                if r.get("approves"):
                    powers.append("approves " + ",".join(r["approves"]))
                if r.get("manages_users"):
                    powers.append("manages users")
                if r.get("reads_audit"):
                    powers.append("reads audit")
                if r.get("sees_operations"):
                    powers.append("sees operations")
                mark = "*" if r.get("builtin") else " "
                print(f"{mark}{r['name']:<12} {'; '.join(powers) or '—'}")
            print("\n* built-in (the standard configuration)")
            return 0

        if args.role_cmd == "layers":
            print(" ".join(api.get("/roles/layers")["layers"]))
            return 0

        if args.role_cmd == "set":
            body = {"rank": args.rank}
            if args.approves is not None:
                body["approves"] = [x for x in args.approves.split(",") if x]
            if args.proposes is not None:
                body["proposes"] = [x for x in args.proposes.split(",") if x]
            for flag in ("manages_users", "reads_audit", "sees_operations"):
                value = getattr(args, flag)
                if value is not None:
                    body[flag] = value
            r = api.put(f"/roles/{args.name}", body)
            print(f"{r['name']}: approves {r['approves'] or '—'}, proposes {r['proposes'] or '—'}")
            return 0

        if args.role_cmd == "rm":
            api.delete(f"/roles/{args.name}")
            print("deleted")
            return 0
    except ApiError as exc:
        print(f"error: {exc.detail}", file=sys.stderr)
        return 1
    return 0


def _create_admin(args: argparse.Namespace) -> int:
    import getpass
    import sys

    from .store import DEFAULT_DATABASE_URL, connect
    from .users import DuplicateUser, create_user

    password = args.password or getpass.getpass("admin password: ")
    conn = connect(os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL))
    try:
        user, token = create_user(conn, args.email, password, "admin")
    except DuplicateUser:
        print(f"error: a user with email {args.email!r} already exists", file=sys.stderr)
        return 1

    print(f"created admin {user.email}")
    print(f"token: {token}")
    print("save this token now — it is shown only once")
    return 0


def _openapi(args: argparse.Namespace) -> int:
    """Print the OpenAPI spec — used by the build to generate TS types + docs."""
    import json

    from .web import create_app

    app = create_app(database_url="sqlite:///:memory:")
    print(json.dumps(app.openapi()))
    return 0


def _migrate(args: argparse.Namespace) -> int:
    """Migrate the database up (default: latest) or down to a pinned version."""
    import sqlite3
    import sys

    from .migrations import MIGRATIONS, migrate_to
    from .store import DEFAULT_DATABASE_URL, _sqlite_path, engine_for

    url = os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)
    path = _sqlite_path(url)

    def _version() -> int | None:
        if not path or path == ":memory:" or not os.path.exists(path):
            return None
        conn = sqlite3.connect(path)
        try:
            return conn.execute("PRAGMA user_version").fetchone()[0]
        finally:
            conn.close()

    before = _version()
    engine_for(url)  # ensure tables exist + apply pending up-migrations
    latest = len(MIGRATIONS)
    target = latest if args.to is None else args.to
    if target < 0 or target > latest:
        print(f"error: --to must be between 0 and {latest}", file=sys.stderr)
        return 1

    current = _version() or 0
    if target < current and not args.yes:
        print(f"refusing to downgrade {current} → {target}: this DROPS columns and their data.\n"
              f"re-run with --yes to confirm.", file=sys.stderr)
        return 1

    if target != current:
        conn = sqlite3.connect(path)
        try:
            migrate_to(conn, target)
        finally:
            conn.close()

    after = _version()
    if before is None:
        print(f"initialized database (schema v{after})")
    elif after == before:
        print(f"database up to date (schema v{after})")
    else:
        print(f"migrated schema {before} → {after}")
    return 0


def _seed(args: argparse.Namespace) -> int:
    import sys

    from .seeds import AlreadySeeded, seed
    from .store import DEFAULT_DATABASE_URL, connect

    conn = connect(os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL))
    try:
        data = seed(conn)
    except AlreadySeeded:
        print("database already has users; seed needs a fresh DATABASE_URL", file=sys.stderr)
        return 1
    from .seeds import PASSWORDS

    print("seeded sample data.\n")
    print(f"  {'role':<9} {'email':<24} {'password':<10} api token")
    for role, (user, token) in data["users"].items():
        print(f"  {role:<9} {user.email:<24} {PASSWORDS[role]:<10} {token}")
    print()
    print(f"  {len(data['repositories'])} repo · {len(data['processes'])} process · "
          f"{len(data['targets'])} target (no key — runs on the echo stub)")
    print()
    print("next:")
    print(f"  {'make dev':<34} # then sign in at http://localhost:8000")
    print(f"  {'make reseed':<34} # start over with a fresh database")
    return 0


def _packs(args: argparse.Namespace) -> int:
    import sys

    from .packs import disable_pack, enable_pack, list_packs
    from .store import DEFAULT_DATABASE_URL, connect
    from .users import user_by_email

    conn = connect(os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL))
    if args.pack_cmd == "list":
        for p in list_packs(conn):
            mark = "x" if p["enabled"] else " "
            print(f"[{mark}] {p['key']:18} {p['role']:9} {p['title']}")
        return 0

    actor = user_by_email(conn, args.as_user)
    if actor is None:
        print(f"error: no user with email {args.as_user!r}", file=sys.stderr)
        return 1
    try:
        fn = enable_pack if args.pack_cmd == "enable" else disable_pack
        state = fn(conn, args.key, actor)
    except Exception as exc:  # PolicyDenied / unknown pack
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"{args.key} enabled={state['enabled']}")
    return 0



def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="open-refinery")
    sub = parser.add_subparsers(dest="command")

    init = sub.add_parser("init", help="first run: write .env and create the database")
    init.add_argument("--env-file", default=".env", help="where to write it (default: .env)")
    init.add_argument("--database-url", default=None, help="override DATABASE_URL")
    init.add_argument("--force", action="store_true", help="overwrite an existing env file")
    init.set_defaults(func=_init)

    doctor = sub.add_parser("doctor", help="check what is missing or broken")
    doctor.set_defaults(func=_doctor)

    config = sub.add_parser("config", help="print every effective setting and its source")
    config.add_argument("--all", action="store_true", help="include values still at their default")
    config.add_argument("--verbose", "-v", action="store_true", help="explain each setting")
    config.set_defaults(func=_config)

    serve = sub.add_parser("serve", help="run the HTTP API")
    serve.add_argument("--host", default=None, help="bind host (or $HOST, default 0.0.0.0)")
    serve.add_argument("--port", type=int, default=None, help="bind port (or $PORT, default 8000)")
    serve.set_defaults(func=_serve)

    creds = sub.add_parser("credentials", help="connect and manage service keys (via the API)")
    creds.add_argument("--url", default=None, help="server URL (or $OPEN_REFINERY_URL)")
    creds.add_argument("--token", default=None, help="API token (or $OPEN_REFINERY_TOKEN)")
    cred_sub = creds.add_subparsers(dest="cred_cmd", required=True)

    cred_sub.add_parser("catalog", help="what can be connected, and what each key needs") \
            .add_argument("--family", choices=("model", "forge", "tracker"), default=None)
    cred_sub.add_parser("list", help="your connected services") \
            .add_argument("--family", choices=("model", "forge", "tracker"), default=None)

    c_add = cred_sub.add_parser("add", help="connect a service: add github token=ghp_…")
    c_add.add_argument("provider")
    c_add.add_argument("field", nargs="*", metavar="key=value",
                       help="omit entirely for a provider that needs no key (e.g. local)")
    c_add.add_argument("--shared", action="store_true",
                       help="publish org-wide (platform only; model keys only)")

    cred_sub.add_parser("verify", help="re-check a stored credential").add_argument("id")
    c_rot = cred_sub.add_parser("rotate", help="replace the secret, keeping the same id")
    c_rot.add_argument("id")
    c_rot.add_argument("field", nargs="+", metavar="key=value")
    cred_sub.add_parser("rm", help="revoke a credential").add_argument("id")
    creds.set_defaults(func=_credentials)

    roles = sub.add_parser("roles", help="define roles and what they may do (via the API)")
    roles.add_argument("--url", default=None, help="server URL (or $OPEN_REFINERY_URL)")
    roles.add_argument("--token", default=None, help="API token (or $OPEN_REFINERY_TOKEN)")
    role_sub = roles.add_subparsers(dest="role_cmd", required=True)

    role_sub.add_parser("list", help="every role and its powers")
    role_sub.add_parser("layers", help="what a role's authority can be about")

    r_set = role_sub.add_parser("set", help="create or update a role")
    r_set.add_argument("name")
    r_set.add_argument("--rank", type=int, default=1, help="ordering for approval chains")
    r_set.add_argument("--approves", default=None, metavar="code,harness,…")
    r_set.add_argument("--proposes", default=None, metavar="code,harness,…")
    for flag in ("manages-users", "reads-audit", "sees-operations"):
        dest = flag.replace("-", "_")
        r_set.add_argument(f"--{flag}", dest=dest, action="store_true", default=None)
        r_set.add_argument(f"--no-{flag}", dest=dest, action="store_false", default=None)

    role_sub.add_parser("rm", help="delete a custom role").add_argument("name")
    roles.set_defaults(func=_roles)

    admin = sub.add_parser("create-admin", help="create the initial admin user")
    admin.add_argument("--email", required=True)
    admin.add_argument("--password", default=None, help="omit to be prompted securely")
    admin.set_defaults(func=_create_admin)

    seed = sub.add_parser("seed", help="populate the database with sample data (dev)")
    seed.set_defaults(func=_seed)

    migrate = sub.add_parser("migrate", help="migrate the schema up (default) or down to --to N")
    migrate.add_argument("--to", type=int, default=None, help="target schema version (default: latest)")
    migrate.add_argument("--yes", action="store_true", help="confirm a destructive downgrade")
    migrate.set_defaults(func=_migrate)

    packs = sub.add_parser("packs", help="list or enable/disable topic packs")
    packs.add_argument("pack_cmd", choices=("list", "enable", "disable"))
    packs.add_argument("key", nargs="?", help="pack key (for enable/disable)")
    packs.add_argument("--as-user", help="acting user's email (role-gated; enable/disable)")
    packs.set_defaults(func=_packs)

    openapi = sub.add_parser("openapi", help="print the OpenAPI spec (build tooling)")
    openapi.set_defaults(func=_openapi)


    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
