# CLAUDE.md — open-refinery

*Manage complexity ruthlessly. The minimum code that solves the problem.*

## What this is

A self-hosted **platform layer** that governs AI-driven software work: work
ships through customizable processes, and every step is authorized, owned,
provenanced, quota'd, content-filtered, and audited. The governed loop is
**authorize → (quota / secrets / filter) → act → record → audit**.

## Architecture (load-bearing)

- **The web dashboard is the main user interface** — React + TypeScript + Vite +
  Tailwind + shadcn/ui (`frontend/`). It consumes the **FastAPI backend** over
  HTTP. Everything a user does goes through the API; the dashboard is a client,
  the backend is the governance boundary and source of truth.
- **Ports and adapters** for the many connectors — integrations
  (`ADAPTERS`), executor backends (`EXECUTORS`), OAuth providers (`PROVIDERS`),
  audit sinks (`AuditSink`), the data store. New connectors are adapters behind
  an existing port; don't thread vendor detail through the core. See
  `.claude/references/ports-and-adapters.md`.
- **Deterministic orchestration** — the transition loop / executor pipeline is
  plain code (a queue), not an agent. See `.claude/references/`.

## Design lineage

Read `.claude/references/` before architectural decisions — harness-vs-platform
(the scope boundary), the deterministic queue, no-sub-agents, and ports &
adapters. They explain *why* the system is shaped this way.

## API docs & type parity

- FastAPI auto-generates OpenAPI; self-hosted Swagger UI is served at
  **`/api-docs`** (assets bundled at build, no CDN).
- `make types` regenerates `frontend/src/api-types.ts` from the OpenAPI schema
  (`openapi-typescript`) so the frontend types match the backend — run it (or
  `make ui`, which includes it) after changing API request/response shapes.

## Layout

- `src/open_refinery/` — src layout, `hatchling` build, `uv` for env/deps.
  - `factory.py` — recipe registry + production loop
  - `provenance.py` — immutable `Record` + I/O digests
  - `authz.py` — `Authorizer` protocol (`AllowAll`, `AllowList`)
  - `audit.py` — `AuditSink` protocol (`MemorySink`, `JsonlSink`)
  - `cli.py` — demo entry point (`open-refinery`)
- `tests/` — pytest
- `docs/ARCHITECTURE.md` — the loop, modules, roadmap

## Working rules

- **Keep the core dependency-free** while the stdlib suffices. A new dependency
  needs a reason.
- **Protocols over inheritance** for the seams (`Authorizer`, `AuditSink`).
- **Immutable records, append-only audit.** Never mutate a `Record`.
- **Every schema change ships a migration.** Any DB change (a model column, a new
  index) must land with the matching entry in `migrations.MIGRATIONS` so existing
  installs upgrade — new tables are handled by `create_all`; columns need an
  `ALTER`, ALTER-added indexed columns need a `CREATE INDEX IF NOT EXISTS`.
  Append-only; schema frozen at 1.0 (additive changes only). Migrations run
  automatically on `serve`, or explicitly via `open-refinery migrate` (`--to N`
  to pin a version, up or down). Append a reverse to `DOWNGRADES` alongside every
  `MIGRATIONS` entry so downgrades stay possible.
- **Test non-trivial logic.** Prove a bug with a failing test first.
- **Surgical changes.** Touch only what the task needs; match existing style.
- Order in `produce` is load-bearing: authorize before running; record/log only
  after a successful run.

## Design & philosophy sources

- **Harness engineering vs platform engineering** — a mental model for how both
  win: <https://traefik.io/blog/harness-engineering-vs-platform-engineering-a-mental-model-for-how-both-win>
  open-refinery *is* the **platform** (out-of-process governance: identity,
  audit, routing, quotas, oversight) that harnesses (in-process, app-owned:
  orchestration, prompt, tools, memory) call through to reach targets. Keep the
  boundary crisp — the platform governs; it does not do the harness's job.

## Commands (dev only — end users `pip install` + `open-refinery serve`)

```bash
make install     # uv sync --extra dev
make test        # pytest
make dev         # run server: fixed SECRET_KEY + local devtest.db on :8000
make seed        # sample data + login tokens
make ui          # build the dashboard into the package
```

See `.claude/rules/dev-workflow.md` — always use make for dev; restart `make dev`
after backend changes.

## Roadmap (don't build ahead of need)

See `PLAN.md`. Next: more integration providers, targets + routing + quotas,
policy governance.
