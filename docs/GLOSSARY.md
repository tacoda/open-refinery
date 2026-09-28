# Glossary

Every term open-refinery uses, defined once. Read this before the code: the
words are load-bearing, and four of them look alike and are not.

*Companion to [FEATURES.md](FEATURES.md) — that one says what exists, this one
says what the words mean.*

---

## The four that read alike

This is the distinction most worth having straight, because all four are
ordered sequences of things with names, and they are four different ideas.

| Term | What it is | Where |
|---|---|---|
| **stage** | a node in a pipeline's graph — `plan`, `run`, `prove`. A run sits at exactly one at a time. | `pipeline/spec.py` |
| **step** | one recorded *attempt* at a stage. A stage refused twice is one stage and three steps. Append-only; a step is a fact, not a status. | `RunStep` |
| **phase** | the harness configuration a stage may invoke — a prompt, a model, a turn cap, a tool grant. `plan` the stage runs `plan` the phase; a stage that runs an *action* has no phase. | `pipeline/phases.py` |
| **rung** | where a rule is *carried* — prose, a tool grant, a hook, a callback, the delivery gate, CI. Not a stage in anything; a place a rule lives. | `ladder.py` |

A **stage** does one of two things: run a **phase** (a governed model turn) or
perform an **action** (plain code — claim a worktree, open a pull request).
Either way it produces a **step**.

---

## The work

**work item** — a ticket. A title, a repository, an owner, and optionally the
tracker reference it came in as. It has **no state machine of its own**: its
stage is *derived* from its runs. Until 3.0 it sat on a `Process`, a second
stage graph that a run ignored.

**stage (of a work item)** — one of `open` · `running` · `waiting` · `landed` ·
`closed` · `failed`, read off the newest run. An outcome beats a stage; the
newest run wins. Not to be confused with a pipeline stage.

**run** — one journey of one work item through one pipeline. **The unit of the
whole system**: one run, one worktree, one branch, one pull request. The `Run`
row *is* the durable state, which is what makes resume free.

**pipeline** — the stage graph a run follows, versioned. A run pins the version
it started under, so editing a pipeline cannot reach work already in flight.
Four templates ship: `ship-a-ticket` · `quick-fix` · `docs-only` · `strict`.

**action** — a stage implemented in plain code: `prepare_workspace` ·
`commit_and_push` · `open_pull_request` · `watch_pull_request` · `teardown`.

**worktree** — the git worktree a run works in, rooted so a turn cannot write
outside it. Claimed at `prepare_workspace`, released at `teardown`.

**intake** — how a ticket arrives: a tracker **webhook** (HMAC-signed), a
**sync** (pull the tracker's issues), or by hand. It behaves the same however
it arrived.

**autostart** — whether an arriving ticket starts a run by itself.

---

## The governance

**permission** — what a person may actually do. Twelve of them:
`approve:<layer>` · `propose:<layer>` over four layers, plus `run:factory`,
`manage:users`, `read:audit`, `see:operations`. **Permissions live on the
person.** This is the authorization model; there is no other.

**layer** — what a change is *about*: `code` · `harness` · `factory` ·
`charter`. Almost every gate keys off one. *(Beware: `Policy.layer` is a
different axis — see below.)*

**role / preset** — a named bundle of permissions, **copied onto a person at
creation and never read again**. A starting point, not an identity. Changing a
preset later changes nobody. Role *rank* is ordering — who signs after whom in
a proposal chain — and **not authority**; nothing that gates an action reads it.

**rule** *(on the ladder)* — one sentence somebody wants obeyed, plus the
**rung** that carries it. Rung 0 is prose and asks; rung 4 is a predicate over
the finished diff and refuses. A rung is a **place, not a strictness**: rung 3
sees a call and never a diff, rung 4 sees a diff and never the call.

**constraint / capability** — the two sides of the ladder. A constraint
*withholds* a function; a capability *grants* one. They meet at rung 1, which is
why the net tool grant is the one number both sides produce.

**predicate** — the code that makes a rule mechanical, required at rungs 2–4.
Four ship: `no-secrets` · `no-force-push` · `no-secrets-in-diff` ·
`no-migration-without-downgrade`. A rule outside that set stays at rung 0, which
is the honest answer.

**promotion / demotion** — moving a rule up or down the ladder. **Not
symmetric, and that asymmetry is the safety property.** A promotion adds
enforcement and the factory may implement its own. A demotion removes it: it
needs a second signer and the factory never performs one.

**policy** — a role-free allow/deny artifact evaluated by `policies.enforce`:
`(effect, applies_to, action, resource)`. **A different mechanism from the
ladder** — a policy gates an *action name*, a rung carries a rule at a *place*.

**`applies_to`** — who a policy gates: `*` for anyone, or a **permission** the
actor holds. Never a role name.

**`Policy.layer`** — `factory` > `harness` > `charter`, the precedence axis for
strict policies. **A different idea from the change layer above**, wearing the
same word; renaming either would break the schema freeze.

**strict (policy)** — a rule that locks the decision at its layer, so a lower
layer cannot override it.

**enforcement mode** — org-wide: `audit` (default-allow, opt-in deny) or
`strict` (whitelist / default-deny).

**pack** — a bundle of **standards** and governed artifacts, enabled as a unit.
Enabling one is a charter change, so `approve:charter` signs it.

**standard** — a unit of written guidance seeded by a pack. Prose — rung 0 by
construction.

**charter** — what a repository says about how work is done there
(`.agents/`, `AGENTS.md`, overridable per repo). It reaches a turn as memory.

**proposal** — a proposed governance change walking an approval chain. Anyone
may propose; only the layer's owner signs. `propose:*` is deliberately wide and
`approve:*` deliberately narrow.

**approval workflow** — the ordered chain of signers for a governance change,
one per layer, with a distinct signer per slot.

---

## The harness

**harness** — the in-process, app-owned side: orchestration, prompt, tools,
memory. open-refinery is the **platform** it calls through to. Also, concretely:
an **agent** registered here that acts through the API.

**turn** — one governed model invocation with a tool grant, a filesystem rooted
at the worktree, and governance on every call.

**tool grant** — the functions a phase is given. Rung 1: what it was never
given, it cannot misuse.

**oversight** — the human-in-the-loop dial on a **repository**:
`manual` · `assisted` · `supervised` · `autonomous` · `dark`. It becomes the set
of tool calls the harness interrupts on. **`ask` never becomes `allow`** — at
`autonomous` and `dark` it degrades to *refuse*, because an unattended factory
reading `ask` as yes has answered a question nobody put.

**hold** — a run stopped at a gate, waiting for a person. Cleared by
`POST /runs/{id}/approve`, which needs `approve:code` and refuses your own run.

**contract** — the shape a phase's answer must take (`PROVEN:` / `VERDICT:`).
**Unparseable is never a pass.**

**delivery gate** — rung 4: the predicate over the finished diff, before the
commit.

---

## The record

### Three things called "audit"

The word does three jobs here. Keeping them apart is the difference between
"who may read the record" and "who may destroy it".

| Term | What it is | Who |
|---|---|---|
| **the audit trail** | the hash-chained record of what happened — `Event` rows, `audit.py` | read with `read:audit` |
| **an auditor grant** | a time-boxed read-only credential for somebody with no account | minted with `manage:users`, reads with `read:audit` |
| ~~a debt audit~~ | a health score over an area — **gone in 2.15.0**, replaced by the **improve lane** | — |

**Reading the record and administering it are different permissions.**
`read:audit` reads; retention (`POST /audit/purge`) and minting a grant are
`manage:users`. Filing them under `read:audit` gave a read-only external auditor
the power to purge the trail and to issue itself a fresh grant.

**event** — one entry in the audit trail. Hash-chained and **keyed**: each link
is an HMAC under a subkey of `SECRET_KEY`, so forging one and recomputing the
chain does not work without the key.

**recipe** — an event's kind: `run-started` · `run-stage` · `run-held` ·
`pr-opened` · `tool-call` · `tool-refused` · `denied` · `redacted` ·
`budget-exceeded` · `approval` · `ladder-added`, and others.

**subject** — what an event is *about* — usually a run or a work item. A run's
whole tool history is one query on it.

**checkpoint** — a signed explanation for a gap in the chain, written when
events are purged. A gap without one is tampering.

**auditor grant** — a time-boxed, read-only token for an external auditor with
no account. It reads the trail and the evidence packs and mutates nothing.
Minting and revoking one is `manage:users`.

**evidence pack** — the trail mapped onto a compliance framework
(`soc2` · `iso27001` · `hipaa` · `gdpr`), control by control.

**improve lane** — one read over the record looking for what went wrong.
**Evidence or it is dropped**: every finding names the events it came from, and
one that cannot be traced is discarded rather than repaired. Nothing is applied
— a finding becomes a proposal.

---

## Cost and capacity

**unit** — what a turn cost, as the provider reported it (`usage_metadata`,
total tokens). **Units are tokens, not money** — the product does not know
anybody's rate card. A provider that reports nothing meters zero.

**budget** — a shared spend ceiling over a rolling window, at `org`, `team` or
`repo` scope. Bounds what *everybody* spends.

**`max_run_units`** — a repository's ceiling on what **one** run may spend.
Checked *between* stages, so a stage already under way runs to its end.

**team** — a group of users. The unit of the concurrency cap and of team-scoped
budgets.

**concurrency cap** — how many runs a team may have in flight at once.

---

## The ports

Every connector is an adapter behind one of these. Adding one is an entry, not a
branch.

| Port | Adapters |
|---|---|
| `models_port.PROVIDERS` | anthropic · openai · google · mistral · deepseek · groq · openrouter · azure-openai · ollama |
| `pipeline/forge.FORGES` | github · gitlab · gitea · bitbucket · local |
| `trackers.TRACKERS` | github-issues · gitlab-issues · jira · linear · shortcut |
| `intake.PARSERS` | github-issues · gitlab-issues · jira · linear |
| `ladder.PREDICATES` | no-secrets · no-force-push · no-secrets-in-diff · no-migration-without-downgrade |
| `audit.AuditSink` | memory · jsonl · sqlite |

**forge** — where code goes to be reviewed. `local` writes a markdown file so
the whole loop runs with no accounts; it is not a way to ship to a real team.

**tracker** — where tickets come from. Five sync; four parse a webhook.

**integration / credential** — one person's key for one service. Personal: a
secret is never returned to anyone at any permission.

---

## Words we do not use any more

Kept here so a stale reference is recognisable rather than mysterious.

| Gone | Was | Now |
|---|---|---|
| **process** | a second stage graph with transitions, gates and checks | **pipeline** — a run ignored the other one |
| **target / route** | where a governed call was sent | a phase names a model; the actor's credential reaches it |
| **quota** | a windowed cap on a target | **budget** (shared) and `max_run_units` (per run) |
| **attestation** | a recorded claim that a check passed, gating a transition | the ladder's predicates, at a rung |
| **transition** | moving a work item between kanban columns | a run advancing a stage |
| **rollback** | reverting a work item to a prior stage | `git revert` and another run |
| **`Policy.role`** | the role a policy gated | **`applies_to`** — a permission |
