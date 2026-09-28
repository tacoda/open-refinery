# The road to 3.0 — subtraction

2.25.0 shipped a feature-complete platform. What it also shipped was **two of
several things**: two governed call sites, two workflow engines, two
authorization models — and in each pair the older half was what the docs, the
dashboard and `doctor` still pointed at.

So the road to 3.0 is mostly deletion. Nothing on this list adds a feature the
product was missing; the list exists because a complete feature set that nobody
can find is not complete.

*The build plan is [PLAN-3.0.md](PLAN-3.0.md) — where the product was going.
This is the cleanup that follows it.*

---

## Status

| | Step | State |
|---|---|---|
| 1 | Delete the second execution path (`/execute`, targets, routes, quotas, ledger); fix `doctor` | **done** |
| 2 | Fold `Process` into `Pipeline`; a work item's stage is derived from its runs | **done** |
| 3 | Put metering and a spend ceiling back on the run | **done** |
| 4 | Scope the content filter to egress | **done** |
| 5 | Rebuild Overview and Metrics on `Run` / `RunStep` | **done** |
| 6 | Give the ladder a UI; collapse the three rules surfaces into it | **done** |
| 7 | Collapse the navigation to ~8 views | **done** — nine, flat |
| 8 | One authorization model — policies key off permissions, not `role_rank` | **done** |
| 9 | Publish the feature list and the domain glossary | **done** |

---

## What each step is for

**1 · the second execution path.** `POST /execute` resolved a `Route` to a
`Target`, consumed a `Quota` and metered a ledger. The factory never called it:
a run resolves its model from the phase and the actor's own credential. Two
governed call sites that disagree are worse than either alone.

**2 · the second workflow engine.** A `Process` was a stage graph with
transitions, gates, checks and an approval chain that a run completely ignored.
The only field of it a run ever read was `oversight`, which now lives on the
repository.

**3 · the ceiling that was documented and never enforced.**
`pipeline/middleware.py` listed quota as check #4 from the day it was written.
`Result.units` and `RunStep.units` both existed and neither was ever populated.

**4 · the filter that refused ordinary work.** One pattern list over every tool
call meant a `git commit --author`, a CODEOWNERS file or any thirteen-digit
literal was refused as a secret.

**5 · metrics about the factory.** `metrics.py` aggregated the kanban. There is
no throughput, no landed/closed/failed ratio, no lead time, no revision rate —
all of it derivable from `Run` and `RunStep` today. The Overview counts events
that no longer exist.

**6 · the ladder has no UI.** It is the sharpest idea in the product — rung 0
prose versus rung 4 predicate — and the dashboard never mentions it. *Standards*,
*Policies* and *My rules* are three surfaces for "the rules"; the ladder is the
one that should absorb them.

**7 · twenty views is not a simple interaction.** *Workflows* competes with
*Processes*; *Work* with *Runs*; *Overview* with *Metrics* with *Spend*. Eight
views cover everything the product does.

**8 · the second authorization model.** `authority.py` puts permissions on the
person and the docs say role rank is ordering only — but `policies.enforce`
matches a stale `role` string and resolves precedence with `role_rank`.

**9 · say what it is.** [FEATURES.md](FEATURES.md) §0 is the feature list;
[GLOSSARY.md](GLOSSARY.md) is the vocabulary, each term defined once. Writing
them down is also an audit: it found `POST /audits/run` answering **500** to
every request — it called a `run_audit` that exists nowhere, and no test covered
it — plus five tables no code reads (`audits`, `claims`, `recert_campaigns`,
`recert_items`, `invitations`). A feature list that includes a 500 is not a
feature list, so they went.
