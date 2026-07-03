# open-refinery

*An open factory to shine light into the dark.*

A self-hosted dark factory that adds auditability to make it open. Work ships
through customizable processes; every output carries its **provenance**, an
**owner**, and an **audit trail**; every production is **authorized** before it
runs and **logged** as it happens.

> Status: **0.3.0.** Server + bundled dashboard, auth (local / API token /
> GitHub OAuth, roles developer / platform / admin), first-run setup wizard,
> repositories, processes (steps + feedback loops), work items with a governed
> transition loop, oversight levels (L0–L4) with approvals and attestations,
> metrics, and an audit trail — all working and tested. Integrations, targets /
> routing / quotas, and policy governance are on the roadmap.

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
unknown emails are denied. The OAuth client id/secret are the one bit of config
that must be env (they're needed before anyone can log in). API/CI accounts keep
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

open-refinery seed      # populate a fresh DB with sample data + login tokens (dev)
```

Frontend (dashboard) lives in `frontend/` — React + TypeScript + Vite + Tailwind
+ shadcn/ui, built with [bun](https://bun.sh):

```bash
make ui-dev             # Vite dev server (proxies API to :8000)
make ui                 # build the SPA into the package
make dist               # build UI + wheel (the wheel bundles the SPA)
```

The build step is release-time only; end users never need bun/node.

See [PLAN.md](PLAN.md), [CONTRIBUTING.md](CONTRIBUTING.md), and
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## License

[MIT](LICENSE) © Ian Johnson
