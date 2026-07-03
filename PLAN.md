# open-refinery — Product Plan

## Thesis

open-refinery is a **self-hosted dark factory that adds auditability to make it
open.** A dark factory runs lights-out: work ships through defined processes
with minimal human intervention. open-refinery keeps that automation *open* —
every action is owned, authorized, recorded, and queryable. Dark by operation,
open by record.

Self-hosted, minimal setup (env vars), multi-repository, deeply customizable
processes, a web dashboard, and per-user accountability with an admin-visible
audit trail.

## Positioning: the Platform layer

open-refinery is the **Platform** — the out-of-process governance layer between
harnesses and targets.

```
   Harness                    Platform                     Targets
   (in-process, app-owned)    (out-of-process)             (models, tools, APIs)
   ┌──────────────────┐       ┌──────────────────┐         ┌──────────────────┐
   │ Orchestration    │       │ Identity, authZ  │         │ Models           │
   │ Prompt context   │  ──▶  │ Audit log        │   ──▶   │ MCP servers      │
   │ Tool selection   │       │ Quotas, cost     │         │ Backend APIs     │
   │ Memory & state   │       │ Routing          │         └──────────────────┘
   │ Self-verification│       │ Content filter   │
   └──────────────────┘       └──────────────────┘
```

- **Harnesses** (pds, pyness, any app-owned agent) own orchestration, prompt
  context, tool selection, memory, self-verification. They call *through* the
  platform.
- **The platform** (open-refinery) is where identity, authorization, audit,
  quotas/cost, routing, and content filtering live — out of process, so every
  harness inherits governance without reimplementing it.
- **Targets** are what work runs against: models (frontier + hosted), MCP
  servers (internal + partner), backend APIs (apps, data, systems).

The **process/work-item** model (below) is how a harness *ships work* through
the platform; the platform pillars are what govern each unit of that work as it
reaches a target.

## Locked decisions

| Area      | Choice                                                              |
|-----------|--------------------------------------------------------------------|
| Backend   | FastAPI + Python (builds on the 0.1.0 core; `uv` + `hatchling`)     |
| Data      | SQLite default (one file, WAL); `DATABASE_URL` swaps to Postgres    |
| Dashboard | React SPA, served by the API in production (single deploy)          |
| Identity  | Dual: **OAuth** for interactive/human accounts (dashboard sign-in, Claude-Code-style), **API tokens** for programmatic/API accounts. Roles `developer`/`platform`/`admin`. |
| Orchestration | **LangGraph** for executing agentic stage actions with durable checkpointer state (persisted to our DB). Process state machine itself stays declarative domain data — *not* a langgraph graph. `deepagents` optional (see open questions). |

## Domain model

The 0.1.0 core generalizes cleanly: a **recipe** becomes a **stage transition**,
`produce()` becomes `transition()`, and the audit `Record` becomes an `Event`.

| Concept      | Meaning                                                                 |
|--------------|-------------------------------------------------------------------------|
| `User`       | Authenticated principal. Email, password hash, role (`developer`/`platform`/`admin`), hashed API token. |
| `Repository` | **The atomic unit** the factory operates on ("project" is a synonym). One git repo = one `Repository`, regardless of code architecture: a monorepo is one repo; N services in N repos are N repos; microservices don't change the unit. Imported from a source-control integration; has owner + credentials ref. |
| `Integration`| A team-configured connection to an external system via a pluggable **adapter** — source control (GitHub, GitLab), issue trackers (Jira, Linear), and more. Owns its own credentials; every call audited. Repos import from source-control integrations; work items can sync from trackers. |
| `Process`    | A named, customizable workflow: ordered/graph of **stages** + allowed transitions + guards. Archetypes: **board** (kanban) or **doctrine** (fixed procedure). |
| `Stage`      | A node in a process (e.g. `triage`, `patch`, `verify`, `done`).         |
| `WorkItem`   | A unit of work shipped through a process for a repository. Has current stage, owner, provenance. |
| `Transition` | Moving a work item between stages — a governed production event.        |
| `Event`      | Append-only audit entry. Every state change, stamped with actor + time. |
| `Target`     | A destination work runs against: model, MCP server, or backend API. Has credentials ref, owner. |
| `Route`      | A rule mapping a request (process/stage/actor/repo) to a target. Enables failover, cost/latency routing, and target versioning. |
| `Quota`      | A limit on usage per user/team/process/target — request count, token/cost budget, rate. Enforced before a target call; overage recorded. |
| `Gate`       | A checkpoint on a transition requiring approval / evals / checks before it proceeds. Carries an oversight level. |
| `Approval`   | A recorded human sign-off on a gated transition — who, when, decision, note. The accountability chain for oversight. |
| `Attestation`| A signed claim that a check passed (evals, tests, code-health, content-filter) — attached to the transition's provenance. |
| `Policy`     | *(roadmap)* Constraint on transitions — governance layer.               |

**Ship work = a work item transitions through a process's stages.** Each
transition is authorized → executed → recorded (provenance + ownership) →
audited → logged. Same loop as the 0.1.0 factory, one level up.

### Process customization

A process is a **series of steps (stages) connected by transitions** — a
directed graph, so **feedback loops are first-class** (a step can point back to
an earlier one, e.g. `verify → patch` on a failed check). It is declarative data
(stored in DB, **fully editable through the web UI** — no config files): steps,
allowed transitions, WIP limits, required guards. **Guards** are the code seam —
registered by name in Python (`GUARD_FACTORIES` pattern from pyness),
configured/tuned by data. Ships with two built-in archetypes:

- **Board (kanban)**: columns, manual transitions, WIP limits. Team-based flow.
- **Doctrine**: a fixed ordered procedure with guards between steps (e.g. vuln
  remediation: `detect → triage → patch → verify → close`, each gated).

Teams define any number of processes and route repos' work through them.

## Human oversight & autonomy

The dark factory runs lights-out by default, but **oversight is a dial, not a
switch** — set per process, and overridable per stage, to match team
philosophy. Every level produces the same audit trail; they differ only in how
much a human must touch a transition before it proceeds.

| Level | Name        | Behaviour                                                        |
|-------|-------------|------------------------------------------------------------------|
| L0    | Manual      | Human performs the action; platform records it.                  |
| L1    | Assisted    | AI proposes; a human approves **every** step before it applies.  |
| L2    | Supervised  | AI acts freely; a human must approve at defined **gates**.       |
| L3    | Autonomous  | AI acts; humans are notified and can intervene/roll back.        |
| L4    | Dark        | Fully lights-out; audit-only, no human in the loop.              |

A `Gate` binds an oversight level to a transition. Gates can also require
**attestations** (evals passed, tests green, code-health held, content-filter
clean) before an `Approval` is even offered. An `Approval` records who signed
off, when, and why — the accountability chain. Escalation/notification targets
are configurable per gate.

## AI-SDLC governance surface

Everything below is **configurable**, and every use of it is **observable,
auditable, and accountable** (tied to a user via token). This is the full
surface the platform governs across an AI-driven software development lifecycle.

| Surface                     | Configurable                                  | Recorded / attributed                          |
|-----------------------------|-----------------------------------------------|------------------------------------------------|
| Processes & stages          | Stages, transitions, WIP, archetype           | Every transition, with actor + provenance       |
| Oversight level             | Per process, override per stage               | Gate hits, approvals, who/when/why              |
| Identity & roles            | Users, roles, ownership                       | Login, token issue/rotate/revoke               |
| Authorization               | Who may act on what target/repo/process       | Allow/deny decisions                           |
| Routing                     | Route rules, failover, target versions        | Which target served each call                   |
| Quotas, cost & rate limits  | Budgets/limits per user/team/process/target   | Usage, cost, overage, throttles                 |
| Model & prompt provenance   | Allowed models, prompt/version pins, params   | Model, prompt, params behind each artifact      |
| Tool / target allow-lists   | Which MCP servers / APIs are reachable        | Each tool/target invocation                     |
| Integrations / sources      | Connect GitHub, GitLab, Jira, Linear, …       | Every external call, sync, and credential use    |
| Quality gates               | Required evals, tests, code-health thresholds | Pass/fail attestations per transition           |
| Content filtering           | In/out inspection, secret/PII redaction rules | Filter hits, redactions                         |
| Notifications & escalation  | Who is alerted on gate/failure/overage        | Alerts sent, acknowledgements                   |
| Retention & data residency  | Event/artifact retention, where data lives    | Retention actions, purges                       |
| Reversibility               | Which actions are reversible / need rollback  | Rollbacks, compensating actions                 |
| Secrets                     | Target/repo credential sources                | Access to credentials (not the values)          |

## Architecture

```
                ┌─────────────── React SPA (dashboard) ────────────────┐
                │  work board · repos · processes · audit · metrics     │
                └───────────────────────┬───────────────────────────────┘
                                        │ REST + token auth
        ┌───────────────────────────────▼───────────────────────────────┐
        │ FastAPI                                                         │
        │  auth (login, tokens, roles)  ·  ownership scoping middleware   │
        │  routers: repos · processes · work · events · metrics · admin   │
        └───────────────────────────────┬───────────────────────────────┘
        ┌───────────────────────────────▼───────────────────────────────┐
        │ Core (open_refinery)                                            │
        │  process engine (transition loop)  ·  authz  ·  policy(roadmap) │
        │  provenance  ·  event store  ·  observability read-model        │
        └───────────────────────────────┬───────────────────────────────┘
        ┌───────────────────────────────▼───────────────────────────────┐
        │ Persistence: SQLite (default) | Postgres (DATABASE_URL)         │
        │  append-only events table + projected read-model                │
        └─────────────────────────────────────────────────────────────────┘
```

### Module map (target)

```
src/open_refinery/
  factory.py        # 0.1.0 core — generalize into the transition loop
  provenance.py     # Record → Event
  authz.py          # Authorizer (roles, ownership) — extend
  audit.py          # AuditSink → durable event store (SQL)
  process/          # process definitions, stages, guards, archetypes
  oversight/        # autonomy levels, gates, approvals, attestations
  routing/          # targets, route rules, failover
  quotas/           # budgets, cost tracking, rate limits
  integrations/     # pluggable adapters: github, gitlab, jira, linear, base
  domain/           # User, Repository, Process, WorkItem, Target entities
  store/            # DB layer (SQLite/Postgres), migrations, event store
  observability/    # read-model, metrics, audit queries
  policy/           # (roadmap) governance policy layer
  web/              # FastAPI app, routers, auth, dashboard static serving
  cli.py            # admin/bootstrap CLI (create-admin, migrate, serve)
```

## Pillars → implementation

| Pillar          | Implementation                                                   |
|-----------------|------------------------------------------------------------------|
| Authorization   | Role + ownership checks in the transition loop and API middleware|
| Provenance      | `Event` per transition — actor, repo, process, stage, digests    |
| Ownership       | Every entity owner-stamped; scoping enforced in queries          |
| Auditability    | Append-only event store; nothing deleted, everything attributed  |
| Logging         | Structured stdlib logging, correlation id per request/transition |
| Observability   | Read-model + metrics API (throughput, cycle time, WIP, failures) |
| Accountability  | Per-user token; every action ties to a user; admin sees all      |
| Routing         | `Route` rules map work to targets; failover, cost/latency, versioning |
| Quotas & cost   | `Quota` limits per user/team/process/target; enforced pre-call, overage audited |
| Oversight       | Per-process/stage autonomy level (L0–L4); `Gate` + `Approval` + `Attestation` |
| Quality gates   | Required evals/tests/code-health as attestations before a transition |
| Integrations    | Pluggable adapters (GitHub, GitLab, Jira, Linear…), team-configured, audited |
| Content filter  | *(roadmap)* inspect/redact payloads to/from targets              |
| Governance      | *(roadmap)* policy layer constraining transitions                |

## Auth & accountability

- **User login is by email + password, or GitHub OAuth.** Humans sign in to the
  dashboard with their password (`POST /auth/login` → session token) or via a
  GitHub OAuth account. API tokens are **not** for human login.
- **API tokens** authenticate programmatic/API clients (CI, harnesses, scripts)
  as a Bearer credential. Sessions and tokens both resolve to the same `User`.
- **Connecting to external services** (GitHub, GitLab, Jira, Linear, model
  providers, MCP) is a *separate* concern from user login: those connections are
  configured in the UI via a service **API token or OAuth**, stored encrypted.
  That lives in the integrations layer (0.6.0), not user auth.
- **Every request** carries an OAuth session or a token → resolves to a `User`
  → stamped on any resulting `Event`. No anonymous mutations.
- **Roles** — three roles defined by *scope of authority*, not a simple
  permission ladder:
  - `developer` — **drives work and sets repository (project) standards.**
    Creates and moves work items; owns and tunes the standards for their own
    repos (the inner layer of the cascade). Sees and acts on what they own.
    (Repository = project = the git repo; see the domain model.)
  - `platform` — **defines policy and standards for teams/organizations.** Sets
    the org/team-wide policy and standards that projects inherit (the outer
    layer), and configures the governance surface: integrations, targets,
    routes, quotas, processes, oversight levels and gates.
  - `admin` — **audits everything.** Full read across all work, repos, users,
    and the complete audit trail with the user tied to each action; user
    management. The accountability and observability authority.
- **Standards cascade** (mirrors the pds charter): `platform` (org/team) ▸
  `developer` (project) — outer sets the floor, inner refines within it; a
  project can tighten but not escape org policy.
- Ownership scoping is enforced at the query layer, not just the UI.

## Observability tooling

The point of "open": make finding events and metrics easy.

- **Event feed**: filter by actor, repo, process, work item, stage, time range.
- **Metrics**: throughput, per-stage cycle time, WIP, transition counts,
  guard failures, per-actor activity — derived by replaying the event store.
- **Audit view (admin)**: chronological, attributed, with links to the exact
  work item / repo / process each action touched.

## Deployment & config (minimal setup)

**Happy path to adoption:** spin up a VPS → install deps → set a minimal set of
environment variables → `open-refinery serve`. After that, *all* management —
users, accounts, repos, processes, integrations, everything — happens in the web
UI. The CLI only seeds the first admin.

**Config is data, not env.** Environment variables only bootstrap the process;
*everything else* — users, integrations, targets, processes, routes, quotas,
oversight levels — is managed in the web UI and stored in the database. A
first-run **setup wizard** creates the initial admin; there is no config file to
edit.

Single process serves API + SPA. The full env surface:

| Env var        | Purpose                                 | Default                        |
|----------------|-----------------------------------------|--------------------------------|
| `SECRET_KEY`   | Signs tokens **and encrypts stored credentials at rest** | *(required — the only must-set)* |
| `DATABASE_URL` | Data store; SQLite file or Postgres DSN | `sqlite:///./open-refinery.db` |
| `PORT`         | HTTP port                               | `8000`                         |
| `LOG_LEVEL`    | Logging verbosity                       | `INFO`                         |

That's it. Install with `pip`/`uv`, run `open-refinery serve` (background it
however you like — `&`, `nohup`, `screen`, `tmux`, or a process manager), open
the browser, complete setup. No Docker, no daemon manager, no external database
— SQLite ships with Python.

### Connections are token-based, entered in the UI

All external connections — GitHub, GitLab, Jira, Linear, model providers, MCP
servers, backend APIs — are configured through the UI by pasting a **token** (or
completing an OAuth flow). Tokens are encrypted with `SECRET_KEY`, never logged,
shown once, and rotatable/revocable from the UI. No credential ever lives in an
env var or config file.

Distributed as a pip/uv package; a single `open-refinery serve` process serves
API + SPA. Ships as a PyPI release — no container or orchestration required.

## Roadmap

| Version | Deliverable                                                          |
|---------|----------------------------------------------------------------------|
Renumbered to reality: 0.3.0 shipped far more than originally scoped (process
engine, oversight, metrics, and the dashboard all landed in it).

| 0.1.0 ✅ | Core factory: authorize → produce → record → audit → log. |
| 0.2.0 ✅ | Persistence (SQLite; Postgres seam), **versioned migrations** (`PRAGMA user_version` + append-only list), durable SQL event store. Entities: `User`, `Repository`, `Process`, `WorkItem`. |
| 0.3.0 ✅ | Full app: FastAPI + auth (email/password, API tokens, **GitHub OAuth**, roles, ownership scoping, first-run wizard); **process engine** (steps + feedback loops, board/doctrine); **oversight** L0–L4 + approvals + attestations; **metrics** read-model; audit API; **React/shadcn dashboard** (bundled in the wheel); seeds. `pip install` + `serve`. |
| 0.4.0   | **Integrations** (in progress): adapter framework + GitHub (import repos), then GitLab / Jira / Linear; UI token/OAuth connection, **encrypted credential store**, sync. Dashboard integrations view. |
| 0.5.0   | Targets + routing + quotas: model/MCP/API targets, route rules, budgets, cost tracking, rate limits — all UI-managed. |
| 0.6.0   | Governance policy layer + content filtering over transitions/targets. |
| 0.7.0   | Hardening: token rotation, secret-handling review, RBAC edge cases, retention/residency; more OAuth providers; LangGraph stage executors. |
| 1.0.0   | Deployable release: `pip install open-refinery && open-refinery serve` self-host (`SECRET_KEY` only), full docs. |

## Open questions

- **Teams**: ownership is per-user in 0.x. Do we need team ownership (shared
  visibility) before 1.0, or defer? Affects the scoping model.
- **Repo actions**: what does a stage *do* to a repo — run a command, open a
  PR, call a tool? Defines the executor seam (0.8.0).
- **Secrets at rest**: tokens are UI-entered and encrypted with `SECRET_KEY`
  (decided). Open: key rotation and re-encryption strategy; optional KMS/secret
  store for larger deployments. Security review before 0.6.0.
- **`deepagents` adoption**: LangGraph checkpointers already give durable
  orchestration state. `deepagents` adds a planning tool, subagents, and
  virtual-FS backends (`StateBackend` thread-scoped, `StoreBackend` durable
  cross-thread). Adopt *only* when a stage action runs an agentic planning /
  subagent loop needing scratchpad memory — its `StoreBackend` can persist to
  our DB. Not needed for the process state machine. Decide per stage-executor.
- **Real-time**: does the board need live updates (websockets/SSE) or is poll
  enough for 1.0?
- **OAuth vs PAT per integration**: some sources (GitHub, GitLab) support OAuth
  apps as well as personal tokens — which per adapter, and does OAuth conflict
  with "minimal env"? (OAuth apps need client id/secret somewhere.)

## Non-goals (for now)

- **Multi-tenancy / multi-org.** One install serves exactly one organization by
  design — self-hosted, single-tenant. There is no org/tenant entity; users,
  repos, and processes all live in the one company that runs the instance. The
  standards cascade (platform ▸ developer) is *within* that single org.
- Building a CI system — open-refinery orchestrates *processes*, it is not a
  build runner.
- Speculative process archetypes beyond board + doctrine until asked.
