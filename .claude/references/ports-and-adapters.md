# Ports and Adapters (Hexagonal Architecture)

Reference: Alistair Cockburn's Hexagonal Architecture — the application core
defines **ports** (interfaces); **adapters** implement them for specific
external technologies. The core stays independent of any particular connector.

## Why it matters here

open-refinery is a connector-heavy system: source hosts (GitHub, GitLab),
trackers (Jira, Linear), OAuth providers, and targets (models, MCP servers,
APIs) — with more to come. Ports and adapters keep the governed core (processes,
transitions, policy, audit) decoupled from each connector, so adding a connector
is writing one adapter, not touching the core.

## The ports (seams) in this codebase

- **Integration adapters** — `integrations.ADAPTERS[kind]` = `{verify, list_repos
  | list_issues}`. Add a source/tracker by adding a dict entry; the service layer
  and API don't change.
- **Executor backends** — `executor.EXECUTORS[kind]` = a callable
  `(target, credential, payload) -> result`. Add a model/MCP/API backend by
  registering one; the pipeline (auth, quota, secrets, filter, audit, failover)
  is unchanged.
- **OAuth providers** — `oauth.PROVIDERS[kind]` = endpoints/scopes/env; each
  provider is gated on its own credentials.
- **Audit sinks** — the `AuditSink` protocol (`MemorySink`, `JsonlSink`,
  `SqlSink`). Swap where events go without touching producers.
- **Email senders** — the `EmailSender` protocol (default `LinuxMailSender`;
  SMTP/others register). Chosen and configured by admin/platform in the UI.
- **Data store** — SQLModel over an engine; other backends (Postgres) slot in at
  the same seam.

## Every connection is UI-managed

All of these connections are configurable at some level, implemented as ports and
adapters, and **managed by authorized users in the web app** (the right role
picks and configures the adapter; credentials are stored encrypted in the DB).
Adding a provider is a new adapter; wiring it up is a UI action, not a redeploy.

## Rule

New connectors are **adapters behind an existing port**. If a feature needs the
core to know about a specific vendor, that's a smell — push the vendor detail
into an adapter and keep the port generic. When a new *kind* of connector
appears, define a small port (a registry of callables or a Protocol), not a
special case threaded through the core.
