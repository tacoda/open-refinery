# Architecture

open-refinery is the **platform layer** that governs AI-driven software work.
Harnesses (agents, scripts, CI) call through it to reach targets (repos, models,
MCP servers, APIs). The platform governs *how* work reaches those targets:
identity, roles, authorization, provenance, an append-only audit trail, quotas,
content filtering, oversight, and metrics.

Two governed loops sit at the core — both are **deterministic plain code**, not
an agent deciding what happens next.

## 1. The transition loop (work items)

A work item moves through a **process** (ordered stages + allowed transitions,
board or doctrine archetype). Each move is governed:

```
transition(item, to, actor, approver?)
   ├─ validate the transition is allowed by the process
   ├─ enforce policy         (role-based allow/deny, deny-overrides)   ← policies.py
   ├─ check attestations      (required quality-gate checks passed)     ← attestations.py
   ├─ oversight gate          (approval if the process/step requires it) ← oversight.py
   ├─ move the item
   └─ record an append-only audit Event                                 ← store.py / provenance.py
```

Gated moves either take an inline approver or go through the **async approval
queue** with **chained approvals** (an ordered role chain, distinct signer per
slot). Order is load-bearing: authorize before moving; record only after a
successful move.

## 2. The executor pipeline (outbound calls)

When a step reaches a target, `execute()` runs the governed call site:

```
execute(process, step, payload, actor)
   ├─ resolve route → candidate targets (priority; step-specific wins)  ← targets.py
   │     └─ routing policy filters region/compliance, prefers cost      ← targets.py
   ├─ hold the team's live concurrency slot (over cap → 429)            ← concurrency.py
   ├─ role-based invoke authorization                                   ← policies.py
   ├─ consume quota (pre-call; windowed rate caps)                      ← targets.py
   ├─ inject the target's decrypted credential (never returned)         ← crypto.py
   ├─ content-filter payload + response (secret/PII redaction)          ← policies.py
   ├─ call the backend (Anthropic / OpenAI / MCP / API / stub)          ← executor.py
   ├─ validate structured output against the target's schema
   ├─ audit (invoke / invoke-failed) + record usage units to the ledger ← ledger.py
   └─ optionally feed an experiment's control/treatment eval; fail over
```

Backends dispatch by kind/provider and connect by **API key or OAuth token**; a
missing credential falls back to a stub so a fresh install works offline.

## Governance stack

- **Roles** are admin-configurable data (seeded developer/platform/admin; rank
  drives every authorization check). — `users.py`
- **Policies** are authored governed harness artifacts: `rule` (allow/deny) plus
  `skill`/`command`/`agent`. A **strict** rule can't be overridden by a lower
  layer; strict precedence resolves along the layer graph (author role rank). A
  policy can scope to a **namespace** (per-namespace whitelists). — `policies.py`
- **Proactive enforcement** — an org mode of `audit` (default-allow) or `strict`
  (whitelist / default-deny), applied at the transition and invoke gates and at a
  **pre-action `/authorize`** seam a harness calls before a tool / command /
  host-egress action (verify identity + intent first). Every refusal is audited. —
  `policies.py`
- **Packs** are opt-in, role-gated starter bundles (standards + example
  processes) — the curated software / platform / team-workflow canon. — `packs.py`
- **Approval workflows** govern changes *to* governance: a change proposal walks
  an admin-configured (or auto-escalating) chain with accept / deny / feedback. —
  `approval_workflows.py`
- **Governance landscape + analysis** — what's defined where, what overrides
  what, and poison flags (dead / contradiction / redundant / prompt-injection). —
  `governance.py`, `analysis.py`
- **Repo coverage & debt audits** — per-repo `Claim`s on charter/harness/code
  surfaces (ingested via GitHub) drive coverage, imitation surfaces, drift, and
  0–100 health scores per area. — `repo_governance.py`, `ingest.py`, `debt.py`
- **Evals & experiments** — hypothesis → change → before/after evals →
  significance verdict. — `experiments.py`
- **Webhooks** fan HMAC-signed audit events to external endpoints. — `webhooks.py`
- **Rollbacks** revert a work item to a known-good prior stage (append-only
  `StageHistory`) and compute a structured **reverse plan** across the whole
  deployment (code, migrations, config, env, libraries, data, services, secret
  refs, infra, dns — an open category set); the harness applies it and reports
  apply-status back, all audited. — `rollback.py`
- **Teams, usage ledger & concurrency** — teams are the unit of cost attribution;
  a `LedgerEntry` per invoke meters units (the audit event digests them away), and
  a team's live in-flight cap is enforced at the invoke seam. — `teams.py`,
  `ledger.py`, `concurrency.py`
- **Traffic graph** — a cross-agent graph (actor→target, weighted by calls +
  units) derived from the ledger. — `ledger.py`

## Runtime infrastructure (in-process, single serve)

Same zero-dependency, single-process ethos throughout — each has a Redis/queue
swap point behind the same API for multi-process later:

- **Background jobs** — a thread-backed runner for long tasks (audits, ingest). — `jobs.py`
- **Scheduler** — a serve-path daemon that enqueues due per-repo ingests. — `scheduler.py`
- **Live channel** — an in-process pub/sub **hub** fans job status, new audit
  events, and per-run **live logs** to the `/ws` WebSocket. — `live.py`, `logs.py`

## Ports & adapters

New connectors are adapters behind an existing port; vendor detail never threads
through the core. Ports: integration `ADAPTERS` (source hosts, trackers),
executor `EXECUTORS` + `MODEL_BACKENDS`, OAuth `PROVIDERS`, `EmailSender`,
`AuditSink`, and the data store (SQLModel over SQLite; Postgres seam). Seams are
`typing.Protocol`s — swap implementations without touching the core.

## Data & config

- **SQLModel over SQLite.** Per-request `Session`; versioned migrations
  (`PRAGMA user_version` + append-only `MIGRATIONS`).
- **Only `SECRET_KEY` in the environment.** All other config (OAuth creds,
  email) lives in an encrypted `Setting` store, UI-editable by the right role.
- **Secrets encrypted at rest** (Fernet via `SECRET_KEY`); the API returns keys,
  never values.
- **Immutable records, append-only audit;** digests, not payloads, in events.

## Schema stability

**At 1.0.0 the schema is frozen.** Post-1.0 changes are **additive only** (new
tables / nullable columns via the migration runner) — no restructures. Pre-1.0
breaking churn is over.

## The library core

The original governed-production loop (`authorize → produce → record → audit →
log`) is still embeddable without the server:

```python
from open_refinery import Factory
factory = Factory()

@factory.recipe("upper")
def upper(text: str) -> str: return text.upper()

artifact, record = factory.produce("upper", actor="ian", text="hello")
```

Modules: `factory.py` (recipe registry + loop), `provenance.py` (immutable
`Record` + SHA-256 I/O digests), `authz.py` (`Authorizer`), `audit.py`
(`AuditSink`).
