# Limitations

What open-refinery does not do, stated plainly. Read it before adopting rather
than after — every item here is a deliberate boundary or a known gap, not a
surprise waiting in production.

---

## Scale and deployment

**SQLite only.** `store.engine_for` refuses any other `DATABASE_URL` outright
rather than half-working on one. That bounds a deployment to a single machine
with a single writer. It is the right shape for one organization's factory and
the wrong shape for a multi-tenant service.

**One process.** Workers are threads inside `serve`, not a separate queue.
There is no Redis and no Celery. A crash loses at most the stage in flight —
the `Run` row is the durable state and the next worker picks it up — but the
process is a single point of failure and horizontal scale-out is not available.

**No hot standby, no replication.** Back up the SQLite file. `open-refinery
migrate` moves the schema in either direction, and downgrading is destructive
by construction: dropping a column drops its data.

## The schema

**Frozen at 1.0, additive only.** Every 3.0 table is new; no existing column
changes type. That is a promise about upgrades, and the cost is that some
shapes are inherited rather than chosen. The clearest one: `Policy.layer` and
`ApprovalWorkflow.layer` are different ideas wearing the same name, and
renaming either would break the freeze.

## The harness

**`deepagents` is pre-1.0.** It is pinned `>=0.7,<0.8` and it carries pillar 2.
The mitigation is containment, not confidence: `pipeline/agent.py` is the only
module that imports it, so an upstream API change has a one-file blast radius.
That is a real dependency risk taken deliberately, with the cost measured.

**Sub-agents are off by default.** A phase may enable them, but the preferred
shape for parallelism is more workers running more runs, not one run split into
pieces that have to be reassembled. A run is the unit that maps to a worktree,
a branch and a pull request; splitting it loses that correspondence.

**`max_turns` is a ceiling, not a budget.** Nothing bounds what a run
spends. The quota mechanism that used to exist governed `POST /execute`, which
the factory never called, and went with it in 3.0; a per-run budget at the tool
seam is the replacement and is not built yet. Until it is, bound cost outside
the product — at the provider.

## The ladder

**The product carries rungs 0, 1, 3 and 4.** Rung 2 (a hook on the call) and
rung 5 (CI, after everybody has left) are named in the model and are somebody
else's to carry — rung 5 deliberately, because a check that runs after the
merge is the wrong place for anything this system can catch earlier.

**A predicate is code.** Rungs 2, 3 and 4 need one, and the four that ship
(`no-secrets`, `no-force-push`, `no-secrets-in-diff`,
`no-migration-without-downgrade`) are the ones the product knows how to
enforce. A rule outside that set stays at rung 0 until somebody writes the
predicate — which is the honest answer, because storing it at a rung nothing
enforces would make it *look* protected.

## Intake and delivery

**Four trackers parse webhooks**: GitHub Issues, GitLab Issues, Jira, Linear.
`trackers.TRACKERS` knows a fifth (Shortcut) for syncing, but nothing parses its
webhook shape yet — a delivery from it is refused rather than guessed at.

**The `local` forge writes a markdown file**, not a pull request. It exists so
the whole loop can be exercised without any accounts, and it is not a way to
ship to a real team.

**A repository must already be cloned.** `workspace.root_of` refuses a
`git_url` that is not a local checkout; the factory does not clone for you.

## Oversight

**`dark` is a real setting.** An organization can turn oversight off, and the
audit trail still records everything — but nothing will stop a run. That is the
org's decision to make, and the dial is where they make it.

**An agent cannot propose its own demotion.** It also cannot be stopped from
proposing a promotion, which means a sufficiently talkative lane can generate
work for its approvers. The evidence rule is the defence: a finding that cannot
be traced is dropped rather than reported.

## What is not verified here

**No live model call has been exercised in this repository's test suite.** The
suite runs against the offline stub, because a test that needs somebody's API
key is a test that does not run. Providers are exercised for *routing* — that
`anthropic/claude-sonnet-5` reaches the OpenRouter gateway rather than
Anthropic — not for generation.

**Nine providers are wired; not all nine have been called.** They share one
code path (`init_chat_model`) and differ in prefix and credential shape, which
is what `tests/test_ports.py` covers.

---

Deferred on purpose, and tracked in [PLAN-3.0.md](PLAN-3.0.md): areas
(`role × layer × area` grants, §2.5.1), passwordless email login codes (§2.4),
and plan previews (§10.2).
