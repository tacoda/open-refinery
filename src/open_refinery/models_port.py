"""Model providers — one port, two call sites.

There were two of these and they disagreed: the old executor knew Anthropic and
OpenAI, `pipeline/agent.py` knew only Anthropic, so a target routed to OpenAI
worked for a governed single call and failed inside a harness turn. Same target,
different answer.

One registry now, read by both. **Adding a provider is one entry here** — its
key, what its model ids look like, and where to get one. Nothing else changes,
which is the property that makes this a port rather than a list.

Two ways a model is reached, because they are genuinely different jobs:

- **`chat`** — a LangChain model for a *turn* (many steps, tools, interrupts)
- **`chat`** — the chat model a governed turn runs on

Both resolve their key from the **actor's own credential**, so cost attributes
to the person accountable for the work.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ModelProvider:
    """One place models come from."""

    key: str
    label: str
    # How to recognise one of its model ids, so a target's endpoint alone is
    # enough to route. Longest prefix wins, so `gpt-` does not swallow `gpt-oss`.
    prefixes: tuple[str, ...] = ()
    # Suggestions for the connect screen. They must **route back to this
    # provider**, so a gateway's suggestions carry its prefix — otherwise
    # picking `anthropic/claude-sonnet-5` from OpenRouter's list resolves to
    # Anthropic and asks for the wrong key.
    models: tuple[str, ...] = ()
    needs: str = ""
    mint_url: str = ""
    # LangChain's provider name, when it differs from ours.
    lc_provider: str = ""
    # Self-hosted or gateway providers take a URL instead of (or besides) a key.
    needs_base_url: bool = False
    shareable: bool = True                # a model key is billing, not identity
    default_base_url: str = ""


PROVIDERS: dict[str, ModelProvider] = {
    "anthropic": ModelProvider(
        "anthropic", "Anthropic",
        prefixes=("claude-",),
        models=("claude-opus-5", "claude-sonnet-5", "claude-haiku-4-5-20251001"),
        needs="a key with access to the Messages API",
        mint_url="https://console.anthropic.com/settings/keys"),
    "openai": ModelProvider(
        "openai", "OpenAI",
        prefixes=("gpt-", "o1", "o3", "o4"),
        models=("gpt-5.5", "gpt-5-mini"),
        needs="a key with access to chat completions",
        mint_url="https://platform.openai.com/api-keys"),
    "google": ModelProvider(
        "google", "Google (Gemini)",
        prefixes=("gemini-",),
        models=("gemini-3.6-pro", "gemini-3.6-flash"),
        needs="a Gemini API key",
        mint_url="https://aistudio.google.com/apikey",
        lc_provider="google_genai"),
    "groq": ModelProvider(
        "groq", "Groq",
        prefixes=("groq/",),
        models=("groq/llama-3.3-70b-versatile", "groq/qwen3-32b"),
        needs="a Groq API key",
        mint_url="https://console.groq.com/keys"),
    "mistral": ModelProvider(
        "mistral", "Mistral",
        prefixes=("mistral-", "codestral-"),
        models=("mistral-large-latest", "codestral-latest"),
        needs="a Mistral API key",
        mint_url="https://console.mistral.ai/api-keys",
        lc_provider="mistralai"),
    "deepseek": ModelProvider(
        "deepseek", "DeepSeek",
        prefixes=("deepseek-",),
        models=("deepseek-chat", "deepseek-reasoner"),
        needs="a DeepSeek API key",
        mint_url="https://platform.deepseek.com/api_keys"),
    "openrouter": ModelProvider(
        "openrouter", "OpenRouter",
        prefixes=("openrouter/",),
        models=("openrouter/anthropic/claude-sonnet-5", "openrouter/z-ai/glm-5.2"),
        needs="an OpenRouter key — one account, many models",
        mint_url="https://openrouter.ai/keys",
        lc_provider="openai",
        needs_base_url=True,
        default_base_url="https://openrouter.ai/api/v1"),
    "azure-openai": ModelProvider(
        "azure-openai", "Azure OpenAI",
        prefixes=("azure/",),
        needs="an Azure OpenAI key and your endpoint URL",
        lc_provider="azure_openai",
        needs_base_url=True),
    "ollama": ModelProvider(
        "ollama", "Ollama (self-hosted)",
        prefixes=("ollama/",),
        models=("ollama/qwen3", "ollama/llama3.3"),
        needs="no key — a reachable Ollama host",
        needs_base_url=True,
        default_base_url="http://localhost:11434"),
}


class UnknownModel(LookupError):
    """No provider claims this model id."""


def provider_of(model: str) -> ModelProvider | None:
    """Which provider a model id belongs to.

    Longest prefix wins, so a provider adding `gpt-oss-` does not lose to
    `gpt-`. An explicit `provider/model` form always wins over a prefix guess.
    """
    name = (model or "").strip().lower()
    if not name:
        return None
    head = name.split("/", 1)[0]
    if head in PROVIDERS:
        return PROVIDERS[head]

    best, longest = None, 0
    for provider in PROVIDERS.values():
        for prefix in provider.prefixes:
            if name.startswith(prefix.lower()) and len(prefix) > longest:
                best, longest = provider, len(prefix)
    return best


def bare_model(model: str) -> str:
    """The model id with our provider prefix stripped, if it carried one."""
    name = (model or "").strip()
    head = name.split("/", 1)[0].lower()
    if head in PROVIDERS and "/" in name:
        return name.split("/", 1)[1]
    return name


def suggestions() -> dict[str, list[str]]:
    return {k: list(p.models) for k, p in PROVIDERS.items() if p.models}


def chat(model: str, credential: dict, *, max_tokens: int = 16000):
    """A LangChain chat model for a **turn**.

    One code path for every provider: `init_chat_model` resolves the package,
    so adding one is an entry above rather than another `if provider ==` branch
    — which is exactly the branch that let the two seams drift apart.
    """
    from langchain.chat_models import init_chat_model

    provider = provider_of(model)
    if provider is None:
        raise UnknownModel(
            f"no provider claims {model!r} — known prefixes: "
            f"{', '.join(sorted(p for pr in PROVIDERS.values() for p in pr.prefixes))}")

    kwargs: dict = {"model_provider": provider.lc_provider or provider.key,
                    "max_tokens": max_tokens}
    key = credential.get("api_key") or credential.get("token") or ""
    if key:
        kwargs["api_key"] = key
    base = credential.get("base_url") or provider.default_base_url
    if provider.needs_base_url and base:
        kwargs["base_url"] = base
    return init_chat_model(bare_model(model), **kwargs)
