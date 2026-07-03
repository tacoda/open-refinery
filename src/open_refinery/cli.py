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

    port = int(os.environ.get("PORT", args.port))
    uvicorn.run(create_app_from_env(), host=args.host, port=port)
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
    serve.add_argument("--host", default="0.0.0.0")
    serve.add_argument("--port", type=int, default=8000)
    serve.set_defaults(func=_serve)

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
