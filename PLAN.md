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
| `Experiment` / `EvalRun` | A scientific experiment (hypothesis, change, layer) with before/after metric samples; analysis reports effect size + significance + a verdict. |
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

## Road to 2.0 (sequenced)

Ordered milestones from 1.13.0 → 2.0.0. Focus is **feature coverage**. Deferred
to 2.x infra (may revisit): **Postgres**, **MFA**, **Celery/Redis scale-out** —
not feature gaps, so out of the 2.0 line. One slot reserved for a to-be-recalled
item. Each milestone is a shippable minor; 2.0.0 is the cut.

| # | Target | Milestone | Notes / scope |
|---|--------|-----------|---------------|
| M1 ✅ | 1.14.0 | **Enforcement v2** | `POST /authorize` pre-action seam (harness verifies identity + intent before a tool/command/host-egress action; denials 403 + audited); **per-namespace whitelists** in `decide`/`enforce`. Completes the security thesis (v1 = 1.5.0). |
| M2 ✅ | 1.15.0 | **Teams + usage ledger + concurrency caps** | `Team` + `User.team_id`; **usage ledger** (`LedgerEntry` per invoke — audit digests units away); **cost attribution by team** (`GET /usage`); live in-flight **concurrency caps** (in-process `slot()`, `ConcurrencyExceeded`→429). Teams + Usage tabs. Migration v13. |
| M3 ✅ | 1.16.0 | **Routing policy inputs + traffic graph** | targets carry region/compliance/unit_cost; org routing policy (`GET/PUT /routing-policy`) filters on region/compliance + prefers cost; unmet requirement → no route. Traffic graph (`GET /traffic`) from the ledger — actor→target edges weighted by calls+units. Migration v14. |
| M4 ✅ | 1.17.0 | **Live logs + rollback apply-side** | per-run **live log tail** over the WS hub (`POST/GET /work-items/{id}/logs`, in-process ring buffer, `type:"log"`); **rollback apply-status** — harness reports applied/failed (`POST …/rollback/applied`), recorded as `rollback-applied` audit event + history row (closes the "we only emit the plan" gap). |
| M5 ✅ | 1.18.0 | **UI/UX revamp round 2** | Visibility-first **Overview** home (glanceable highlight cards for the few actionable things — approvals/denials/failures/rollbacks-to-apply/WIP — with drill-in) + **Work board** grouped by stage where a card opens a right-hand **detail/action Drawer** (move/attest/history/rollback/logs/post-mortem). Reusable `Drawer` slide-over. Broader Vitest. UI-only, no schema change; admin tables unchanged. Next (2.x): extend the drawer pattern to the remaining admin surfaces. |
| M6 ✅ | 2.0.0 | **Cut 2.0** | Docs pass (README + ARCHITECTURE refreshed for the full 1.x surface); milestone cut — schema still frozen at 1.0, all 1.x additive + backward-compatible, so any 1.x → 2.0 is a drop-in upgrade. Tagged 2.0.0. |

**Road to 2.0 complete — 2.0.0 released.** 2.0-defining: M1 (security) + M5
(visibility). **Deferred to 2.x:** Postgres, MFA, Celery/Redis scale-out, the
drawer pattern across the remaining admin surfaces (+ a reserved slot dropped for
now — revisit later).

**2.1.0 (post-2.0 UX + agents).** Left icon sidebar + brand/login; role-aware nav
+ developer read-only "My rules"; GitHub Issues connector + tracker **workflow
discovery**; OAuth-first shared connect; **first-run setup wizard** (connect →
import → pack → process-from-columns → first item); **harness identities** (auth
for Claude Code et al. — role-scoped service accounts, token + OAuth device flow,
governed by the proactive controls); concept visuals (process pipeline, layer
lattice, icon/trend cards, humanized metrics). Migration v15.

**2.2.0 (role authorization model).** Developer/platform/admin scoped to their
concerns, enforced backend (403 via a central `_AUTHZ_RULES` matrix + middleware)
and UI; admin re-scoped to oversight-only; invites at your level or lower.

## Governance-maturity track (2.3.0 → 2.7.0) — regulated / large-org oversight

Ten features that make "prove your governance" a button, sequenced by dependency
and buyer pull. Guiding constraints: **keep the dashboard simple** (each feature
adds a focused surface, reuses the drawer/overview patterns); **schema frozen at
1.0** (additive tables/columns + a migration per DB change); every new capability
is itself audited and role-scoped.

### Phase 1 — Provable governance (the audit/evidence trio) → 2.3.0
*Why:* regulated buyers ask "prove the control existed and the log wasn't
altered." This phase answers it. Highest pull; foundational for later phases.
- **1.1 Tamper-evident audit ✅** — events hash-chained (`entry_hash =
  sha256(prev+fields)`), `GET /audit/verify` (detects edits/insertions/mid-
  deletions), signed export (`/audit/export`, HMAC over head) + **filtered CSV
  export** (`/audit/export.csv`). Upgrade backfill chains pre-2.3 events. UI:
  Verify-trail seal + Export CSV/signed. Migration v16. Shipped 2.3.0. Also folded
  in more concept visuals (approval chains + work-item history as pipelines).
- **1.2 Versioned policy history ✅** — every create/delete recorded as an
  immutable `PolicyVersion` (snapshot + who/when/why); `GET /policies/history`,
  `GET /policies/at?t=` reconstructs the rule set in effect at a timestamp; UI
  History drawer with point-in-time + change log. Shipped 2.4.0.
- **1.3 Compliance evidence packs + auditor role ✅** — `GET /evidence?framework=`
  maps SOC2/ISO27001/HIPAA/GDPR controls to platform evidence (chain integrity,
  RBAC/enforcement, policy versioning + workflows, attestations) with a met/
  partial/attention status + coverage %; downloadable. Time-boxed read-only
  **auditor** grants (`/auditor-grants`, mint/revoke) — a scoped principal that
  reads evidence + audit and mutates nothing; auditor sign-in on the login. UI:
  Evidence tab. Shipped 2.5.0. **Phase 1 complete.**

### Phase 2 — Proactive oversight → 2.4.0
*Why:* "lights-on" = catch and route problems before the post-mortem.
- **2.1 Governance notifications ✅** — `NotificationRule`s match an audit recipe
  (blank = any) → Slack (incoming webhook) / email / plain webhook; dispatched
  best-effort on every audit write. Policy changes now emit `policy-change` audit
  events (chained + notifiable). `/notification-rules` CRUD; Notifications card in
  Settings. Shipped 2.6.0.
- **2.2 Approval SLAs + escalation + segregation-of-duties ✅** — a process carries
  an `approval_sla_hours`; each request derives a `due_at`. Overdue pending
  requests escalate once (an `approval-overdue` audit event, chained + notifiable,
  with a dedup stamp) via the serve-path scheduler sweep; `GET /approvals/overdue`
  lists them. SoD: requester ≠ approver, plus the existing one-signature-per-chain
  rule. Shipped 2.7.0.
- **2.3 Anomaly / behavioral alerting** — flag denial spikes, off-hours agent
  activity, harness-over-norm, privilege drift, mass changes. Overview "Attention"
  feed. Uses 2.1 to notify.

### Phase 3 — Enterprise identity & access → 2.5.0
*Why:* non-negotiable for large orgs; closes the deferred MFA item.
- **3.1 SSO (SAML / OIDC) + MFA** — log in via the org IdP; enforce MFA. Keeps the
  fixed three-role model, fed from the IdP.
- **3.2 SCIM provisioning + group→role mapping** — auto provision/deprovision;
  map IdP groups to developer/platform/admin.
- **3.3 Access recertification campaigns** — scheduled "re-attest access/roles"
  campaigns tracked to completion, overdue flagged. Depends on 3.1/3.2.

### Phase 4 — Data governance & resilience → 2.6.0
*Why:* regulated data can't cross the wrong boundary; emergencies must stay
accountable.
- **4.1 Data classification + residency** — tag repos/work/targets with a data
  class (PII/PHI/secret) + residency. New columns; additive.
- **4.2 DLP enforcement per class** — extend the routing/egress gates to enforce
  by data class + per-class redaction rules.
- **4.3 Break-glass emergency access** — controlled, time-boxed, heavily-audited
  override that forces a mandatory post-incident review.

### Phase 5 — Reporting & trust → 2.7.0
*Why:* push posture to the accountable; make the platform's own governance
legible. (Not a 3.0 cut — more is planned before 3.0.)
- **5.1 Scheduled signed reports** — periodic PDF/CSV of posture, denials,
  approvals, coverage, SoD (signed per 1.1). Depends on 1.1 + 1.3.
- **5.2 Trust page + docs pass** — optional public read-only posture page; full
  docs/upgrade pass.

**Feature → phase map:** 1→P1.1 · 2→P1.3 · 3→P1.2 · 4→P2.3 · 5→P2.2 · 6→P4.3 ·
7→P3.1/3.2 · 8→P4.1/4.2 · 9→P3.3 · 10→P2.1 (notify) + P5.1 (reports).

**Backlog (honorable mentions):** usage/cost budgets with hard caps · legal hold /
immutable retention · multi-environment promotion gates (dev→staging→prod) ·
Postgres / Celery-Redis scale-out (deferred infra).

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
| 0.13.11 ✅ | **MCP transport** — real `mcp` backend: JSON-RPC `tools/call` over HTTP (SSE-framed replies tolerated), connects by API key or OAuth token, honors `output_schema` via the server's `structuredContent`. Registered as `EXECUTORS["mcp"]`. |
| 0.13.13 ✅ | **Target OAuth handshake** — `POST /targets/{id}/oauth/{provider}/start` + callback exchange (reuses `oauth.PROVIDERS` + configured client creds), storing `{provider, access_token}` in the target credential; per-target OAuth connect buttons. `set_target_credential` added. |
| 0.13.17 ✅ | **Generic `api` backend + quota rate windows** — real HTTP POST for `api` targets; quotas gain a rolling `window_seconds` (per-minute/hour caps, 0 = lifetime). |
| 0.13.18 ✅ | **Retention/purge + experiment-tagged runs** — `POST /audit/purge?days=N` (admin) drops old audit events; `execute(experiment_id, arm)` feeds a tagged run's units into the control/treatment eval automatically. (Residency = self-hosted deploy concern, documented.) |
| post-1.0 | **Concurrency limits + cost attribution by team** — concurrency caps need live in-flight tracking (pairs with the job runner); cost-by-team needs the Team model + a usage ledger (units on the event/ledger). Deferred with those. |
| 1.13.0 ✅ | **Rollback covers infra + DNS; reverse engine open-ended** — `infra` (restore prior state/version) + `dns` (restore prior record) added; `reverse_plan` stops whitelisting — `code`/`migrations` stay bespoke, every other `{name:{old,new}}` map reverses generically, so any surface the harness reports (queues/cdn/certs/iam/cron/…) rolls back with no code change. UI renders whatever categories a plan holds. Material-safety rule spans all categories (refs only, plaintext + audited). |
| 1.12.0 ✅ | **Rollback covers secret/credential rotations** — `secrets` change-set category reverses a rotation to the prior credential **reference** (version/rotation id, vault path) — never the material (change set is plaintext + audited); harness re-activates out of band. |
| 1.11.0 ✅ | **Rollback covers env + data + services** — change set adds `env` (env var → restore prior value), `data` (data update → restore prior snapshot), and `services` (vendor swap → restore prior vendor) alongside code/migrations/config/libraries; the reverse plan now unwinds the full deployment. |
| 1.10.0 ✅ | **Rollbacks (first-class, governed)** — append-only `StageHistory` per work item; revert to a known-good prior stage, gated by policy action `rollback` (enforcement-mode-aware, refusals audited) + structured `rollback` audit event. A transition can carry the **PR's change set** (`code`/`migrations`/`config`/`libraries`); rollback computes a **reverse plan** (code revert-to-commit, migration downgrades newest-first, config + library versions restored) for the harness to apply — the platform governs the revert, doesn't run git/alembic/pip. `GET …/history`, `POST …/rollback`, optional `changes` on `…/transition`. |
| 1.9.0 ✅ | **Live UI via WebSockets** — `/ws` (bearer token) streams job-status + new-audit-event updates via an in-process pub/sub hub (fans out from any thread); ● live indicator + job-done toasts. Redis-backed hub can replace it for multi-process later. Next: per-run **live logs** streaming. |
| 1.2.0 ✅ | **Governance layer graph** — explicit artifact axis (`factory` > `harness` > `charter`, `Policy.layer`) alongside the role axis; strict precedence resolves on the (role-rank, layer) lattice in `decide`/`enforce`, landscape overrides, and poison analysis. Pack artifacts layer-tagged; Policies UI shows layer. |
| 0.13.2 ✅ | **Admin governance landscape** (`GET /governance` + Governance tab) — the role ladder with user counts, rules grouped by layer (author role rank), and what overrides what (strict rules shadowing a lower layer). Drift/violations stubbed pending enforcement-outcome logging. |
| 0.13.3 ✅ | **Per-layer approval workflows** — admin defines, per role layer, the ordered chain that must approve a governance change (`/approval-workflows`); a **change proposal** (`/proposals`) walks it with **accept / deny / feedback (revise & resubmit)**, distinct signer per slot, applying the change on full accept (policy-create first). Dashboard **Proposals** tab. |
| 0.13.4 ✅ | **Governance analysis — poison flags** (`GET /governance/analysis`, per-role): **dead** (shadowed) rules, **contradictions**, **redundant** rules, and **prompt_injection** in artifact content — with per-type metrics + per-finding insights; populates the landscape `violations`. Governance-flags card in Metrics. (True enforcement-vs-config drift → the repo-level slice below.) |
| 0.13.5 ✅ | **Repo-level drift & coverage** (model + math). Per-repo `Claim`s on charter/harness/code surfaces with instruction+gate flags → **coverage**/health score, **imitation surfaces** (no instruction+gate = false coverage, prime targets), and **drift** across all three axes. `GET /repositories/{id}/coverage`, claims CRUD, Coverage tab. Claims authored/seeded for now. |
| 0.13.x / 0.15.0 | **Auto-ingest repo surfaces** — populate `Claim`s from real `.claude/` charter, harness config, and code signals (via the GitHub integration) so coverage/drift run on reality, not seeded claims. Feeds per-repo health scores + insights (with the 0.15.0 debt audits). |
| 0.13.14 ✅ | **Starter-pack catalog expansion** — added `tdd`, `atdd`, `spec-driven`, `ui-verification` (Puppeteer/Playwright), and `tech-debt` (incl. a remediation-doctrine process) packs. README value prop refreshed (governance policy layer, configurable oversight strategy, human approval gates). |
| 1.1.0 ✅ | **Packs bundle harness artifacts** — packs seed governed `Policy` artifacts (rule / skill / command / agent), pack-tagged (removed on disable) and **namespaced** (`Policy.namespace`, e.g. `canon/tdd`, `org`). Starter artifacts: a `tdd` command, a `review` command, an org compliance-reviewer agent. |
| 0.13.16 ✅ | **Cascading suggestions** — with no configured workflow, a proposal auto-escalates **up the role ladder** from the proposer (lowest-above first); plus a free-text `suggestion` kind anyone can send up the chain (accept / deny / feedback per step; adopted on full accept). Completes the 0.17 cascading-suggestions goal atop the 0.13.3 approval workflows. |
| 0.13.15 ✅ | **Evals & experiments** — `Experiment` (hypothesis + change + layer), before/after `EvalRun`s per metric/round, and `analyze_experiment` (delta, Cohen's d, normal-approx z-test, verdict). Iterate by round (latest wins). `/experiments` + evals/analysis/conclude routes; Experiments tab; results stored structured. |
| 0.13.18 ✅ | **Experiment-tagged runs (control/treatment)** — `execute(experiment_id, arm)` auto-feeds a run's units into the before (control) / after (treatment) eval. Follow-up: isolate tagged runs from normal metrics; tie outcomes into debt-health; proper t-test/scipy for small-n. |
| 0.13.8 ✅ | **Debt audits & health** — `run_audit`/`GET /audits`/`/health/areas` score **factory** (rule config), **harness** (artifact injection), **charter** (repo coverage) 0–100 with per-area insights; persisted for tracking. Audits tab. Signals reuse governance analysis + repo coverage. (Resolve/learn/prune workflow can extend this later.) |
| 0.13.9 ✅ | **Ingest repo surfaces** — `POST /repositories/{id}/ingest` reads `.claude/` (charter), `CLAUDE.md`/`AGENTS.md` (harness), and code signals via the GitHub integration → `Claim`s with heuristic instruction/gate backing; idempotent. Ingest button on Coverage. Reader injectable (pipeline tested offline; live read best-effort). |
| 1.4.0 ✅ | **Ingest polish** — GitLab reader (parity with GitHub); per-repo integration linking (`Repository.integration_id`, source-picker in Repos, host fallback); richer code signals (CI, Dockerfile, Makefile, docs, pre-commit); readers dispatched by kind. |
| 1.8.0 ✅ | **Scheduled ingest** — per-repo `ingest_interval_hours`; in-process scheduler (serve-path daemon) enqueues background ingest jobs for due repos + stamps `last_ingest_at`. `/repositories/{id}/schedule`, Auto-ingest field. |
| 0.13.10 ✅ | **Webhooks** — register URLs (event filter + generated signing secret) so audit events fan out as HMAC-signed JSON POSTs; last-status recorded. `GET/POST/DELETE /webhooks`, Webhooks card in Settings. **Swagger `/api-docs` now has Authorize** (Bearer scheme) → live "Try it out". Delivery is synchronous best-effort; background runner is the post-1.0 job-queue item. |
| 1.0.0   | Deployable release + full docs. **UI revamp** — the dashboard has grown busy/jumbled (~17 tabs); reorganize (group work vs. governance vs. platform vs. insights vs. admin; progressive disclosure per the admin-overview item). **Marketplace-style Packs page** (browsable cards, enable/disable). **New palette:** purple primary accent, yellow highlight, red for failures/blocking, green for successes (replaces blue/green/purple/orange; keep semantic classes — no raw utilities in JSX). Graceful empty states everywhere *(landed 0.13.21)*. **Vitest** component tests with a **mocked API** covering empty / populated / error / role-gated states *(landed 0.13.21; expand coverage as the revamp lands)*. Grouped nav + progressive disclosure *(landed 0.13.22)*. **Docs pass + schema freeze landed in 1.0.0 — released.** ✅ **Schema frozen** — post-1.0 changes are additive-only. |
| ongoing | **Pack canon curation** — keep growing the catalog toward the full modern team-workflow / software-engineering / platform-engineering canon (and let packs seed rules/skills/commands/agents, not just standards + processes). |
| 1.3.0 ✅ | **Repo relations / systems** — a platform-level `System` groups repos (service / microservice group / server) with a governance-health rollup (avg coverage + total imitation surfaces). `/systems` routes + Systems tab. |
| post-1.0 | **Admin overview UX** — admin can do everything, but the dashboard presents only **high-level** state prominently; details (a specific user, job, or rule) are reached by intentional drill-in, not shown by default. (Feeds the 1.0 UI revamp.) |
| post-1.0 | **MFA requirement** — admin-managed multi-factor auth policy (whether MFA is required, and for which roles); defaults off. |
| 1.7.0 ✅ | **Background job runner (in-process)** — thread-based, zero-dep; `enqueue`/`Job`/`GET /jobs`, `?background=true` on audits + ingest. A **port** — Celery/RQ can back it later for horizontal scale (still opt-in; in-process stays the one-command default). Unblocks scheduled ingest + WebSocket progress. |
| post-1.0 ✅ | **GitHub Pages product site** — value-prop-first landing (problem → platform → features → get started) on the `gh-pages` branch; **live**. (Demo video dropped.) |
| **pre-2.0** | **Proactive enforcement layer (security/verification).** A gate that **stops unauthorized actions before they run** — distinct from observability/audit, which explains after the fact. Whitelist-first: an action proceeds only if explicitly permitted (default-deny), enforced at the action boundary (transitions, executor invokes, tool/command calls, target/host egress). Verify identity + intent against the policy set *before* acting; block + record the denial. |
| 1.5.0 ✅ | **Proactive enforcement layer (v1).** Admin `policy.enforcement` = `audit` (default-allow) or **`strict`** (whitelist / default-deny) at the transition + invoke gates; **every refused attempt is audited** (`denied` events). `decide(default_allow=)` + `enforcement_mode`; landscape shows the mode. The shift from *legible* to *restrained* automation. Next: extend gates (tool/command/host egress), per-namespace/layer whitelists, verify identity+intent. |
| **pre-2.0** | **UI/UX revamp (round 2)** — the dashboard is still confusing/intimidating. Make it **intuitive and approachable**, and move away from the CRUD look (walls of tables + forms). Direction: a **dynamic, workflow-oriented** layout — clean and minimal, not over the top; a primary list/board of the thing you're working on, and a **right-hand side pane (drawer)** where selecting an item reveals its detail plus the secondary operations/actions (create/edit inline, not separate form blocks). Task-oriented flows, sensible defaults, guidance/empty-state onboarding, plain language, progressive disclosure of advanced governance. **Visibility-first:** minimally highlight the few most important pieces of information to focus attention (surface what's relevant/actionable now), while keeping easy drill-in for single-item detail. Lean into visibility as the product's core value. Fold in broader Vitest coverage. |
| 1.6.0 ✅ | **Agent-run post-mortem** — `GET /work-items/{id}/postmortem` assembles the run (timeline, invoke-failures, policy denials, approvals, attestations, timings), deduces a root cause, and suggests follow-ups; Post-mortem toggle per work item. Next: richer payload capture (events store digests, not bodies) for deeper detail. |

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
