# You don't need sub-agents

Source: Anton Vinogradov — *You don't need sub-agents*
<https://www.linkedin.com/pulse/you-dont-need-sub-agents-anton-vinogradov-q7tef>
(LinkedIn; login-walled — this note is self-contained.)

## Principle

Reaching for agent-spawned **sub-agents** to decompose a task is usually the
wrong tool. Decomposition and sequencing belong in **deterministic
orchestration** (plain code / a queue), not in an LLM spawning and coordinating
child agents. Sub-agent delegation is opaque, non-deterministic, expensive, and
hard to audit; explicit steps are none of those.

## How open-refinery applies it

Decomposition is expressed as a **process** (ordered steps with transitions),
run by the deterministic transition loop — not by an orchestrating agent that
spawns sub-agents. This is consistent with two other references here:

- Sub-agent delegation is a **harness** concern (see harness-vs-platform.md) —
  explicitly a non-goal for the platform.
- The orchestrator is a **queue, not an agent** (see deterministic-queue.md).

So: do not add sub-agent orchestration to open-refinery. If work needs breaking
down, model it as steps in a process. An agent's judgment stays inside a single
step's execution.
