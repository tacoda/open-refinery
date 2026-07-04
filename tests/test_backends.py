import sys
import types

import pytest

from open_refinery.executor import anthropic_backend, model_backend, openai_backend
from open_refinery.models import Target


def target(endpoint="claude-opus-4-8", output_schema=None):
    return Target(name="t", kind="model", endpoint=endpoint, owner_id="o",
                  output_schema=output_schema or {})


def fake_anthropic(monkeypatch, *, text="hi", tokens=7, stop_reason="end_turn"):
    """Inject a stand-in `anthropic` module; return a dict capturing call kwargs."""
    seen: dict = {}

    class _Block:
        type = "text"

        def __init__(self, t):
            self.text = t

    class _Resp:
        def __init__(self):
            self.content = [_Block(text)]
            self.stop_reason = stop_reason
            self.usage = types.SimpleNamespace(output_tokens=tokens)

    class _Messages:
        def create(self, **kwargs):
            seen.update(kwargs)
            return _Resp()

    class _Client:
        def __init__(self, api_key=None):
            seen["api_key"] = api_key
            self.messages = _Messages()

    mod = types.ModuleType("anthropic")
    mod.Anthropic = _Client
    monkeypatch.setitem(sys.modules, "anthropic", mod)
    return seen


def fake_openai(monkeypatch, *, text="hi", tokens=5):
    seen: dict = {}

    class _Msg:
        def __init__(self, c):
            self.content = c

    class _Choice:
        def __init__(self, c):
            self.message = _Msg(c)

    class _Resp:
        def __init__(self):
            self.choices = [_Choice(text)]
            self.usage = types.SimpleNamespace(completion_tokens=tokens)

    class _Completions:
        def create(self, **kwargs):
            seen.update(kwargs)
            return _Resp()

    class _Chat:
        completions = _Completions()

    class _Client:
        def __init__(self, api_key=None):
            seen["api_key"] = api_key
            self.chat = _Chat()

    mod = types.ModuleType("openai")
    mod.OpenAI = _Client
    monkeypatch.setitem(sys.modules, "openai", mod)
    return seen


def test_openai_free_text(monkeypatch):
    seen = fake_openai(monkeypatch, text="reply", tokens=9)
    out = openai_backend(target(endpoint="gpt-5"), {"api_key": "sk-o"}, "hi")
    assert out == {"output": "reply", "units": 9}
    assert seen["model"] == "gpt-5" and "response_format" not in seen


def test_openai_structured_output(monkeypatch):
    seen = fake_openai(monkeypatch, text='{"n": 1}')
    schema = {"type": "object", "properties": {"n": {"type": "integer"}}, "required": ["n"]}
    out = openai_backend(target(endpoint="gpt-5", output_schema=schema), {"api_key": "sk-o"}, "hi")
    assert out["output"] == {"n": 1}
    assert seen["response_format"]["json_schema"]["schema"] == schema


def test_dispatch_openai_by_endpoint(monkeypatch):
    fake_openai(monkeypatch, text="viaopenai")
    out = model_backend(target(endpoint="gpt-5"), {"api_key": "sk-o"}, "hi")
    assert out["output"] == "viaopenai"


def test_oauth_token_connects(monkeypatch):
    # a target connected via OAuth stores an access_token, not an api_key
    seen = fake_anthropic(monkeypatch, text="oauthed")
    out = model_backend(target(), {"provider": "anthropic", "access_token": "oauth-tok"}, "hi")
    assert out["output"] == "oauthed" and seen["api_key"] == "oauth-tok"


def test_anthropic_free_text(monkeypatch):
    seen = fake_anthropic(monkeypatch, text="answer", tokens=12)
    out = anthropic_backend(target(), {"api_key": "sk-x"}, "hello")
    assert out == {"output": "answer", "units": 12}
    assert seen["model"] == "claude-opus-4-8" and seen["api_key"] == "sk-x"
    assert "output_config" not in seen  # no schema → no structured request


def test_anthropic_structured_output(monkeypatch):
    seen = fake_anthropic(monkeypatch, text='{"ok": true}')
    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}
    out = anthropic_backend(target(output_schema=schema), {"api_key": "sk-x"}, "hi")
    assert out["output"] == {"ok": True}
    assert seen["output_config"]["format"]["schema"] == schema


def test_anthropic_refusal_raises(monkeypatch):
    fake_anthropic(monkeypatch, stop_reason="refusal")
    with pytest.raises(RuntimeError):
        anthropic_backend(target(), {"api_key": "sk-x"}, "hi")


def test_dispatch_uses_anthropic_with_credential(monkeypatch):
    fake_anthropic(monkeypatch, text="real")
    out = model_backend(target(), {"api_key": "sk-x"}, "hi")
    assert out["output"] == "real"  # dispatched to the real backend


def test_dispatch_falls_back_to_stub_without_credential(monkeypatch):
    out = model_backend(target(), {}, "hi")           # no key → stub
    assert out["output"].startswith("[model:claude-opus-4-8]")


def test_dispatch_unknown_provider_stubs(monkeypatch):
    out = model_backend(target(endpoint="mistral-large"), {"api_key": "sk-x"}, "hi")  # no backend
    assert out["output"].startswith("[model:mistral-large]")


def test_api_backend_posts_and_parses(monkeypatch):
    seen = {}

    def post(url, body, headers):
        seen["url"] = url
        seen["body"] = body
        seen["headers"] = headers
        return 200, '{"ok": true}'

    from open_refinery.executor import api_backend
    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}
    out = api_backend(Target(name="a", kind="api", endpoint="https://api/x", owner_id="o",
                             output_schema=schema), {"token": "t"}, '{"q":1}', poster=post)
    assert out["output"] == {"ok": True} and out["units"] == 1
    assert seen["url"] == "https://api/x" and seen["headers"]["Authorization"] == "Bearer t"


def test_api_backend_raises_on_http_error(monkeypatch):
    from open_refinery.executor import api_backend
    with pytest.raises(RuntimeError):
        api_backend(Target(name="a", kind="api", endpoint="https://api/x", owner_id="o"),
                    {}, "{}", poster=lambda u, b, h: (500, "boom"))
