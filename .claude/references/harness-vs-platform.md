# Harness vs Platform

Source: Traefik Labs — *Harness engineering vs platform engineering: a mental
model for how both win*
<https://traefik.io/blog/harness-engineering-vs-platform-engineering-a-mental-model-for-how-both-win>

## Principle

Two layers, cleanly separated:

- **Harness** — in-process, app-owned, task-specific. The agent/app's own loop:
  orchestration, prompt context, tool selection, memory, self-verification.
- **Platform** — out-of-process, fleet-wide. Governance every harness inherits
  by calling *through* it: identity, authorization, secrets, quotas, routing,
  content filtering, audit.

Between them sit **targets**: models, MCP servers, backend APIs.

## How open-refinery applies it

open-refinery **is the platform**. It governs *how work reaches targets*; it
does not do the harness's job. This is the scope boundary — keep it crisp.

### Platform owns (open-refinery's job)

| Concern | Reasoning |
|---|---|
| Identity of the calling actor | Consistent across harnesses; required for audit |
| Authorization to invoke a tool/target | Role-based; enforced across agents; not self-asserted |
| Secrets injection into calls | Secrets must not enter harness process memory |
| Rate limits & concurrency caps | Multi-tenant fairness, provider quotas |
| Per-policy routing (cost, region, compliance) | Enterprise policy, not per-task |
| Failover when a provider degrades | Transparent to the harness; consistent SLOs |
| Content filtering & DLP on prompts/responses | Regulatory / data-protection consistency |
| Audit trail of every model & tool call | Single source of truth for compliance |
| Traffic-graph observability & correlation | Cross-agent, cross-tenant visibility |
| Cost attribution by team/product | Enforced at the call site, not self-reported |

### Harness owns (NOT open-refinery — non-goals)

| Concern | Reasoning |
|---|---|
| Tool selection for a task | Task-specific; depends on prompt + intermediate state |
| Per-task model selection | Depends on sub-task semantics |
| Sub-agent delegation logic | Internal to one agent's planning |
| Context-window compression | Intra-loop performance optimization |
| Self-verification of model output | Task correctness within a single agent |
| Eval & tracing of agent reasoning | Reasoning is internal; harness-native |
| Session persistence & checkpointing | Internal to the agent lifecycle |

When unsure whether a feature belongs here: if it's task-specific and lives
inside one agent's loop, it's the harness's. If it must be consistent and
auditable across all agents, it's the platform's — ours.
