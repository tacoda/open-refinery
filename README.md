<p align="center">
  <img src="frontend/public/favicon.svg" width="72" height="72" alt="Open Refinery" />
</p>
<h1 align="center">Open Refinery</h1>
<p align="center"><em>A factory with the lights on.</em></p>

---

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

- **Governance policy layer** — org-wide `(effect, role, action, resource)`
  rules with deny-overrides, plus **strict** rules a lower layer can't override.
  Policies are authored *and* governed: a change to governance walks a
  **per-layer approval workflow** (accept / deny / feedback). Packs seed starter
  rules, skills, commands, and standards (TDD, ATDD, spec-driven, UI
  verification, tech-debt, infrastructure, org policy…).
- **Configurable oversight strategy** — a per-process human-oversight dial
  (L0 manual → L4 fully dark) with a configurable risk profile: which steps are
  **gated**, which **quality-gate attestations** must pass, and the minimum
  approver role.
- **Human approval gates** — gated steps need recorded sign-off: inline, or an
  **async approval queue** with **chained approvals** (an ordered role chain,
  distinct signer per slot) for higher-risk moves.
- **Proactive enforcement** — an org-wide mode of `audit` (default-allow, opt-in
  deny) or **`strict`** (whitelist / default-deny). A **pre-action authorize**
  seam lets a harness verify identity + intent against policy *before* it runs a
  tool / command / host-egress action; **per-namespace whitelists** scope rules;
  every refused attempt is audited.
- **First-class rollbacks** — revert a work item to a known-good prior stage and
  compute a structured **reverse plan** that unwinds the whole deployment: code,
  DB migrations, config, env, libraries, data, services, secret refs, infra,
  DNS — any surface the PR touched. The harness applies it and reports back;
  the platform governs + audits.
- **Teams, cost attribution & concurrency caps** — group users into teams; a
  usage ledger meters units per governed invoke and rolls up cost by team; a
  team's live in-flight concurrency cap is enforced at the invoke seam.
- **Routing policy inputs + traffic graph** — route resolution filters targets on
  region / compliance tags and can prefer lowest cost; a cross-agent traffic
  graph shows who sends how much to which target.
- **Connects your code hosts and issue trackers** — GitHub, GitLab (code hosts);
  GitHub Issues, Jira, Linear (issue trackers), connected by token or OAuth,
  credentials encrypted at rest. Trackers expose **workflow discovery** — the
  tool's own columns/statuses — so a process can be shaped from *your* board
  (your Jira statuses, your Linear states) rather than a generic template.
- Ships work through **customizable processes** — ordered steps with feedback
  loops (board or doctrine archetypes).
- Records a **complete, attributed audit trail** — who did what, to which work
  item, with what inputs — fans it out to **webhooks**, and derives **metrics**
  plus **debt-audit health scores** (factory / harness / charter) with insights.
- **Runs live** — background job runner, scheduled ingest, and a WebSocket live
  channel (job status, new audit events, per-run **live logs**) feeding a
  **visibility-first dashboard** (an overview that surfaces what needs attention,
  a work board, and a right-hand detail/action drawer).
- Enforces **ownership** with **admin-configurable roles**: developers see their
  own work; platform sets org-wide policy; admins audit everything.

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

> Status: **2.0.0 — feature-complete platform** (schema frozen at 1.0; every
> release since is additive, backward-compatible — no breaking change at 2.0).
> The full governed loop plus the platform around it is in place: **admin-
> configurable roles**; **policies** as authored harness artifacts (rule / skill
> / command / agent) with a **strict** override lock and layered precedence;
> **proactive enforcement** (`audit` / `strict` modes, a pre-action `/authorize`
> gate, per-namespace whitelists); **packs** — a curated marketplace of starter
> standards + processes; **per-layer approval workflows** that govern changes to
> governance itself; the **executor** with real **Anthropic / OpenAI / MCP / API**
> backends (API key or OAuth), **routing policy inputs** (region / compliance /
> cost) and windowed quotas; **teams + usage ledger + cost attribution +
> concurrency caps**; a cross-agent **traffic graph**; **first-class rollbacks**
> (full-deployment reverse plans, apply-side reporting); **governance landscape +
> analysis**; **repo coverage & debt-audit health** with GitHub **ingest** (on a
> schedule); **evals & experiments**; **webhooks**; **background jobs** and a
> **WebSocket live channel** with per-run **live logs**; oversight, the async
> approval queue + chained approvals, metrics, agent-run **post-mortems**, and a
> full audit trail — behind a **visibility-first dashboard**. Config lives in the
> **database, not the env** — encrypted, UI-managed, so **only `SECRET_KEY` is
> required in the environment**. Self-hosted API docs with live "Try it out" at
> `/api-docs`. See [CHANGELOG.md](https://github.com/tacoda/open-refinery/blob/main/CHANGELOG.md).

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

### Upgrading

Schema migrations run **automatically on startup** (`serve`). To apply them
explicitly after upgrading the package — before starting the server — run:

```bash
pip install -U open-refinery
open-refinery migrate                            # applies pending migrations
open-refinery migrate --to 9 --yes               # pin an older schema (down; destructive)
```

The schema is frozen at 1.0 — upgrades are additive only, so existing data is
preserved. Downgrading to a pinned version drops the newer columns (and their
data), so it requires `--yes`.

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
| Observability   | `GET /metrics` — WIP, event counts, per-actor activity, lead times; `GET /traffic` — cross-agent traffic graph; per-run live logs |
| Governance      | Policy layer (`audit` / `strict` enforcement, layered strict overrides, per-namespace whitelists) + pre-action `/authorize` gate |
| Reversibility   | First-class rollbacks — revert to a prior stage + a full-deployment reverse plan, applied by the harness and audited |
| Cost & limits   | Teams + usage ledger + cost attribution; live concurrency caps; windowed quotas; region / compliance / cost routing inputs |

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
