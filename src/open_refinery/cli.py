"""Demo CLI — produces one artifact and prints its provenance record."""

from __future__ import annotations

import argparse
import json
import logging

from .factory import Factory


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="open-refinery")
    parser.add_argument("--actor", default="demo-user")
    parser.add_argument("--text", default="hello", help="text to refine")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    factory = Factory()

    @factory.recipe("upper")
    def upper(text: str) -> str:
        return text.upper()

    artifact, record = factory.produce("upper", actor=args.actor, text=args.text)
    print(f"artifact: {artifact!r}")
    print(json.dumps(record.to_dict(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
