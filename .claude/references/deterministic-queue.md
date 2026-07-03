# The orchestrator is a queue, not an agent

Source: Mike Piccolo — *Loop Engineering: it's just software, we should have a
name*
<https://www.linkedin.com/pulse/loop-engineering-just-software-we-have-name-mike-piccolo-yb73c/>

## Principle

The loop that sequences work should be **deterministic code** — a queue, plain
Python — not an LLM deciding what happens next. The model's judgment belongs
*inside* a step; moving between steps is software.

Why it matters:

- **Cost** — advancing a step costs nothing (no model call to orchestrate).
- **Determinism** — sequencing is reproducible and testable.
- **Auditability** — every state change is a plain, attributable record.

## Brooks corollary

Keeping the loop deterministic keeps work items **partitionable**. Per Fred
Brooks (*The Mythical Man-Month*), work that can be partitioned *without
intercommunication* is the kind where adding effort adds throughput; work
requiring communication incurs overhead that grows with the number of workers. A
central orchestrating agent would be exactly such a communication bottleneck; a
queue is not.

## How open-refinery applies it

The transition loop over the durable store *is* the orchestrator. `transition()`
and the executor pipeline are deterministic functions; the LLM is confined to
work performed within a step (via the executor's target calls). Independent work
items advance through the queue without talking to a central agent. Do not
introduce an agent that decides sequencing — that would forfeit cost,
determinism, and partitionability.
