# open-refinery

*An open factory to shine light into the dark.*

**open-refinery is a self-hosted control plane for AI-driven software work.**
Teams define the *processes* their work moves through — a kanban board, a
vulnerability-remediation doctrine, whatever fits — connect their repositories,
and ship work through those processes. Every step is owned, authorized,
recorded, and queryable. It runs "dark" (lights-out automation) but stays
"open": nothing happens without an attributable, auditable trail.

### What it is

The **platform layer** between your harnesses (agents, scripts, CI — the
in-process, app-owned side) and your targets (repos, models, tools). It governs
*how work reaches those targets*: identity and roles, authorization, provenance,
an append-only audit trail, oversight gates, and metrics. Install it on any VPS
with `pip install` and one command; manage everything from the web dashboard.

### What it does

- Ships work through **customizable processes** — ordered steps with feedback
  loops (board or doctrine archetypes).
- Puts a **human-oversight dial** on every process (L0 manual → L4 fully dark),
  with approvals and quality-gate attestations where you want them.
- Records a **complete, attributed audit trail** — who did what, to which work
  item, with what inputs — and derives **metrics** (WIP, lead time, throughput)
  from it.
- Enforces **ownership**: developers see their own work; platform sets org-wide
  standards; admins audit everything.

### What it doesn't do

- It is **not** a CI runner, a build system, or an agent framework — it
  *governs* work, it doesn't execute your builds or own your prompts.
- It is **not** multi-tenant SaaS. One install serves **one organization**,
  self-hosted and single-tenant by design.
- It doesn't hide anything: no opaque automation, no un-owned actions.

### Philosophy & goals

Automation you can't audit isn't trustworthy. open-refinery's goal is to make
lights-out software work **safe to trust** by making it *legible* — every
production authorized, owned, provenanced, and logged, with human oversight
configurable to each team's philosophy. Minimal to run (one process, SQLite,
env-light), everything managed through the UI, and completely open source.

**The orchestrator is a queue, not an agent.** Work advances through processes
via deterministic code (the transition loop over a durable store), not an LLM
deciding what happens next. That determinism is the point: it's cheap (no model
call to move a step), reproducible, and auditable — the agent's judgment is
confined to the work *inside* a step, while sequencing stays plain software.
It also keeps work items **partitionable**: independent items advance through
the queue without intercommunication, which — per Brooks in *The Mythical
Man-Month* — is the condition under which adding effort actually adds
throughput, whereas work requiring communication incurs overhead that a central
agent bottleneck would impose.

> Status: **0.13.0.** **Roles are admin-configurable** — a seeded
> developer/platform/admin ladder that admins extend and re-rank via the UI
> (`/roles`); rank comparisons, invitations, and approval chains resolve against
> it. **Packs** — opt-in, role-gated starter bundles of guidance (enable via the
> CLI or the Packs tab); the base install seeds almost nothing. **Policies are
> authored harness artifacts** (rule / skill / command / agent) with a **strict**
> override lock (default an admin setting). Configuration lives in the
> **database, not the env** — OAuth provider creds
> are UI-managed (platform/admin) and encrypted at rest, so **only `SECRET_KEY`
> is required in the environment**. Atop role-gated invitations, structured
> output, the async approval queue + chained approvals, the configurable risk
> profile, the executor, policy governance, targets / routing / quotas,
> integrations, oversight, metrics, and a full audit trail.
> Self-hosted API docs at `/api-docs`. See [CHANGELOG.md](https://github.com/tacoda/open-refinery/blob/main/CHANGELOG.md).

## Quickstart

Requires **Python 3.11+**. SQLite ships with Python — there is no separate
database to install.

```bash
pip install open-refinery        # or: uv pip install open-refinery
open-refinery serve              # server + dashboard on port 8000
```

Open `http://your-host:8000` — on a fresh instance the **dashboard** walks you
through creating the first admin (no CLI needed), then signs you in. From there,
manage repos, processes, work, oversight, and the audit trail. The UI (React +
shadcn/ui, light/dark/auto themes) is bundled in the package — no Node to run.

Prefer the CLI to seed the admin? `open-refinery create-admin --email you@x.dev`
still works.

Background it on a VPS however you like — `&`, `nohup`, `screen`, `tmux`, or
your process manager:

```bash
open-refinery serve --port 9000 &                # or: PORT=9000 open-refinery serve
curl localhost:9000/health                       # {"status": "ok"}
```

### Using the API

Authenticate every request with the admin token from `create-admin`:

```bash
TOKEN=<paste the token>
H="Authorization: Bearer $TOKEN"

# register a repository (a repo = a project, whatever the code architecture)
curl -s -H "$H" localhost:9000/repositories \
  -d '{"name":"my-app","git_url":"git@github.com:me/my-app.git"}'

# define a process: steps + oversight (dark = lights-out; assisted needs approval)
curl -s -H "$H" localhost:9000/processes \
  -d '{"name":"remediate","archetype":"doctrine",
       "stages":["detect","triage","patch","verify","close"],
       "transitions":[["detect","triage"],["triage","patch"],["patch","verify"],
                      ["verify","close"],["verify","patch"]],
       "oversight":"supervised","gates":["close"]}'

# ship work through it, then move it a step (approve=true when a gate needs sign-off)
curl -s -H "$H" localhost:9000/work-items \
  -d '{"repo_id":"<repo>","process_id":"<proc>","title":"CVE-1234"}'
curl -s -H "$H" localhost:9000/work-items/<item>/transition -d '{"to":"triage"}'

# read the audit trail — every move, owned and attributed
curl -s -H "$H" "localhost:9000/events?subject=<item>"
```

Config is env-only, all optional: `PORT` (or `--port`), `DATABASE_URL`
(`sqlite:///open-refinery.db` default), `LOG_LEVEL`.

### Sign in with GitHub (optional)

Set these and the dashboard shows a "Sign in with GitHub" button:

```bash
export GITHUB_CLIENT_ID=...       # from your GitHub OAuth App
export GITHUB_CLIENT_SECRET=...
export APP_BASE_URL=https://or.example.com   # optional; used to build the callback
```

Register the OAuth App's callback as `<APP_BASE_URL>/auth/github/callback`.
A GitHub login is accepted only when its **verified primary email matches an
existing user** — provision accounts first (an admin creates them in the UI);
unknown emails are denied. (Roadmap: OAuth client id/secret move to DB settings,
editable in the UI by platform/admin — so **only `SECRET_KEY` is required in the
environment**; everything else lives in the database.) API/CI accounts keep
using tokens.

## Library

open-refinery is also an embeddable core — the same governed-production loop
without the server:

```python
from open_refinery import Factory

factory = Factory()

@factory.recipe("upper")
def upper(text: str) -> str:
    return text.upper()

artifact, record = factory.produce("upper", actor="ian", text="hello")
```

`open-refinery demo` prints one such record.

## Pillars

| Pillar          | Where it lives                                              |
|-----------------|-------------------------------------------------------------|
| Authorization   | `Authorizer` (`AllowAll`, `AllowList`) — checked before produce |
| Provenance      | `Record` — recipe, actor, timestamp, input/output digests   |
| Ownership       | `owner` on every record (defaults to the actor)             |
| Auditability    | `AuditSink` (`MemorySink`, `JsonlSink`) — append-only trail  |
| Logging         | stdlib `logging`, logger name `open_refinery`               |
| Oversight       | Per-process autonomy levels L0–L4; gated steps need recorded approvals |
| Observability   | `GET /metrics` — WIP, event counts, per-actor activity, lead times over the audit trail |
| Governance      | *(roadmap)* policy layer that constrains what may be produced |

## Durable audit trail

```python
from open_refinery import Factory, JsonlSink

factory = Factory(audit=JsonlSink("audit.jsonl"))
```

Each production appends one JSON line — a replayable record of who produced
what, from which inputs, and when.

## Development

```bash
make install            # backend: uv sync --extra dev
make test               # uv run pytest
make serve              # run the server locally
make help               # list all tasks

open-refinery seed      # optional: load EXAMPLE data + login tokens (never auto-run)
```

Frontend (dashboard) lives in `frontend/` — React + TypeScript + Vite + Tailwind
+ shadcn/ui, built with [bun](https://bun.sh):

```bash
make ui-dev             # Vite dev server (proxies API to :8000)
make ui                 # build the SPA into the package
make dist               # build UI + wheel (the wheel bundles the SPA)
```

The build step is release-time only; end users never need bun/node.

For a full fresh-VPS walkthrough — install, background the server, create the
admin, ports, and HTTPS/TLS on a public host — see [USER_GUIDE.md](https://github.com/tacoda/open-refinery/blob/main/USER_GUIDE.md).

See also [PLAN.md](https://github.com/tacoda/open-refinery/blob/main/PLAN.md), [CONTRIBUTING.md](https://github.com/tacoda/open-refinery/blob/main/CONTRIBUTING.md), and
[docs/ARCHITECTURE.md](https://github.com/tacoda/open-refinery/blob/main/docs/ARCHITECTURE.md).

## Credits

The harness-vs-platform framing that shapes open-refinery's design — the
platform as the out-of-process governance layer that harnesses call through —
draws on Traefik Labs' mental model:
[Harness engineering vs platform engineering](https://traefik.io/blog/harness-engineering-vs-platform-engineering-a-mental-model-for-how-both-win).

The deterministic-queue orchestrator — the orchestrator *is* the queue (plain
code), not an agent, for cost, determinism, and parallelism — is inspired by
Mike Piccolo's [Loop Engineering](https://www.linkedin.com/pulse/loop-engineering-just-software-we-have-name-mike-piccolo-yb73c/).

The stance that decomposition belongs in deterministic orchestration rather than
agent-spawned sub-agents (sub-agent delegation is a harness concern, not the
platform's) draws on Anton Vinogradov's
["You don't need sub-agents"](https://www.linkedin.com/pulse/you-dont-need-sub-agents-anton-vinogradov-q7tef).

## License

[MIT](https://github.com/tacoda/open-refinery/blob/main/LICENSE) © Ian Johnson
