"""CLI — `serve` runs the API; `demo` prints one provenance record."""

from __future__ import annotations

import argparse
import json
import logging
import os

from .factory import Factory


def _serve(args: argparse.Namespace) -> int:
    import uvicorn

    from .web import create_app_from_env

    # precedence: --port flag > PORT env > default 8000
    port = args.port if args.port is not None else int(os.environ.get("PORT", 8000))
    host = args.host or os.environ.get("HOST", "0.0.0.0")
    uvicorn.run(create_app_from_env(), host=host, port=port)
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
    print("seeded sample data. login tokens:")
    for role, (user, token) in data["users"].items():
        print(f"  {role:9} {user.email:22} {token}")
    return 0


def _demo(args: argparse.Namespace) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    factory = Factory()

    @factory.recipe("upper")
    def upper(text: str) -> str:
        return text.upper()

    artifact, record = factory.produce("upper", actor=args.actor, text=args.text)
    print(f"artifact: {artifact!r}")
    print(json.dumps(record.to_dict(), indent=2, sort_keys=True))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="open-refinery")
    sub = parser.add_subparsers(dest="command")

    serve = sub.add_parser("serve", help="run the HTTP API")
    serve.add_argument("--host", default=None, help="bind host (or $HOST, default 0.0.0.0)")
    serve.add_argument("--port", type=int, default=None, help="bind port (or $PORT, default 8000)")
    serve.set_defaults(func=_serve)

    admin = sub.add_parser("create-admin", help="create the initial admin user")
    admin.add_argument("--email", required=True)
    admin.add_argument("--password", default=None, help="omit to be prompted securely")
    admin.set_defaults(func=_create_admin)

    seed = sub.add_parser("seed", help="populate the database with sample data (dev)")
    seed.set_defaults(func=_seed)

    demo = sub.add_parser("demo", help="produce one artifact and print its record")
    demo.add_argument("--actor", default="demo-user")
    demo.add_argument("--text", default="hello", help="text to refine")
    demo.set_defaults(func=_demo)

    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
