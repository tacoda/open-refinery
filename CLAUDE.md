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

## Commands

```bash
uv sync --extra dev
uv run pytest
uv run open-refinery --actor ian --text hello
```

## Roadmap (don't build ahead of need)

Governance policy layer, observability read-model, pluggable sinks, async
recipes. See `docs/ARCHITECTURE.md`.
