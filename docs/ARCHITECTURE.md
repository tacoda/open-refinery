# Architecture

open-refinery is a self-hosted server that runs a **software factory**. Work
arrives as a ticket, goes through a stage graph, and comes out as a pull request
that a person merges. Everything it does on the way is authorized, owned,
filtered and audited.

Four things make up the product, and every module belongs to one of them:

| Pillar | What it is | Where |
|---|---|---|
| **1 · the factory** | the stage graph, the worktree, the forge, the delivery gate | `pipeline/` |
| **2 · the harness** | the coding agent that does a stage's work | `pipeline/agent.py`, `pipeline/phases.py` |
| **3 · the queue** | workers claiming runs and advancing them one stage at a time | `pipeline/workers.py` |
| **4 · the business** | audit, proposals, observation, evidence | `store.py`, `improve.py`, `approval_workflows.py` |

The orchestration is **deterministic plain code**. An agent does a stage's work;
it never decides what happens next.

---

## The run

A `Run` is the unit. One run, one worktree, one branch, one pull request.

```
POST /runs  ─→  Run row at the graph's first stage
                  │
        ┌─────────┴──────────  a worker ticks  ──────────────┐
        │                                                     │
   claim (conditional UPDATE)                          nothing actionable
        │
   advance ONE stage ────────────────────────────────┐
        │                                            │
   ┌────┴─────┐                                      │
 action    phase                                     │
 (plain    (the harness: a governed turn)            │
  code)         │                                    │
        │       └─ contract parsed → pass/refuse     │
        │                                            │
   apply_move  ──→  the pure machine decides where next
        │           (graph.advance: three dicts in, a Move out)
   release the claim ───────────────────────────────┘
```

The `Run` row **is** the durable state. Nothing is held in memory between ticks,
which is what makes resume free: a crash mid-stage leaves a *stale* claim that a
later worker takes over, where a lock file would just stay locked.

- `pipeline/spec.py` — the graph schema and the four templates
- `pipeline/graph.py` — the pure state machine. `advance`/`plan_next` are
  functions of three dicts, so the whole thing is testable with literals
- `pipeline/store.py` — versioned pipelines, runs, steps. `apply_move` is the
  only place a run's stage changes, which is why the live channel publishes from
  there
- `pipeline/runner.py` — one stage per call
- `pipeline/workers.py` — the claim, the tick, the concurrency cap
- `pipeline/workspace.py` — git worktrees; refuses a `git_url` that is not a
  checkout before creating anything
- `pipeline/forge.py` — GitHub · GitLab · Gitea · Bitbucket · `local`
- `pipeline/actions.py` — the delivery gate
- `pipeline/contracts.py` — `PROVEN:` / `VERDICT:` parsing. **Unparseable is
  never a pass**
- `pipeline/document.py` — the run document, which becomes the PR body

**Parallelism is runs, not turns.** Ten tickets go through at once because ten
runs are in flight, each a clean governed unit — not because one run was
shattered into pieces that have to be reassembled.

## The harness

`pipeline/agent.py` is the **only** module that imports `deepagents`. That is
deliberate containment: it is a pre-1.0 dependency carrying a pillar, so an
upstream API change has a one-file blast radius.

- `pipeline/phases.py` — seven phases (refine · plan · run · prove · review ·
  security · improve). A phase's **tool grant is rung 1**: what it is never
  given, it cannot misuse
- `pipeline/middleware.py` — `GovernanceMiddleware`, rung 3: sees each call
  before it happens and may hold it for a person
- the repo's **charter** (`.agents` / `AGENTS.md` by default, overridable)
  reaches the model as memory; enabled packs reach it as skills

## The ladder

A rule has a **rung**: the mechanism that carries it. "Money is Decimal" in a
markdown file is rung 0, and prose is a request. The same sentence as a
predicate that refuses the write is a guarantee.

| Rung | Carried by | Sees |
|---|---|---|
| 0 | prose in the charter | nothing. It asks |
| 1 | the tool grant | function ids, before any call |
| 2 | a hook on the call | the arguments *(not ours)* |
| 3 | a callback in the turn | the call; may hold it |
| 4 | the delivery gate | the finished diff |
| 5 | CI | the merged tree *(not ours — too late)* |

**A rung is a place, not a strictness.** Rung 3 sees a call and never a diff;
rung 4 sees a diff and never the call. Promotion and demotion are not
symmetric, and that asymmetry is the safety property: a promotion adds
enforcement and the factory may implement its own; a demotion removes it and
never runs unattended. — `ladder.py`

## Authorization

**Permissions live on the user.** A role is a preset — a starting point that is
copied and then edited — so changing a preset later changes nobody.

`approve:<layer>` · `propose:<layer>` · `run:factory` · `manage:users` ·
`read:audit` · `see:operations`, over layers `code` / `harness` / `factory` /
`charter`. `propose:*` is wide; `approve:*` is narrow. — `authority.py`

Every route carries an explicit `Depends(...)` guard. There is no path-matching
middleware: there was one, it disagreed with the per-route guards the moment
permissions moved, and two authorization systems that disagree are worse than
either alone.

## The governed call site

There is one, and it is inside a turn. Every tool a phase reaches for goes
through `Governed.check` before it runs:

```
the grant (rung 1, at build time) → the ladder (rung 3) → the content filter
  → the call → audit, subject-linked to the run
```

A refusal is handed back to the model as a tool result, not raised: an exception
ends the turn, and a refusal the model can read is one it can work around.
— `pipeline/middleware.py`, `ladder.py`, `policies.py`

**The spend ceiling is not here.** It cannot be: this seam sees a tool call,
and the cost of a turn is not known until the turn is over. `budgets.py` holds
it instead — `check_budget` before each stage, `charge` after — so a ceiling
refuses the *next* stage rather than the call that passed it. Inside one turn
the bound is `max_turns`, a turn cap rather than a cost one.

Two shapes, because there are two questions. `Repository.max_run_units` bounds
what **one** run may spend. A `Budget` is a shared counter over a rolling
window, at `org`, `team` or `repo` scope, and bounds what **everybody** spends.
A run's own spend is the sum of its steps' `units`, so there is one number and
it is the audited one.

Until 3.0 a *second* call site existed — `POST /execute`, resolving a `Route` to
a `Target`, consuming a `Quota` and metering a ledger. The factory never used
it: a run resolves its model from the phase and the actor's own credential. It
was deleted rather than wired up, because two governed call sites that disagree
are worse than either alone.

## Audit

Append-only, hash-chained, and **keyed**: each link is an HMAC under a subkey
derived from `SECRET_KEY`, so forging an event and recomputing the chain does not
produce a valid one. Purges write a signed `AuditCheckpoint`, so deleting the
oldest events is detectable rather than reading as a legitimate retention pass.
The chain head is authenticated, which catches a wholesale algorithm downgrade,
and an export is signed over every event rather than only the head.

`GET /audit/verify` recomputes it. An external auditor gets a time-boxed grant
rather than an account. — `store.py`, `provenance.py`, `auditors.py`

## Intake

Three doors, one destination:

- **webhook** — `POST /intake/{id}`, the one route with no bearer token, because
  the caller is a tracker rather than a person. The HMAC over the raw bytes is
  the credential
- **sync** — pull a tracker's issues on demand
- **by hand**

A ticket is **untrusted data**: it reaches a phase as a quoted spec, never as
instructions. — `intake.py`, `trackers.py`

## The improve lane

Reads the audit trail *and the run history* — contradictory rules, injection
text, denial spikes, stages that keep failing, revisions burned to no end, holds
nobody clears. Two rules carry it:

- **evidence or it is dropped** — a lane that always finds three things is one
  nobody believes by the third time
- **nothing is applied** — a finding becomes a proposal, and accepting one
  creates a *work item* that goes through the same graph as anything a person
  filed. The exception is a ladder move, which has no diff to produce

— `improve.py`, `approval_workflows.py`

## Ports and adapters

New connectors are adapters behind an existing port; vendor detail never threads
through the core. Seams are `typing.Protocol`s.

| Port | Adapters |
|---|---|
| `models_port.PROVIDERS` | anthropic · openai · google · mistral · deepseek · groq · openrouter · azure-openai · ollama |
| `pipeline/forge.FORGES` | github · gitlab · gitea · bitbucket · local |
| `trackers.TRACKERS` | github-issues · gitlab-issues · jira · linear · shortcut |
| `intake.PARSERS` | github-issues · gitlab-issues · jira · linear |
| `audit.AuditSink` | memory · jsonl · sqlite |
| `ladder.PREDICATES` | no-secrets · no-force-push · no-secrets-in-diff · no-migration-without-downgrade |

## Surfaces

The **web app** is the main surface (React + TypeScript + Vite + Tailwind +
shadcn/ui, `frontend/`), and the **CLI** is a peer rather than an afterthought —
`credentials`, `roles`, `pipelines`, `runs`, `phases`, `ladder` and `packs` all
drive the same API. Environment variables are for the server's lifecycle only.

The **canvas** is the workflow builder, and live mode is the same canvas with
runs standing on it. — `frontend/src/Canvas.tsx`, `live.py`

## Runtime

In-process, single `serve`, no Redis and no Celery:

- **workers** — threads advancing runs — `pipeline/workers.py`
- **jobs** — a thread-backed runner for long tasks — `jobs.py`
- **scheduler** — enqueues due per-repo ingests — `scheduler.py`
- **live channel** — in-process pub/sub to `/ws` — `live.py`, `logs.py`

## Data

SQLModel over **SQLite only** — `engine_for` refuses anything else rather than
half-working on it. Per-request `Session`; versioned migrations under
`PRAGMA user_version` with an append-only `MIGRATIONS` list and a reverse in
`DOWNGRADES` for each.

Secrets are encrypted at rest (Fernet via `SECRET_KEY`); the API returns key
*names*, never values. Events carry digests, not payloads.

**The schema is frozen at 1.0** — additive changes only. Every 3.0 table is new;
no existing column changes type.

## Reading further

- [ADOPTING.md](ADOPTING.md) — install to first pull request
- [LIMITATIONS.md](LIMITATIONS.md) — what this does not do
- [PLAN-3.0.md](PLAN-3.0.md) — the design record and why each decision went the
  way it did
- [FEATURES.md](FEATURES.md) — features by permission, journeys as diagrams
