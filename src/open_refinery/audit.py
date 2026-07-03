"""Audit sink — append-only trail of production events."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

from .provenance import Record


class AuditSink(Protocol):
    def write(self, record: Record) -> None: ...


class MemorySink:
    """In-memory trail. Default; useful for tests and ephemeral runs."""

    def __init__(self) -> None:
        self.records: list[Record] = []

    def write(self, record: Record) -> None:
        self.records.append(record)


class JsonlSink:
    """Append each record as one JSON line. The durable audit trail."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, record: Record) -> None:
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record.to_dict(), sort_keys=True) + "\n")
