# Contributing to open-refinery

Thanks for your interest. This is an early-stage project; the core is small on
purpose.

## Setup

```bash
uv sync --extra dev
uv run pytest
```

## Principles

- **Manage complexity ruthlessly.** The minimum code that solves the problem.
  No speculative abstractions, no configurability that wasn't asked for.
- **Test non-trivial logic.** New behavior lands with a test. Prove a bug with
  a failing test before fixing it.
- **Surgical changes.** Touch only what the change requires; match existing
  style.
- **Keep the core dependency-free** where the standard library suffices.

## Workflow

1. Branch from `main`.
2. Make the change with tests.
3. `uv run pytest` — all green.
4. Open a PR against `main` with a clear description of the *why*.

## Commit style

Conventional Commits (`feat:`, `fix:`, `docs:`, `refactor:`, `test:`). Subject
in the imperative, ≤50 chars; body only when the *why* isn't obvious.

## Scope

Discuss larger changes (new pillars, dependencies, policy engine) in an issue
first — see the roadmap in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
