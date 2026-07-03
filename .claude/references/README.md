# Design references

Design lineage and principles for open-refinery. Read these when making
architectural decisions — they explain *why* the system is shaped the way it is.
Each note summarizes an external source's principle and how it applies here;
follow the links for the originals.

- [harness-vs-platform.md](harness-vs-platform.md) — the scope boundary: what
  the platform owns vs what the harness owns.
- [deterministic-queue.md](deterministic-queue.md) — the orchestrator is a queue
  (plain code), not an agent.
- [no-sub-agents.md](no-sub-agents.md) — decomposition lives in deterministic
  orchestration, not agent-spawned sub-agents.
- [ports-and-adapters.md](ports-and-adapters.md) — hexagonal architecture for the
  many connectors (integrations, targets, executors, OAuth providers).

## App shape (load-bearing)

The **main user interface is the web dashboard** (React + TypeScript + Vite +
Tailwind + shadcn/ui). It consumes the **FastAPI backend** over HTTP. The
backend is the source of truth and the governance boundary; the dashboard is a
client. Everything a user does is possible through the dashboard, and everything
the dashboard does goes through the API — no privileged side channels.
