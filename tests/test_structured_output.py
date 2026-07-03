import pytest

from open_refinery import (
    EXECUTORS,
    ExecutionError,
    SqliteSink,
    connect,
    create_process,
    create_route,
    create_target,
    create_user,
    execute,
    query_events,
    validate_schema,
)

SCHEMA = {"required": ["passed", "findings"],
          "properties": {"passed": {"type": "boolean"}, "findings": {"type": "array"}}}


def test_validate_schema():
    validate_schema({"passed": True, "findings": []}, SCHEMA)  # ok
    with pytest.raises(ExecutionError):
        validate_schema("a paragraph", SCHEMA)                 # not an object
    with pytest.raises(ExecutionError):
        validate_schema({"findings": []}, SCHEMA)              # missing required
    with pytest.raises(ExecutionError):
        validate_schema({"passed": "yes", "findings": []}, SCHEMA)  # wrong type


def setup(monkeypatch, schema):
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    conn = connect("sqlite:///:memory:")
    ian, _ = create_user(conn, "ian@x.dev", "pw", "developer")
    proc = create_process(conn, "flow", "board", ["draft", "run"], ian.id)
    t = create_target(conn, "reviewer", "model", "m", ian.id, output_schema=schema)
    create_route(conn, proc.id, t.id, ian.id)
    return conn, ian, proc


def test_structured_output_persisted_and_filtered(monkeypatch):
    conn, ian, proc = setup(monkeypatch, SCHEMA)
    monkeypatch.setitem(EXECUTORS, "model", lambda t, c, p: {
        "output": {"passed": False, "findings": ["leak a@b.com"]}, "units": 1})
    r = execute(conn, ian.id, proc.id, "review", SqliteSink(conn))
    assert r["structured"] is True
    assert r["output"]["passed"] is False              # kept structured, not stringified
    assert "a@b.com" not in r["output"]["findings"][0]  # string leaves filtered
    assert "email" in r["redactions"]


def test_structured_output_validated(monkeypatch):
    conn, ian, proc = setup(monkeypatch, SCHEMA)
    monkeypatch.setitem(EXECUTORS, "model", lambda t, c, p: {"output": "just prose", "units": 1})
    with pytest.raises(ExecutionError):
        execute(conn, ian.id, proc.id, "review", SqliteSink(conn))  # not schema-conformant


def test_free_text_when_no_schema(monkeypatch):
    conn, ian, proc = setup(monkeypatch, {})  # no schema
    monkeypatch.setitem(EXECUTORS, "model", lambda t, c, p: {"output": "plain text", "units": 1})
    r = execute(conn, ian.id, proc.id, "hi", SqliteSink(conn))
    assert r["structured"] is False and r["output"] == "plain text"
    assert any(e.recipe == "invoke" for e in query_events(conn))
