"""Service credentials — one catalog, one screen, one resolution rule.

Every external service is reached with a key or a token a **person** entered in
their own settings. There is no authorization-code flow anywhere in the product
and no shared machine account: a run started by Dana uses Dana's GitHub token
and Dana's model key, so the pull request is authored by the person accountable
for it and cost attributes to a real actor at the call site.

`PROVIDERS` is the catalog — the single source of truth for the API, the
onboarding wizard and the Connections screen. Adding support for a service is an
entry here plus its adapter functions; *connecting* to it is not an engineering
task at all, which is the difference between this and configuring a worker.

Three families, because they are asked for in different places and mean
different things:

- **model**   — where a phase's turn runs (Anthropic, OpenAI, …)
- **forge**   — where the branch is pushed and the request opened (GitHub, …)
- **tracker** — where tickets come from (Jira, Linear, …)

Credentials are verified before they are stored — nothing is saved that does not
authenticate — encrypted at rest with `crypto`, and never returned by the API.
"""

from __future__ import annotations

from dataclasses import dataclass, field

MODEL, FORGE, TRACKER = "model", "forge", "tracker"
FAMILIES = (MODEL, FORGE, TRACKER)


@dataclass(frozen=True)
class Field_:
    """One input on the connect form."""

    name: str
    label: str
    secret: bool = False
    required: bool = True
    placeholder: str = ""


@dataclass(frozen=True)
class Provider:
    """One connectable service."""

    key: str
    family: str
    label: str
    fields: tuple[Field_, ...]
    # Where to go and mint the credential, and exactly what it needs to carry.
    # Both exist so the Connections screen can answer "what do I paste here"
    # without the reader leaving to search for it.
    mint_url: str = ""
    needs: str = ""
    # Model providers only: what a target's endpoint may be set to.
    models: tuple[str, ...] = ()
    # Whether an admin may publish one of these for the whole org (§2.2).
    # Identity-bearing credentials are personal; a model key is a billing
    # relationship, which is the one an org usually holds centrally.
    shareable: bool = False


def _secret(name: str, label: str, placeholder: str = "") -> Field_:
    return Field_(name=name, label=label, secret=True, placeholder=placeholder)


PROVIDERS: dict[str, Provider] = {
    # --- models -----------------------------------------------------------
    "anthropic": Provider(
        "anthropic", MODEL, "Anthropic",
        (_secret("api_key", "API key", "sk-ant-…"),),
        mint_url="https://console.anthropic.com/settings/keys",
        needs="a key with access to the Messages API",
        models=("claude-opus-5", "claude-sonnet-5", "claude-haiku-4-5-20251001"),
        shareable=True),
    "openai": Provider(
        "openai", MODEL, "OpenAI",
        (_secret("api_key", "API key", "sk-…"),),
        mint_url="https://platform.openai.com/api-keys",
        needs="a key with access to chat completions",
        models=("gpt-5.5", "gpt-5-mini"),
        shareable=True),
    "ollama": Provider(
        "ollama", MODEL, "Ollama (self-hosted)",
        (Field_("base_url", "Base URL", placeholder="http://localhost:11434"),),
        needs="no key — a reachable Ollama host",
        shareable=True),

    # --- forges -----------------------------------------------------------
    "github": Provider(
        "github", FORGE, "GitHub",
        (_secret("token", "Personal access token", "github_pat_…"),),
        mint_url="https://github.com/settings/tokens?type=beta",
        needs="Contents: read/write · Pull requests: read/write · Metadata: read"),
    "gitlab": Provider(
        "gitlab", FORGE, "GitLab",
        (_secret("token", "Personal access token", "glpat-…"),),
        mint_url="https://gitlab.com/-/user_settings/personal_access_tokens",
        needs="scopes: api, write_repository"),
    "local": Provider(
        "local", FORGE, "Local (no forge)",
        (),
        needs="nothing — the request is written as a file in the repository"),

    # --- trackers ---------------------------------------------------------
    "github-issues": Provider(
        "github-issues", TRACKER, "GitHub Issues",
        (_secret("token", "Personal access token", "github_pat_…"),
         Field_("repo", "Repository", required=False, placeholder="owner/name")),
        mint_url="https://github.com/settings/tokens?type=beta",
        needs="Issues: read/write · Metadata: read. Leave Repository blank for issues assigned to you"),
    "jira": Provider(
        "jira", TRACKER, "Jira",
        (Field_("site", "Site", placeholder="your-team.atlassian.net"),
         Field_("email", "Account email", placeholder="you@example.com"),
         _secret("token", "API token")),
        mint_url="https://id.atlassian.com/manage-profile/security/api-tokens",
        needs="an API token for the account above"),
    "linear": Provider(
        "linear", TRACKER, "Linear",
        (_secret("token", "API key", "lin_api_…"),),
        mint_url="https://linear.app/settings/api",
        needs="a personal API key"),
}


class UnknownProvider(ValueError):
    """Raised for a provider key that is not in the catalog."""


class MissingField(ValueError):
    """Raised when a required credential field is absent or blank."""


class NoCredential(LookupError):
    """Raised when an actor has no usable credential for a provider.

    Carries the provider so the caller can say which connection is missing
    rather than failing with a bare authentication error from the service.
    """

    def __init__(self, provider: str, actor_id: str = ""):
        self.provider, self.actor_id = provider, actor_id
        super().__init__(
            f"no credential for {provider!r} — connect it in Settings → Connections")


def get_provider(key: str) -> Provider:
    provider = PROVIDERS.get(key)
    if provider is None:
        raise UnknownProvider(f"unknown provider: {key!r}")
    return provider


def catalog(family: str | None = None) -> list[dict]:
    """The connectable services, for the UI and the wizard."""
    out = []
    for p in PROVIDERS.values():
        if family and p.family != family:
            continue
        out.append({
            "key": p.key, "family": p.family, "label": p.label,
            "mint_url": p.mint_url, "needs": p.needs,
            "models": list(p.models), "shareable": p.shareable,
            "fields": [{"name": f.name, "label": f.label, "secret": f.secret,
                        "required": f.required, "placeholder": f.placeholder}
                       for f in p.fields],
        })
    return out


def validate(key: str, credential: dict) -> dict:
    """Check a credential against its provider's declared fields.

    Returns the credential narrowed to the declared fields — so a stray extra
    key a caller passed is not quietly encrypted and stored forever.
    """
    provider = get_provider(key)
    clean = {}
    for f in provider.fields:
        value = str(credential.get(f.name) or "").strip()
        if not value:
            if f.required:
                raise MissingField(f"{provider.label} needs {f.label!r}")
            continue
        clean[f.name] = value
    return clean


# --- verification ----------------------------------------------------------
# Each provider says how to prove a credential works and who it belongs to.
# The forge/tracker verifiers already exist in `integrations`; model providers
# get theirs here, because nothing needed one while targets held raw keys.

def _anthropic_verify(cred: dict) -> dict:
    import json
    import urllib.request
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/models?limit=1",
        headers={"x-api-key": cred["api_key"], "anthropic-version": "2023-06-01"})
    with urllib.request.urlopen(req, timeout=10) as r:
        json.load(r)
    return {"account": "anthropic"}  # the API exposes no account identity


def _openai_verify(cred: dict) -> dict:
    import json
    import urllib.request
    req = urllib.request.Request(
        "https://api.openai.com/v1/models?limit=1",
        headers={"Authorization": f"Bearer {cred['api_key']}"})
    with urllib.request.urlopen(req, timeout=10) as r:
        json.load(r)
    return {"account": "openai"}


def _ollama_verify(cred: dict) -> dict:
    import json
    import urllib.request
    base = cred["base_url"].rstrip("/")
    with urllib.request.urlopen(f"{base}/api/tags", timeout=10) as r:
        body = json.load(r)
    return {"account": f"{base} ({len(body.get('models', []))} models)"}


def _local_verify(cred: dict) -> dict:
    return {"account": "local"}  # nothing to reach; the forge is the filesystem


def verifier(key: str):
    """The function that proves a credential works, or None if unverifiable."""
    from . import integrations
    builtin = {"anthropic": _anthropic_verify, "openai": _openai_verify,
               "ollama": _ollama_verify, "local": _local_verify}
    if key in builtin:
        return builtin[key]
    adapter = integrations.ADAPTERS.get(key) or {}
    return adapter.get("verify")


def verify_credential(key: str, credential: dict) -> dict:
    """Prove a credential works and return who it belongs to.

    Raises whatever the provider raised — the caller surfaces it verbatim,
    because 'GitHub said 401' is a better message than 'verification failed'.
    """
    fn = verifier(key)
    if fn is None:
        return {"account": get_provider(key).label}
    return fn(credential)


# --- service layer ---------------------------------------------------------

def connect(session, owner_id: str, key: str, credential: dict, *,
            shared: bool = False):
    """Verify a credential, then store it encrypted against its owner.

    Verification happens **before** storage on purpose: a key that does not
    authenticate is not saved, so the Connections screen never shows a
    connection that was never going to work.
    """
    import json

    from .crypto import encrypt
    from .models import Integration, User, now_iso

    provider = get_provider(key)
    if session.get(User, owner_id) is None:
        raise ValueError(f"unknown owner: {owner_id!r}")
    if shared and not provider.shareable:
        raise ValueError(
            f"{provider.label} credentials are personal — "
            "an identity cannot be shared across an org")

    clean = validate(key, credential)
    account = str(verify_credential(key, clean).get("account") or provider.label)

    row = Integration(kind=key, account=account, owner_id=owner_id,
                      secret=encrypt(json.dumps(clean)), shared=shared,
                      last_verified_at=now_iso(), status="ok")
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def credential_of(session, integration_id: str) -> dict:
    """The decrypted credential — for a call site, never for a response."""
    import json

    from .crypto import decrypt
    from .models import Integration

    row = session.get(Integration, integration_id)
    if row is None:
        raise ValueError(f"unknown credential: {integration_id!r}")
    return json.loads(decrypt(row.secret))


def public(row) -> dict:
    """The safe projection. `secret` must never cross the wire."""
    return {"id": row.id, "provider": row.kind,
            "family": PROVIDERS[row.kind].family if row.kind in PROVIDERS else "",
            "label": PROVIDERS[row.kind].label if row.kind in PROVIDERS else row.kind,
            "account": row.account, "shared": row.shared,
            "status": row.status, "status_detail": row.status_detail,
            "last_verified_at": row.last_verified_at, "created_at": row.created_at}


def list_for(session, owner_id: str | None = None, *, family: str | None = None) -> list:
    """Credentials, scoped to an owner. `None` sees every one (oversight)."""
    from sqlmodel import select

    from .models import Integration

    stmt = select(Integration)
    if owner_id is not None:
        stmt = stmt.where(Integration.owner_id == owner_id)
    rows = list(session.exec(stmt.order_by(Integration.created_at.desc())))
    if family:
        rows = [r for r in rows if r.kind in PROVIDERS and PROVIDERS[r.kind].family == family]
    return rows


def recheck(session, integration_id: str) -> dict:
    """Re-verify a stored credential and record the outcome.

    A key that worked at connect time and has since been revoked is the common
    failure, and it is invisible until something tries to use it. Recording the
    outcome lets the Connections screen and `doctor` say so first.
    """
    from .models import Integration, now_iso

    row = session.get(Integration, integration_id)
    if row is None:
        raise ValueError(f"unknown credential: {integration_id!r}")
    try:
        account = verify_credential(row.kind, credential_of(session, integration_id))
        row.account = str(account.get("account") or row.account)
        row.status, row.status_detail = "ok", ""
        row.last_verified_at = now_iso()
    except Exception as exc:  # noqa: BLE001 — surfaced verbatim; this is a report
        row.status, row.status_detail = "failing", f"{type(exc).__name__}: {exc}"
    session.add(row)
    session.commit()
    session.refresh(row)
    return public(row)


def rotate(session, integration_id: str, credential: dict) -> dict:
    """Replace a credential's secret in place — same id, same wiring, new key.

    Rotation must not be delete-and-recreate: anything referencing this row by
    id would break, and the gap between the two is a window where work fails.
    """
    import json

    from .crypto import encrypt
    from .models import Integration, now_iso

    row = session.get(Integration, integration_id)
    if row is None:
        raise ValueError(f"unknown credential: {integration_id!r}")

    clean = validate(row.kind, credential)
    account = verify_credential(row.kind, clean)     # refuse a broken replacement
    row.secret = encrypt(json.dumps(clean))
    row.account = str(account.get("account") or row.account)
    row.status, row.status_detail = "ok", ""
    row.last_verified_at = now_iso()
    session.add(row)
    session.commit()
    session.refresh(row)
    return public(row)


def revoke(session, integration_id: str) -> None:
    from .models import Integration

    row = session.get(Integration, integration_id)
    if row is not None:
        session.delete(row)
        session.commit()


def for_actor(session, actor_id: str, provider: str) -> dict:
    """The credential this actor reaches `provider` with.

    Resolution order, and the last step matters as much as the first:

    1. the actor's **own** credential — a run uses the runner's identity, so the
       pull request is authored by the person accountable for it
    2. an **org-wide** credential, only for providers the catalog marks
       shareable (model keys, never a forge or tracker token)
    3. `NoCredential` — never a silent fallback to somebody else's key, which
       would attribute one person's work to another in the audit trail

    Returns the decrypted credential. Called at the call site, never returned.
    """
    from sqlmodel import select

    from .models import Integration

    get_provider(provider)  # raises UnknownProvider for a typo
    rows = list(session.exec(
        select(Integration).where(Integration.kind == provider)))

    mine = [r for r in rows if r.owner_id == actor_id]
    if mine:
        return credential_of(session, mine[0].id)

    if PROVIDERS[provider].shareable:
        org = [r for r in rows if r.shared]
        if org:
            return credential_of(session, org[0].id)

    raise NoCredential(provider, actor_id)
