"""Model targets, through the one provider port.

These used to mock the Anthropic and OpenAI SDKs directly, because the executor
kept its own list of backends. It no longer does: `models_port` answers for both
`/execute` and a harness turn, so what is worth testing here is the **routing
and the fallback**, not somebody else's client.
"""

import pytest

from open_refinery.executor import api_backend, model_backend, stub_backend
from open_refinery.models import Target
from open_refinery.models_port import PROVIDERS, provider_of


def target(endpoint="claude-opus-5", output_schema=None):
    return Target(name="t", kind="model", endpoint=endpoint, owner_id="o",
                  output_schema=output_schema or {})


# --- routing ----------------------------------------------------------------

@pytest.mark.parametrize("model,expected", [
    ("claude-opus-5", "anthropic"),
    ("gpt-5.5", "openai"),
    ("o3-mini", "openai"),
    ("gemini-3.6-flash", "google"),
    ("deepseek-chat", "deepseek"),
    ("mistral-large-latest", "mistral"),
    ("openrouter/z-ai/glm-5.2", "openrouter"),
    ("ollama/qwen3", "ollama"),
])
def test_a_model_id_routes_to_its_provider(model, expected):
    assert provider_of(model).key == expected


def test_an_explicit_prefix_beats_a_guess():
    """`openrouter/anthropic/claude-…` is OpenRouter's, not Anthropic's."""
    assert provider_of("openrouter/anthropic/claude-sonnet-5").key == "openrouter"


def test_an_unknown_model_belongs_to_nobody():
    assert provider_of("some-model-nobody-ships") is None


def test_adding_a_provider_is_one_entry():
    """The property that makes this a port: every provider carries what the
    connect screen and the router both need, in one place."""
    for key, provider in PROVIDERS.items():
        assert provider.needs, key
        assert provider.prefixes or provider.models, key


# --- the executor's dispatch ------------------------------------------------

def test_a_target_with_a_credential_calls_the_provider(monkeypatch):
    seen = {}

    def fake_call(model, credential, payload, **kw):
        seen.update(model=model, credential=credential, payload=payload)
        return {"output": "answered", "units": 11}

    monkeypatch.setattr("open_refinery.models_port.call", fake_call)
    out = model_backend(target(endpoint="gpt-5.5"), {"api_key": "sk-o"}, "hi")

    assert out == {"output": "answered", "units": 11}
    assert seen["model"] == "gpt-5.5" and seen["credential"]["api_key"] == "sk-o"


def test_a_structured_target_asks_for_its_schema(monkeypatch):
    """A persisted answer with a shape is stored with that shape."""
    seen = {}

    def fake_call(model, credential, payload, *, output_schema=None, **kw):
        seen["schema"] = output_schema
        return {"output": {"passed": True}, "units": 1}

    monkeypatch.setattr("open_refinery.models_port.call", fake_call)
    schema = {"type": "object", "properties": {"passed": {"type": "boolean"}}}
    out = model_backend(target(endpoint="claude-opus-5", output_schema=schema),
                        {"api_key": "sk"}, "hi")

    assert seen["schema"] == schema and out["output"] == {"passed": True}


def test_no_credential_falls_back_to_the_stub():
    """A fresh install works offline — that is what makes the loop inspectable
    before anybody has paid for anything."""
    out = model_backend(target(endpoint="claude-opus-5"), {}, "hello")
    assert out == stub_backend(target(endpoint="claude-opus-5"), {}, "hello")


def test_a_model_nobody_claims_falls_back_to_the_stub():
    out = model_backend(target(endpoint="not-a-real-model"), {"api_key": "sk"}, "hi")
    assert "not-a-real-model" in out["output"]


def test_a_self_hosted_target_needs_no_key(monkeypatch):
    """Ollama takes a base URL instead — so "has a credential" cannot mean
    "has an api_key"."""
    monkeypatch.setattr("open_refinery.models_port.call",
                        lambda *a, **k: {"output": "local", "units": 0})
    out = model_backend(target(endpoint="ollama/qwen3"),
                        {"base_url": "http://localhost:11434"}, "hi")
    assert out["output"] == "local"


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
