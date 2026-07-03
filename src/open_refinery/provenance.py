"""Provenance record — the governance metadata attached to every produced artifact."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone


def _digest(value: object) -> str:
    """Stable SHA-256 of any JSON-serializable value; repr fallback for the rest."""
    try:
        payload = json.dumps(value, sort_keys=True, default=repr)
    except TypeError:
        payload = repr(value)
    return hashlib.sha256(payload.encode()).hexdigest()


@dataclass(frozen=True)
class Record:
    """Immutable provenance for a single production event."""

    recipe: str
    actor: str
    owner: str
    input_digest: str
    output_digest: str
    artifact_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @classmethod
    def of(cls, recipe: str, actor: str, owner: str, inputs: dict, output: object) -> Record:
        return cls(
            recipe=recipe,
            actor=actor,
            owner=owner,
            input_digest=_digest(inputs),
            output_digest=_digest(output),
        )

    def to_dict(self) -> dict:
        return asdict(self)
