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
    """Raised when no route resolves, a target's output fails its schema, or
    every candidate target fails."""


_JSON_TYPES = {"string": str, "number": (int, float), "integer": int,
               "boolean": bool, "object": dict, "array": list}


def validate_schema(obj, schema: dict) -> None:
    """Minimal JSON-schema check: object, required keys present, declared types.

    ponytail: covers required + top-level property types — enough to enforce a
    structured contract. Swap in `jsonschema` if richer validation is needed.
    """
    if not isinstance(obj, dict):
        raise ExecutionError("structured output must be a JSON object")
    for key in schema.get("required", []):
        if key not in obj:
            raise ExecutionError(f"structured output missing required key {key!r}")
    for key, spec in schema.get("properties", {}).items():
        expected = spec.get("type") if isinstance(spec, dict) else None
        if key in obj and expected in _JSON_TYPES and not isinstance(obj[key], _JSON_TYPES[expected]):
            raise ExecutionError(f"structured output {key!r} must be {expected}")


def _filter_value(value):
    """Content-filter string leaves anywhere in a structured value."""
    if isinstance(value, str):
        return scan_content(value)  # (clean, hits)
    if isinstance(value, dict):
        out, hits = {}, []
        for k, v in value.items():
            out[k], h = _filter_value(v)
            hits += h
        return out, hits
    if isinstance(value, list):
        out, hits = [], []
        for v in value:
            cv, h = _filter_value(v)
            out.append(cv); hits += h
        return out, hits
    return value, []


def stub_backend(target, credential, payload: str) -> dict:
    """Default backend — echoes; real providers register their own in EXECUTORS."""
    return {"output": f"[{target.kind}:{target.endpoint}] {payload}", "units": 1}


DEFAULT_ANTHROPIC_MODEL = "claude-opus-4-8"


def _key(credential: dict) -> str | None:
    """A target's secret, however it was connected — API key or OAuth token."""
    return credential.get("api_key") or credential.get("token") or credential.get("access_token")


def _provider(target, credential: dict) -> str:
    """Which model provider a target uses — explicit credential wins, else the
    model-id prefix on the endpoint."""
    if credential.get("provider"):
        return credential["provider"]
    ep = (target.endpoint or "").lower()
    if ep.startswith("claude") or ep.startswith("anthropic"):
        return "anthropic"
    if ep.startswith(("gpt", "o1", "o3", "o4")):
        return "openai"
    return ""


def anthropic_backend(target, credential: dict, payload: str) -> dict:
    """Real Anthropic Messages API call. Honors a target's output_schema via
    structured outputs. Returns {"output": text|dict, "units": output_tokens}."""
    try:
        import anthropic
    except ModuleNotFoundError as exc:  # optional dependency
        raise RuntimeError("anthropic SDK not installed — `pip install open-refinery[providers]`") from exc

    client = anthropic.Anthropic(api_key=_key(credential))
    model = target.endpoint or DEFAULT_ANTHROPIC_MODEL

    kwargs: dict = {"model": model, "max_tokens": 16000,
                    "messages": [{"role": "user", "content": payload}]}
    if target.output_schema:  # constrain the response to the declared shape
        kwargs["output_config"] = {"format": {"type": "json_schema", "schema": target.output_schema}}

    resp = client.messages.create(**kwargs)
    if getattr(resp, "stop_reason", None) == "refusal":
        raise RuntimeError("model refused the request")

    text = next((b.text for b in resp.content if getattr(b, "type", None) == "text"), "")
    if target.output_schema:
        import json
        output = json.loads(text)  # format guarantees valid JSON
    else:
        output = text
    units = getattr(resp.usage, "output_tokens", 0) or 0
    return {"output": output, "units": int(units)}


def openai_backend(target, credential: dict, payload: str) -> dict:
    """Real OpenAI Chat Completions call. Honors output_schema via a json_schema
    response format. Returns {"output": text|dict, "units": completion_tokens}."""
    try:
        import openai
    except ModuleNotFoundError as exc:  # optional dependency
        raise RuntimeError("openai SDK not installed — `pip install open-refinery[providers]`") from exc

    client = openai.OpenAI(api_key=_key(credential))
    kwargs: dict = {"model": target.endpoint, "max_tokens": 16000,
                    "messages": [{"role": "user", "content": payload}]}
    if target.output_schema:
        kwargs["response_format"] = {"type": "json_schema", "json_schema": {
            "name": "output", "schema": target.output_schema, "strict": True}}

    resp = client.chat.completions.create(**kwargs)
    text = resp.choices[0].message.content or ""
    if target.output_schema:
        import json
        output = json.loads(text)
    else:
        output = text
    units = getattr(resp.usage, "completion_tokens", 0) or 0
    return {"output": output, "units": int(units)}


# Registered model providers, connected by API key or OAuth token. MCP/API keep
# the stub until their transports land.
MODEL_BACKENDS = {"anthropic": anthropic_backend, "openai": openai_backend}


def model_backend(target, credential: dict, payload: str) -> dict:
    """Dispatch a model target to its provider; fall back to the stub when there's
    no credential or no real backend (keeps a fresh install working offline)."""
    provider = _provider(target, credential)
    backend = MODEL_BACKENDS.get(provider)
    if backend is None or not _key(credential):
        return stub_backend(target, credential, payload)
    return backend(target, credential, payload)


def _http_post(url: str, body: bytes, headers: dict) -> tuple[int, str]:
    import urllib.request
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status, r.read().decode("utf-8", "replace")


def _parse_jsonrpc(text: str) -> dict:
    """Parse a JSON-RPC reply, tolerating SSE framing (Streamable HTTP)."""
    import json
    if "data:" in text:  # SSE: take the last data line
        data = [ln[5:].strip() for ln in text.splitlines() if ln.startswith("data:")]
        if data:
            text = data[-1]
    return json.loads(text)


def mcp_backend(target, credential: dict, payload: str, *, poster=None) -> dict:
    """Call an MCP server's `tools/call` (JSON-RPC over HTTP). Payload is JSON
    `{"tool": name, "arguments": {...}}` (a bare string is treated as the tool
    name). Connects by API key or OAuth token. Honors output_schema when the
    server returns structuredContent."""
    import json
    poster = poster or _http_post
    try:
        req = json.loads(payload)
    except (ValueError, TypeError):
        req = {"tool": payload, "arguments": {}}

    rpc = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
           "params": {"name": req.get("tool") or req.get("name"),
                      "arguments": req.get("arguments", {})}}
    headers = {"Content-Type": "application/json",
               "Accept": "application/json, text/event-stream"}
    key = _key(credential)
    if key:
        headers["Authorization"] = f"Bearer {key}"

    _, text = poster(target.endpoint, json.dumps(rpc).encode(), headers)
    msg = _parse_jsonrpc(text)
    if "error" in msg:
        raise RuntimeError(f"MCP error: {msg['error'].get('message', 'unknown')}")

    result = msg.get("result", {})
    if target.output_schema and isinstance(result.get("structuredContent"), dict):
        return {"output": result["structuredContent"], "units": 1}
    content = result.get("content", [])
    out = ("".join(c.get("text", "") for c in content if c.get("type") == "text")
           if isinstance(content, list) else str(result))
    return {"output": out, "units": 1}


def api_backend(target, credential: dict, payload: str, *, poster=None) -> dict:
    """Generic HTTP API target — POST the payload to the endpoint. Connects by API
    key or OAuth token; honors output_schema by parsing the JSON response."""
    import json
    poster = poster or _http_post
    headers = {"Content-Type": "application/json"}
    key = _key(credential)
    if key:
        headers["Authorization"] = f"Bearer {key}"
    status, text = poster(target.endpoint, payload.encode(), headers)
    if status >= 400:
        raise RuntimeError(f"API target returned HTTP {status}")
    output = json.loads(text) if target.output_schema else text
    return {"output": output, "units": 1}


EXECUTORS = {"model": model_backend, "mcp": mcp_backend, "api": api_backend}


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

        raw = result.get("output", "")
        if target.output_schema:  # structured contract: validate + keep structured
            validate_schema(raw, target.output_schema)
            clean_out, out_hits = _filter_value(raw)
            structured = True
        else:
            clean_out, out_hits = scan_content(str(raw))
            structured = False
        units = int(result.get("units", 1))
        redactions = in_hits + out_hits
        audit.write(Record.of(
            recipe="invoke", actor=actor_id, owner=actor_id,
            inputs={"target": target.id, "step": step, "units": units,
                    "redactions": redactions, "structured": structured},
            output=clean_out, subject=work_item_id))
        return {"output": clean_out, "target": target.name, "kind": target.kind,
                "units": units, "redactions": redactions, "structured": structured}

    raise ExecutionError("all candidate targets failed: " + "; ".join(errors))
