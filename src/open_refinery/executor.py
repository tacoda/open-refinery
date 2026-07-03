"""Executor — the governed call site where a step reaches a target.

`execute()` runs the full outbound pipeline for a process/step: resolve the
route, authorize the invocation (role-based policy), consume quota, inject the
target's decrypted secret (never surfaced), content-filter the payload and
response, call a pluggable backend, and audit the call — with failover across
routes when a backend fails. Real model/MCP/API backends register in
`EXECUTORS`; a stub ships by default.
"""

from __future__ import annotations

from sqlmodel import Session

from .audit import AuditSink
from .models import User
from .policies import enforce as enforce_policy
from .policies import scan_content
from .provenance import Record
from .targets import consume_quota, resolve_targets, target_credential


class ExecutionError(Exception):
    """Raised when no route resolves or every candidate target fails."""


def stub_backend(target, credential, payload: str) -> dict:
    """Default backend — echoes; real providers register their own in EXECUTORS."""
    return {"output": f"[{target.kind}:{target.endpoint}] {payload}", "units": 1}


EXECUTORS = {"model": stub_backend, "mcp": stub_backend, "api": stub_backend}


def execute(session: Session, actor_id: str, process_id: str, payload: str, audit: AuditSink,
            *, step: str | None = None, work_item_id: str | None = None) -> dict:
    actor = session.get(User, actor_id)
    if actor is None:
        raise ValueError(f"unknown actor: {actor_id!r}")

    targets = resolve_targets(session, process_id, step)
    if not targets:
        raise ExecutionError(f"no route for process {process_id!r} step {step!r}")

    clean_in, in_hits = scan_content(payload)  # filter before anything leaves
    errors: list[str] = []
    for target in targets:
        # role-based authorization to invoke this target kind (deny aborts, no failover)
        enforce_policy(session, actor.role, "invoke", target.kind)
        consume_quota(session, target.id)                 # pre-call; over → QuotaExceeded
        credential = target_credential(session, target.id)  # decrypted here, never returned
        try:
            result = EXECUTORS[target.kind](target, credential, clean_in)
        except Exception as exc:  # backend failure → try the next route
            errors.append(f"{target.name}: {exc}")
            audit.write(Record.of(
                recipe="invoke-failed", actor=actor_id, owner=actor_id,
                inputs={"target": target.id, "step": step}, output=str(exc), subject=work_item_id))
            continue

        clean_out, out_hits = scan_content(str(result.get("output", "")))
        units = int(result.get("units", 1))
        redactions = in_hits + out_hits
        audit.write(Record.of(
            recipe="invoke", actor=actor_id, owner=actor_id,
            inputs={"target": target.id, "step": step, "units": units, "redactions": redactions},
            output=clean_out, subject=work_item_id))
        return {"output": clean_out, "target": target.name, "kind": target.kind,
                "units": units, "redactions": redactions}

    raise ExecutionError("all candidate targets failed: " + "; ".join(errors))
