import json

import pytest

from open_refinery.executor import mcp_backend
from open_refinery.models import Target


def target(output_schema=None):
    return Target(name="m", kind="mcp", endpoint="https://mcp.example/rpc", owner_id="o",
                  output_schema=output_schema or {})


def poster_returning(text):
    seen = {}

    def post(url, body, headers):
        seen["url"] = url
        seen["headers"] = headers
        seen["rpc"] = json.loads(body)
        return 200, text
    return seen, post


def test_tools_call_request_shape_and_auth():
    seen, post = poster_returning(json.dumps(
        {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": "pong"}]}}))
    payload = json.dumps({"tool": "ping", "arguments": {"x": 1}})
    out = mcp_backend(target(), {"token": "tok"}, payload, poster=post)
    assert out == {"output": "pong", "units": 1}
    assert seen["rpc"]["method"] == "tools/call"
    assert seen["rpc"]["params"] == {"name": "ping", "arguments": {"x": 1}}
    assert seen["headers"]["Authorization"] == "Bearer tok"


def test_bare_string_payload_is_tool_name():
    seen, post = poster_returning(json.dumps(
        {"jsonrpc": "2.0", "result": {"content": [{"type": "text", "text": "ok"}]}}))
    mcp_backend(target(), {}, "list_files", poster=post)
    assert seen["rpc"]["params"]["name"] == "list_files"
    assert "Authorization" not in seen["headers"]  # no credential → no auth header


def test_structured_output_uses_structured_content():
    schema = {"type": "object", "properties": {"n": {"type": "integer"}}, "required": ["n"]}
    _, post = poster_returning(json.dumps(
        {"jsonrpc": "2.0", "result": {"structuredContent": {"n": 3}, "content": []}}))
    out = mcp_backend(target(output_schema=schema), {"token": "t"}, '{"tool":"count"}', poster=post)
    assert out["output"] == {"n": 3}


def test_sse_framed_reply_is_parsed():
    body = "event: message\ndata: " + json.dumps(
        {"jsonrpc": "2.0", "result": {"content": [{"type": "text", "text": "streamed"}]}}) + "\n\n"
    _, post = poster_returning(body)
    out = mcp_backend(target(), {"token": "t"}, '{"tool":"x"}', poster=post)
    assert out["output"] == "streamed"


def test_mcp_error_raises():
    _, post = poster_returning(json.dumps(
        {"jsonrpc": "2.0", "error": {"code": -32601, "message": "method not found"}}))
    with pytest.raises(RuntimeError):
        mcp_backend(target(), {"token": "t"}, '{"tool":"x"}', poster=post)
