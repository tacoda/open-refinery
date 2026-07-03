# CLAUDE.md — open-refinery

*Manage complexity ruthlessly. The minimum code that solves the problem.*

## What this is

A factory that produces artifacts under governance. The production loop is:
**authorize → run recipe → record provenance + ownership → audit → log**.
Core pillars: observability, auditability, authorization, ownership,
provenance, logging — and, on the roadmap, **governance via policies**.

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
