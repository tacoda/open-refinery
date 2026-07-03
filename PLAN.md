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

## Concern ownership: platform vs harness

The boundary that defines scope. **Platform concerns** (out-of-process,
fleet-wide) are open-refinery's job; **harness concerns** (in-process,
task-specific) belong to the calling agent/app and are explicit non-goals.
(Framing from Traefik's harness-vs-platform mental model — see README credits.)

### Platform concerns — owned by open-refinery

| Concern | Why platform-owned | Status |
|---------|--------------------|--------|
| Identity of the calling actor | Consistent across harnesses; required for audit | ✅ users + API tokens / sessions; every event actor-stamped |
| Authorization to invoke a tool/target | **Role-based** (RBAC), enforced across agents; cannot be self-asserted | ✅ executor enforces a role-based `invoke` policy per target kind |
| Secrets injection into calls | Secrets must not enter harness process memory | ✅ executor decrypts the target credential and hands it to the backend at the call site; never returned |
| Rate limits & concurrency caps | Multi-tenant fairness, provider quotas | ◐ usage quotas enforced pre-call; rate/concurrency windows pending (0.9) |
| Per-policy model routing (cost, region, compliance) | Org-wide policy, not per-task | ◐ routes by process/step/priority with failover; cost/region/compliance policy inputs pending |
| Failover when a provider degrades | Transparent to the harness; consistent SLOs | ✅ executor fails over across candidate routes by priority |
| Content filtering & DLP on prompts/responses | Regulatory / data-protection consistency | ✅ executor content-filters payload and response at the boundary |
| Audit trail of every model & tool call | Single source of truth for compliance | ✅ `invoke` / `invoke-failed` events, subject-linked, on every call |
| Traffic-graph observability & correlation | Cross-agent visibility | ◐ metrics + audit feed; cross-agent graph is roadmap |
| Cost attribution by team/product | Enforced at the call site, not self-reported | ◐ executor records units per call; team/product attribution needs teams (0.9) |

Legend: ✅ implemented · ◐ partial / in progress · ○ planned.

### Harness concerns — NOT open-refinery (non-goals)

These belong to the harness (pds, pyness, any agent app). open-refinery does not
implement them; it governs the *calls* a harness makes, not its internal loop.

| Concern | Why harness-owned |
|---------|-------------------|
| Tool selection for a task | Task-specific; depends on prompt + intermediate state |
| Per-task model selection (capability fit) | Depends on sub-task semantics |
| Sub-agent delegation logic | Internal to one agent's planning |
| Context-window compression | Intra-loop performance optimization |
| Self-verification of model output | Task correctness within a single agent |
| Eval & tracing of agent reasoning | Reasoning is internal (harness-native observability) |
| Session persistence & checkpointing | Internal to the agent lifecycle |

## Customizability & agnosticism (core pillar)

open-refinery works at a **higher level than any specific tool**. A team defines
their **processes** as they actually work; everything a process touches is
pluggable and **agnostic**:

- **Work board / methodology** — board (kanban) or doctrine, arbitrary steps and
  feedback loops; the team defines the shape.
- **Code host** — GitHub, GitLab, … (integration adapters).
- **Work tracker** — Jira, Linear, … (integration adapters).
- **Model / provider** — any model target; routed per process/step (executor
  backends).
- **Harness tool** — Claude Code, Cursor, any agent/app. Harnesses call *through*
  the platform; open-refinery neither knows nor cares which one — it governs the
  calls, not the tool.

**It's the upper (governance) layers that are fully customizable** — everything
UI-managed, so a team defines *how their system works*:

- **Processes** — steps, transitions, feedback loops, archetype.
- **Oversight & risk profile** — autonomy level (L0–L4), gated steps, required
  checks, `min_approver_role`, and the **approval chain** (e.g. senior → platform).
- **Policy** — role-based allow/deny rules over actions and resources.
- **Routing** — which target serves which process/step, with priority/failover.
- **Quotas** — usage caps per target.
- **Roles & standards** — the authority ladder and the standards cascade
  (platform sets org policy; developers set project standards).

The lower layers (code host, tracker, model provider, harness tool) are agnostic
connectors chosen by the project. **Every external source is an integration**,
connected in the UI via an **API token or OAuth** — the same pattern across code
hosts, trackers, model providers, and harness tools. All of them are
**ports and adapters**: a small port (a registry of callables / a Protocol) with
one adapter per vendor (`ADAPTERS`, `EXECUTORS`, `PROVIDERS`). Adding a tool is
writing an adapter behind an existing port
(see `.claude/references/ports-and-adapters.md`), never changing the governed
core. If a feature forces the core to know a specific vendor, that's a design
smell — push it into an adapter.

*Consistency to reach for pre-1.0:* targets (model/MCP/API) should support the
same **token-or-OAuth** connect that integrations already do (targets are
token-only today; OAuth-connect for them is additive).

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
| `User`       | Authenticated principal. Email, password hash, role (a configured `Role` by name), hashed API token. |
| `Role`       | **Admin-configurable** authority tier: name + rank. Seeded developer/platform/admin; admins add/re-rank. All rank checks (approvals, invitations) resolve against it. |
| `Pack`       | A code-defined, role-gated bundle of starter `Standard`s for a topic (software/charter for developers, platform/infrastructure for platform, org-policy for admin). Enabled/disabled on demand; a `PackState` tracks which are on. |
| `Standard`   | A unit of guidance (topic + title + body) seeded by an enabled pack; readable by any authenticated user. |
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
| `ApprovalWorkflow` | Admin-configured approval **chain** (ordered roles) for governance changes at a role **layer**. |
| `ChangeProposal`   | A proposed governance change walking a layer's workflow: **accept / deny / feedback (revise & resubmit)**, distinct signer per slot; applies the change (e.g. create a policy authored at the proposer's layer) on full accept. |
| `Claim`      | A stated behavior on a repo **surface** (charter/harness/code) with instruction/gate backing flags. Drives coverage, imitation-surface, and drift analysis. |
| `Attestation`| A signed claim that a check passed (evals, tests, code-health, content-filter) — attached to the transition's provenance. |
| `Policy`     | An **authored** governed harness artifact (users create these): `kind` ∈ rule / skill / command / agent (hooks TBD). A **rule** is an allow/deny constraint (`effect`/`role`/`action`/`resource`), deny-overrides. A **strict** flag locks a rule against lower-layer override (strict default is an admin Setting). Skills/commands/agents carry `content`. Packs are the **starter** counterpart — pre-built bundles that seed a starting set. |

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
- **Roles** — five roles on an authority ladder (`developer` < `senior` <
  `lead` < `platform` < `admin`). Each has its own concerns, and each **suggests
  changes at the next layer up** that the role above **approves and applies**:
  - `developer` — a **subset of senior**; drives work on their own repos. Most
    risk-restricted: gated moves need sign-off from a higher role.
  - `senior` — works at the **repo level**; approves developers' risky moves and
    may **suggest team-layer changes** (which a lead approves/applies).
  - `lead` — **approves and applies seniors' team-layer suggestions**, and may
    **suggest infrastructure changes** (which platform approves/applies).
  - `platform` — **approves lead's infrastructure suggestions**; owns org/team
    policy and the governance surface (integrations, targets, routes, quotas,
    processes, oversight, policies).
  - `admin` — **observability, reporting, insights, and accountability.** Reviews
    metrics and **insights**, generates reports, understands usage and
    **experiment results**, manages users, and audits the full trail. Admin *can*
    access work and policies but
    **does not drive work or define platform/team policy** — that's not their
    role or main workflow (the UI surfaces the high-level view; operational
    detail is drill-in, not default).
- **Cascading suggestions** *(roadmap)*: anyone can propose a change (even a
  junior proposing infrastructure); it **cascades up the chain** through each
  approving level. At every step the reviewer can **accept** (advance to the next
  level / apply at the top), **deny** (stop), or give **feedback** (return to the
  proposer to revise and resubmit). Extends the chained-approval queue with the
  three-outcome step and an escalation path.
- **Risk profile is per-process and UI-configurable**: oversight level (L0–L4),
  gated steps, required checks, and **`min_approver_role`** together define how
  much oversight a process demands and who may approve — not hardcoded.
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
| 0.4.0 ✅ | **Integrations**: adapter framework + GitHub & GitLab (import repos) and Jira & Linear (**work-item sync**, deduped by external ref); UI token *or* OAuth connection (per-provider gated), **encrypted credential store**, disconnect, idempotent import. Dashboard integrations + sync view. |
| 0.5.0 ✅ | **Data-layer ORM — SQLModel** (SQLAlchemy + Pydantic): entities are SQLModel table models; modules use per-request `Session`s; `connect()` returns a Session, `engine_for()` backs the web layer. Migration runner + audit event store kept. Portable toward other backends (Postgres, …). |
| 0.6.0 ◐ | Targets + routing + quotas: model/MCP/API targets (encrypted creds), route rules (process/step/priority resolution), usage quotas enforced pre-call — all UI-managed. Remaining: rate/concurrency windows, failover, cost attribution (with the executor). |
| 0.7.0 ◐ | Governance policy layer (role-based allow/deny rules, deny-overrides, enforced on transitions) + content filtering (secret/PII redaction). Remaining: policy at the target-invocation seam (with the executor), DLP config. |
| 0.8.0 ✅ | **Executor** — the governed call site (`POST /execute`): resolve route → **role-based invoke authorization** → **quota** → **secrets injection** (decrypt + hand to backend, never returned) → **content filter** in/out → pluggable backend → audit (`invoke`/`invoke-failed`), with **failover** across routes. Ships a stub backend; real model/MCP/API backends register in `EXECUTORS`. |
| 0.9.0 ◐ | Hardening: **`senior` role** (four-role ladder) with a **configurable per-process risk profile** (oversight + gates + checks + `min_approver_role`); **API token rotation**; seeds confirmed opt-in. |
| 0.10.0 ✅ | **Async approval queue** — request→approve-later with a pending-approvals view, and **chained approvals** (`approval_chain`, e.g. senior *then* platform; distinct signer per slot, in order). Plus DX: self-hosted `/api-docs`, OpenAPI→TS type parity, `.claude/references/`. |
| 0.11.0 ✅ | **Structured output in the executor** — a target may declare an `output_schema`; the executor validates the model's output against it, content-filters string leaves, and persists it **structured** (see `.claude/rules/structured-output.md`). Real backends (Anthropic / OpenAI / MCP) next. |
| 0.12.0 ✅ | **User invitations** — a role invites *lower* roles by email (admin→any, platform→senior & below, senior→developer); invite carries an **expiring token** (default 1 week, configurable) and the assigned role. The invitee opens the link and **sets their own password** to register. Email is a **port/adapter** (default: Linux `mail`); the email service and its credentials are **configurable in the UI by admin/platform** (another provider — SMTP, SendGrid, … — can be swapped in), stored in the DB settings (see 0.12.5). |
| 0.12.5 ✅ | **Config in the DB, not env** — encrypted `Setting` store; OAuth provider client id/secret resolved from DB settings (env fallback), edited in the UI by platform/admin (`/settings`, Settings tab). **Only `SECRET_KEY` is required in the environment.** |
| 0.13.0  | **Roles + governance foundation.** Roles are **admin-configurable data** (seeded developer/platform/admin; add/re-rank via `/roles`); rank checks, invitations, approval chains resolve from the store. **Packs** — opt-in, role-gated topic bundles of starter `Standard`s (software/charter for developers; platform/infrastructure for platform; org-policy for admin), enable/disable via CLI (`packs`) and the dashboard **Packs** tab; the base install seeds almost nothing. **Policies become governed harness artifacts** — `kind` ∈ rule / skill / command / agent (hooks TBD), each with a **strict** flag (a lower layer may not override a strict rule; strict rules decide alone, deny-overrides among them). Strict's **default is an admin Setting** (`policy.strict_default`, off unless set). |
| 0.13.6 ✅ | **Real Anthropic model backend** — executor `model` targets dispatch by provider; a credentialed Anthropic target makes a real Messages API call (official SDK, honors `output_schema` via structured outputs, refusal → failover, output-token units). No credential → stub (offline-safe). `pip install open-refinery[providers]`. |
| 0.13.7 ✅ | **Real OpenAI backend** (Chat Completions, honors `output_schema`) registered in `MODEL_BACKENDS`; backends connect by **API key or OAuth token** (`api_key`/`token`/`access_token`). `open-refinery[providers]` pulls anthropic + openai. |
| 0.13.x  | **MCP transport + target OAuth handshake** — real MCP backend (JSON-RPC over Streamable HTTP) and the interactive OAuth authorize→callback→store flow for targets (parity with the GitHub integration). Then: rate/concurrency windows; retention/purge & residency; cost attribution by team. |
| 0.13.x  | **Governance layer graph** — model the two override axes explicitly: **factory → harness → charter** and **platform → developer**. Strict-override precedence resolves along the graph (higher layer wins unless it allows override); every rule/skill/command/agent is tagged with the layer that defined it. |
| 0.13.2 ✅ | **Admin governance landscape** (`GET /governance` + Governance tab) — the role ladder with user counts, rules grouped by layer (author role rank), and what overrides what (strict rules shadowing a lower layer). Drift/violations stubbed pending enforcement-outcome logging. |
| 0.13.3 ✅ | **Per-layer approval workflows** — admin defines, per role layer, the ordered chain that must approve a governance change (`/approval-workflows`); a **change proposal** (`/proposals`) walks it with **accept / deny / feedback (revise & resubmit)**, distinct signer per slot, applying the change on full accept (policy-create first). Dashboard **Proposals** tab. |
| 0.13.4 ✅ | **Governance analysis — poison flags** (`GET /governance/analysis`, per-role): **dead** (shadowed) rules, **contradictions**, **redundant** rules, and **prompt_injection** in artifact content — with per-type metrics + per-finding insights; populates the landscape `violations`. Governance-flags card in Metrics. (True enforcement-vs-config drift → the repo-level slice below.) |
| 0.13.5 ✅ | **Repo-level drift & coverage** (model + math). Per-repo `Claim`s on charter/harness/code surfaces with instruction+gate flags → **coverage**/health score, **imitation surfaces** (no instruction+gate = false coverage, prime targets), and **drift** across all three axes. `GET /repositories/{id}/coverage`, claims CRUD, Coverage tab. Claims authored/seeded for now. |
| 0.13.x / 0.15.0 | **Auto-ingest repo surfaces** — populate `Claim`s from real `.claude/` charter, harness config, and code signals (via the GitHub integration) so coverage/drift run on reality, not seeded claims. Feeds per-repo health scores + insights (with the 0.15.0 debt audits). |
| 0.13.x  | **Packs bundle harness artifacts** — a pack seeds not just prose `Standard`s but the same governed artifacts a policy carries: **rules / skills / commands / agents**. Example: a **TDD** pack ships a `tdd` command or skill. Artifacts are **namespaced** (company / department / team / project — exact scheme TBD). Enabling a pack seeds its artifacts (pack-tagged so disable removes them); design the pack-item ↔ Policy-artifact unification here. |
| 0.17.0  | **Cascading suggestions** — anyone proposes a change; it escalates up the role chain (senior→lead team changes, lead→platform infrastructure). Each level can **accept** (advance/apply), **deny** (stop), or give **feedback** (return to revise & resubmit). Extends the approval queue with a three-outcome step. |
| 0.16.0  | **Eval / experiment system** — run experiments at each layer (project, platform, harness, charter) using the scientific method: a **hypothesis**, the **change** under test, **evals before and after**, and a **statistical analysis** of the observed effect (is the difference real?). Work can be run through the system **marked as an experiment** (tagged, isolated from normal metrics), and experiments can be **iterated** like engineers do — refine hypothesis/change and re-run, tracking rounds over time and tying into the health scores. |
| 0.13.8 ✅ | **Debt audits & health** — `run_audit`/`GET /audits`/`/health/areas` score **factory** (rule config), **harness** (artifact injection), **charter** (repo coverage) 0–100 with per-area insights; persisted for tracking. Audits tab. Signals reuse governance analysis + repo coverage. (Resolve/learn/prune workflow can extend this later.) |
| 0.13.x  | **Ingest repo surfaces** — `POST /repositories/{id}/ingest` reads real `.claude/` charter, harness config, and code signals via the GitHub integration to populate `Claim`s (triggered per repo like tracker sync, later schedulable), so coverage/charter health run on reality. |
| 0.14.0  | **Webhook registration** — register webhook URLs (with an event filter + signing secret) so audit events fan out to external services. Endpoints are FastAPI routes, so they appear in `/api-docs` automatically; the outbound payload is documented there too. |
| 1.0.0   | Deployable release + full docs. **UI revamp** (to be defined). **Schema frozen** — post-1.0 changes are additive-only (via the migration runner), no restructures. |
| post-1.0 | **Repo relations / systems** — platform can define work and **relations between repositories** that constitute a service, microservice group, or server; customizable at the platform level (repos compose into systems). |
| post-1.0 | **Admin overview UX** — admin can do everything, but the dashboard presents only **high-level** state prominently; details (a specific user, job, or rule) are reached by intentional drill-in, not shown by default. (Feeds the 1.0 UI revamp.) |
| post-1.0 | **MFA requirement** — admin-managed multi-factor auth policy (whether MFA is required, and for which roles); defaults off. |
| post-1.0 | **Background job runner (possibly Celery)** — move long-running backend work (real model calls, ingestion, audits, evals) onto a task queue so the UI stays snappy. Keep it optional: the in-process path stays the zero-dependency default; Celery (or similar) is opt-in for scale. Weigh against the single-`serve`-process, minimal-setup constraint. |
| post-1.0 | **Demo video** — a Puppeteer script drives the seeded dashboard at human speed with a highlighted cursor + click ripples, recorded to mp4 (ffmpeg). Then a **GitHub Pages project site** (landing page featuring the demo video). |

**Schema stability.** All core entities land before 1.0 so the schema is stable
at release. Pre-1.0, breaking restructures are accepted (recreate the DB);
**at 1.0 the schema freezes** and later changes are additive (new tables /
nullable columns via the migration runner) — no churn. Teams (vs per-user
ownership) would arrive additively (a `Team` table + optional `team_id`), so
deferring them past 1.0 carries no restructure risk.

**Seeds are opt-in and minimal.** A fresh install seeds only the role ladder
(developer/platform/admin) and prompts the setup wizard for the first admin —
no topic content. Curated topic content ships as **packs**: role-gated bundles
enabled on demand via `open-refinery packs enable <key> --as-user <email>` or the
dashboard Packs tab. `open-refinery seed` still loads a full *example* dataset
(sample users/repos/processes) for evaluation only — never run in normal operation.

## Open questions

- **Data-layer ORM (0.5.0) — SQLModel + Pydantic** (decided). Replace the
  hand-written `sqlite3` SQL behind `store.register_schema` with SQLModel table
  models. Known design points from a spike:
  - `connect()` returns a `Session`; the shared-connection design + in-memory
    tests mean modules port **together**, not incrementally.
  - Web needs a **session per request** (SQLAlchemy Session isn't thread-safe);
    the app holds the engine, a dependency yields a Session.
  - Tests that compare returned rows by value (`==`) rely on the session
    **identity map** returning the same instance — keep one session per test.
  - `Process` structure (stages/transitions/gates/checks) → **JSON columns**;
    `can_transition`/`required_checks` become model methods.
  - Metrics aggregations (GROUP BY, MIN/MAX) → SQLAlchemy `func`/raw `text` via
    the session. `Record` stays the provenance value object; the SQL sink writes
    `Event` models. Keep the `PRAGMA user_version` migration runner (run on the
    engine's raw DBAPI connection).
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
