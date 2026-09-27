# open-refinery 3.0 — the road to a working factory

*A ticket goes in, a pull request comes out, nothing merges itself.*

This is the plan for 3.0. It has two halves that ship together:

1. **Token/key auth everywhere.** Every service — models, code forges, ticket
   trackers — connects with an API key or PAT. Every authorization-code flow in
   the product is deleted.
2. **The factory.** A work item can be *run*: a governed agent works in a git
   worktree and opens a pull request. Today `transition()` moves a stage and
   `execute()` makes one model call; nothing writes code.

Design lineage is [ghola](https://github.com/tacoda/ghola) — its harness/factory
split, its stage graph, its contracts, and its constraint ladder. What
open-refinery already does better (a hash-chained, queryable, exportable audit
log; RBAC; quotas; approval workflows) is not re-ported.

---

## 0. Where we are

| | Status |
|---|---|
| Service credentials | **Already tokens.** `integrations.py` takes a PAT for GitHub/GitLab/Jira/Linear. OAuth is a *parallel* path, not the only one. |
| Audit | **Parity met.** Hash-chained, append-only, verifiable, exportable, retention-managed — and queryable, which ghola's file log is not. |
| Governance | RBAC, policies, quotas, content filter, approvals + chains + SLA, attestations, recert, evidence packs. All reusable by the factory. |
| Ticket → PR | **Does not exist.** No worktree, no forge driver, no stage runner, no agent loop. |
| Install | Broken on a clean clone: the wheel force-includes `src/open_refinery/static`, which only exists after `make ui`. |
| Tests | 328 pass — but only with `SECRET_KEY` exported. `make test` does not set one. |

## 1. Decisions taken

| Decision | Choice |
|---|---|
| Auth scope | **Strip every authorization-code flow.** GitHub OAuth login, the `/integrations/*/oauth/*` and `/targets/*/oauth/*` connect paths, *and* OIDC SSO all go. Humans: email + password + TOTP. Machines: API tokens. Services: keys/PATs. |
| `deepagents` | **Core dependency**, not an extra. One install, one command. |
| Pipeline model | **Its own concept**, not an extension of `Process`. `Process` is untouched. |
| Pipeline storage | **SQLite, in JSON columns** — the same shape `Process` already uses for `stages` / `transitions` / `gates`. YAML is an import/export *format* for portability, never a storage or override mechanism. |
| State | **All state lives in SQLite.** No `settings/*.yaml`, no job files, no document files. The only thing on disk is the git worktree, because git requires one — and even its claim and path are rows. |

### The thesis change, stated plainly

PLAN.md currently lists orchestration, tool selection and sub-agent delegation as
**harness concerns and explicit non-goals**. 3.0 changes that, and it is worth
stating without hedging:

**open-refinery is both a harness and a factory.**

- The **harness** constrains one turn: the phase's model, thinking level, turn
  cap and tool grant; the prompt it is actually asked; the governance wrapped
  around every call it makes.
- The **factory** runs many turns to a diff: the stage graph, the worktree, the
  contracts, the delivery gate, and a pull request nothing merges for you.

A harness with no factory is a well-behaved agent you cannot get work through. A
factory with no harness runs unattended and cannot tell you what it was allowed
to do. open-refinery has been neither, and has been the *platform* underneath
both — identity, audit, quotas, routing, policy. 3.0 keeps all of that and
builds the other two on top of it, which is why the governance is not bolted on:
it is the layer the harness already stood on.

External harnesses are unaffected. They still call through the API exactly as
before, and the boundary they cross is the same one `GovernanceMiddleware` now
applies per tool call. The platform did not stop being a platform; it stopped
being *only* a platform.

### Why no files

ghola keeps its pipeline in `settings/pipeline.yaml`, its job records in
`state/jobs/*.json` and its run documents in `state/documents/*.md`. That is the
right call for a starter kit somebody clones — `cat state/jobs/<id>.json` is a
debugging tool, and a directory cannot be misconfigured.

open-refinery is not a starter kit. It is a self-hosted server with a database,
a dashboard, an approval workflow and a hash-chained audit log, and file-based
state would sit outside every one of them: a pipeline edited on disk is a
governance change nothing recorded, nothing approved, and no auditor can
reconstruct. `Process` already stores its graph in JSON columns; a pipeline that
did otherwise would be the single piece of state in the product that the audit
trail cannot see.

So the borrow from ghola is the *shape* of the stage graph, not its storage.

### On SCIM

SCIM survives the SSO removal. It provisions accounts with a bearer token; those
accounts then sign in with password + TOTP. It is token-based and stays.

---

## 2. Token/key auth

### 2.1 What is deleted

- `oauth.py` entirely (`PROVIDERS`, `authorize_url`, `exchange_code`, `primary_email`)
- `oidc.py` entirely
- `GET /auth/github/login`, `GET /auth/github/callback`
- `GET|POST /auth/sso/config`, `GET /auth/sso/login`, `GET /auth/sso/callback`
- `POST /integrations/{kind}/oauth/start`, `GET /integrations/{kind}/oauth/callback`
- `POST /targets/{id}/oauth/{provider}/start`, `GET /targets/{id}/oauth/{provider}/callback`
- `deps.provider_creds`, the `{kind}.client_id` / `{kind}.client_secret` settings,
  the `GITHUB_CLIENT_ID` / `GITLAB_CLIENT_ID` env fallbacks
- the `ConnectState` model and its table (migration drops it)
- `SsoConfig`, `OAuthReturn`
- frontend: `oauthLoginUrl`, `connectOAuth`, `SsoSettings`, the provider buttons
- tests: `test_oauth.py`, `test_target_oauth.py`, `test_oidc.py`

`GET /auth/providers` keeps its shape but reports only what remains, so the
login screen has one code path.

### 2.2 What replaces it — one credential surface

The product has two credential stores today: `Integration` (forges, trackers)
and `Target` (models, MCP, APIs). They stay as tables — but they get **one
catalog and one screen**, because "insert service keys" should be one place.

New `src/open_refinery/credentials.py` — the catalog is the single source of
truth for the API, the wizard and the UI:

```python
PROVIDERS = {
  # family: model
  "anthropic":  {"family": "model",   "label": "Anthropic",
                 "fields": [("api_key", "API key", SECRET)],
                 "mint_url": "https://console.anthropic.com/settings/keys",
                 "needs": "a key with Messages API access",
                 "models": ["claude-opus-5", "claude-sonnet-5", "claude-haiku-4-5-20251001"]},
  "openai":     {...}, "google": {...}, "openrouter": {...},
  "ollama":     {"fields": [("base_url", ...)], "needs": "no key — a reachable host"},

  # family: forge
  "github":     {"family": "forge",
                 "fields": [("token", "Personal access token", SECRET)],
                 "mint_url": "https://github.com/settings/tokens?type=beta",
                 "needs": "Contents: read/write · Pull requests: read/write · Metadata: read"},
  "gitlab":     {..., "needs": "scopes: api, write_repository"},
  "gitea":      {..., "fields": [("base_url", ...), ("token", ...)]},
  "local":      {"family": "forge", "fields": [], "needs": "nothing — the request is a file in the repo"},

  # family: tracker
  "jira":       {"family": "tracker", "fields": [("site",...), ("email",...), ("token", SECRET)]},
  "linear":     {...}, "github-issues": {...}, "gitlab-issues": {...},
}
```

Each entry carries `verify(cred) -> {"account": str}` — reusing the existing
`integrations.ADAPTERS` verifiers — so a key is **verified before it is stored**,
and the row is labelled with the account it resolved to. Nothing is saved that
does not authenticate.

**Credentials belong to a person, not the org.** Every key and token is entered
by a user in **their own settings**, encrypted under their row, and used to
authenticate *their* work. There is no shared bot account.

This is already half true and inconsistently so, which is the bug this fixes:

| Today | |
|---|---|
| `Integration` (forges, trackers) | per-user — `owner_id`, listing scoped by `owner_scope()` |
| `Target` (models) | owned by a user but selected by `Route`, which is **per process**. Everyone's work runs on whoever's key the route happens to point at. |

In 3.0 both resolve the same way: **the actor's own credential for that
provider**. A run started by Dana uses Dana's GitHub PAT and Dana's model key.

That is not an ergonomic preference, it is the governance argument:

- the pull request is **authored by the person accountable for it**, not by a
  shared machine user everyone hides behind
- cost and quota attribute to a real person at the call site, which is what
  `record_usage` has always claimed to do
- revoking one person's access revokes it everywhere, immediately, with no
  shared secret to rotate across a team
- the audit trail names an actor whose credential actually made the call

**The cost, stated plainly.** Per-user model keys are the weak point: a team of
ten usually has *one* Anthropic billing relationship, not ten, and telling every
new developer to go get their own API key is friction that per-user forge tokens
do not have (those they already have). Two ways out, and this needs deciding
before Phase 1 ships:

1. **Strict per-user** — as described. Cleanest accountability, most onboarding friction.
2. **Per-user identity, org-wide billing** — forge and tracker credentials stay
   strictly personal (identity matters); an admin may additionally publish a
   **shared model credential** that users fall back to when they have none, with
   usage still attributed per actor by `record_usage`.

Option 2 keeps every governance property above except "no shared secret", and
removes the friction where it actually bites. **Recommended**, but it is a
product call rather than a technical one.

**Resolution order** (`credentials.for_actor(session, actor, provider)`):
the actor's own credential → the org-wide one if the provider allows it and one
exists → a clear `NoCredential` error naming the provider and linking to where
to add it. Never a silent fallback to somebody else's key.

**API** (`routers/credentials.py`):

| Route | Does |
|---|---|
| `GET /credentials/catalog` | the catalog: provider, family, fields, where to mint, what scopes it needs |
| `POST /credentials` | verify → encrypt → store. Returns the resolved account, never the secret |
| `GET /credentials` | **the caller's own** redacted rows: provider, family, account, `last_verified_at`, `status`. Platform/admin may scope to another user for oversight — metadata only, never a secret |
| `POST /credentials/{id}/verify` | re-check a stored key (powers `doctor`) |
| `PUT /credentials/{id}` | rotate in place — same id, same wiring, new secret |
| `DELETE /credentials/{id}` | revoke |

Model credentials stop being hand-written `Target` JSON: picking **Anthropic +
`claude-opus-5`** creates the `Target` for you, with the credential attached and
`unit_cost` pre-filled. `executor._key()` loses its `access_token` branch —
there are no OAuth tokens left to accept.

**UI** — a **Settings → Connections** screen, per user, three tabs
(Models · Code forges · Trackers). Each row: provider, the exact scopes the
token needs, a deep link to where to mint it, **Verify** (shows the account it
resolved to), Rotate, Revoke. A provider the user has not connected shows what
it would unlock, so the screen doubles as the list of what is available.

Onboarding lands here: a new user's first stop is connecting their own services,
and `doctor` plus the dashboard both report which of them are missing.

### 2.3 Sign-up

Step 2 of the product path. Today: first-run wizard creates the admin
(`POST /setup`), everyone else arrives by invitation.

Added: an admin-set org mode, `org.signup ∈ {invite, domain, open}` — default
`invite`, which is what a self-hosted install should do on day one.

- `POST /auth/signup` — 404s under `invite`; under `domain:<example.com>` accepts
  matching addresses; under `open` accepts anyone. New accounts land at
  `developer`. Rate-limited, audited, and never able to mint an admin.

Human sign-in stays **email + password + optional TOTP** for 3.0. See §2.4.

### 2.4 Deferred: passwordless email login codes

**Not in 3.0.** Planned for a later release: replace passwords entirely with a
six-digit code emailed to the address on file, admin-provisioned accounts, and
an admin "re-send code" action.

Recorded here because it has one consequence worth knowing before it is built:
**with no passwords, a broken email sender locks every human out permanently.**
`email.py` today is a port whose default adapter shells out to `mail`, and
invitation links are also returned to the inviter precisely so email being
unconfigured is survivable. That safety net disappears with passwords.

Whenever it lands it needs, at minimum: an `open-refinery login-code <email>`
break-glass CLI for an operator with shell access, a `doctor` check that
test-sends for real, a first-run wizard that will not complete until email
works, and a real SMTP adapter — `LinuxMailSender` is not a credible default for
a product whose logins depend on it. Phase 0's `doctor` (§5) is built with a
slot for that check.

---

### 2.5 The authority model — three domains, not a ladder

The code today treats roles as a **total order**: `developer(1) < platform(2) <
admin(3)`, compared with `at_least()`, with `_SEES_ALL = ("platform", "admin")`
on every scoped listing. Admin can do everything platform can, and more.

3.0 replaces that with **authority as data**: a role carries an explicit set of
powers rather than a position in a line. The three built-in roles are the
**standard configuration** — a sensible default, not a limit:

| role | approves | may propose | users | audit | operational visibility |
|---|---|---|---|---|---|---|
| **developer** | `code` | `code`, `harness`, `factory` | — | own work | own work |
| **platform** | `harness`, `factory` | `harness`, `factory` | — | — | **org-wide operations** |
| **admin** | — | — | **manage** | **full** | users and audit only |

**Roles are customizable.** `Role` already exists as a table and `create_role` /
`delete_role` already exist in `users.py` — they are simply not exposed, with a
note in `routers/core.py` saying arbitrary roles "proved confusing". That note
is right about the symptom and wrong about the cause: a role that is only a
*rank* means nothing, so a fourth one was unanswerable — what does rank 2.5 let
you do? Attaching the columns above makes a custom role legible, so `Role` gains
`approves`, `proposes`, `manages_users`, `reads_audit`, `sees_operations` and a
`builtin` flag, and role management becomes an admin surface in the API, the
dashboard and the CLI.

A team that wants `reviewer` (approves `code`, proposes nothing) or `auditor-lite`
(reads audit only) writes it down; a team that agrees with the three defaults
configures nothing. The built-ins cannot be deleted, and **no role may grant
itself authority it does not have**.

Three things follow, and each is a deliberate loss of convenience:

- **Admin cannot approve anything that ships.** The role that grants access is
  not the role that approves what goes out. A compromised admin account can
  create users and read the log; it cannot merge a change or weaken a rule.
  This is the separation an auditor actually looks for, and it is the reason
  admin is not a superset.
- **Platform cannot approve ordinary code.** It approves *governance* — harness
  and factory changes, and ladder moves. A platform user reviewing a teammate's
  pull request has no special authority over it, which is correct: that review
  is a developer's job.
- **Developers propose governance changes but never approve them.** The
  improve lane (§4.1) is a proposal mechanism for exactly this reason.

`layer` already carries the distinction the table needs — `policies.LAYERS` is
`("factory", "harness", "charter")`, plus `code` for ordinary work — so approval
authority keys off the layer a change belongs to rather than off a rank.

**A naming collision to fix on the way through.** "Layer" currently means two
unrelated things: `Policy.layer` is the *artifact* layer above, while
`ApprovalWorkflow.layer` is a **role name** (`valid_role(session, layer)`).
Two concepts, one word, and this model puts them next to each other. The
artifact sense keeps `layer`; the approval-workflow sense becomes `role`.

**Scope.** This touches `at_least()`, `owner_scope()`, `_SEES_ALL`, and every
`require(...)` guard in `routers/`, so it is **Phase 1.5** rather than something
smuggled into the credentials work. A new `authority.py` reads the powers off
the role row — `may_approve(session, role, layer)`, `may_propose`,
`manages_users`, `reads_audit`, `sees_operations` — and the route guards stop
naming role literals entirely, which is what makes a custom role work without
touching code. `at_least()` survives only where a genuine ordering is meant,
such as walking an approval chain.

Also cleaned up there: **`"senior"` is referenced in three guards in
`routers/org.py` and as the v2 migration default for `min_approver_role`, and is
never seeded.** Because `role_rank()` returns 0 for an unknown role,
`at_least(developer, senior)` is **True** — so a process left on that default has
no effective minimum and a developer satisfies its approval gate. `authority.py`
fails closed on an unknown role, and a repair migration moves those rows onto a
real one.

### 2.6 Surfaces: what drives what

Three surfaces, and the split between them is load-bearing rather than
stylistic.

| Surface | For | Reaches the data via |
|---|---|---|
| **Web app** | the main surface. Everything a person does with the product | HTTP API |
| **CLI** | a full peer for doing the same things, scriptable and ssh-able | HTTP API |
| **Environment variables** | installing, starting and maintaining the *server* — nothing else | the process |

**Environment variables configure the server, never the product.** `SECRET_KEY`,
`DATABASE_URL`, `HOST`, `PORT`, `LOG_LEVEL`, `APP_BASE_URL` — that is the whole
list, and `config.py` already enforces it as a catalog. No credential, pipeline,
phase or policy is ever read from the environment. That is why the OAuth client
id/secret env fallbacks go in this phase (§2.1): they were product configuration
wearing a server variable's clothes.

**The CLI is a peer surface, not a second implementation.** This is the part
worth being strict about, because getting it wrong reintroduces the class of
hole the audit chain just had. The CLI splits in two:

| | Commands | Talks to |
|---|---|---|
| **Server maintenance** — run on the box, by whoever operates it | `init` · `migrate` · `serve` · `doctor` · `config` · `create-admin` · `seed` | the database directly |
| **Doing the work** — run by a person, from anywhere | `credentials` · `runs` · `run` · `pipelines` · `ladder` · `work-items` · `turn` | **the HTTP API** |

The second group goes through the API *on purpose*. The backend is the
governance boundary: RBAC, policy enforcement, quota, content filtering and the
audit trail all live on that side. A CLI that wrote to SQLite directly would
bypass every one of them — a `credentials add` that skipped authorization and
left no audit event is exactly the kind of quiet side door this product exists
to not have.

So an application command authenticates like any other client, with the pattern
`harnesses.py` already uses: `OPEN_REFINERY_URL` and `OPEN_REFINERY_TOKEN`, or
`--url` / `--token`. Those two are connection settings for reaching a server,
which is the one thing the environment is still allowed to say.

This also closes §9.4: the CLI stops being an accretion of maintenance scripts
and becomes the thing that makes the factory scriptable, cron-able and
debuggable over ssh — without becoming a second, ungoverned way into the data.

---

## 3. The factory

### 3.0 deepagents is the framework

ghola's organizing rule is **if a worker does it, ghola does not** — iii ships
the turn loop, the tools, worktrees, the forge client, the approval gate and the
queue, so ghola is small enough to read.

open-refinery's equivalent: **deepagents is the framework, and if deepagents
does it, open-refinery does not.**

| deepagents provides | open-refinery therefore does not write |
|---|---|
| `create_deep_agent` | the turn loop, transcript, retries, token budget |
| `FilesystemMiddleware` + backends | read / write / edit / glob / grep / ls, and where they are rooted |
| `TodoListMiddleware` | in-turn planning and task tracking |
| `subagents=[...]` | in-turn delegation (off by default — see below) |
| `skills=[...]`, `memory=[...]` | how a repo's charter and standards reach the model |
| `interrupt_on` + `Command(resume=...)` | the human-in-the-loop hold and its resume |
| LangGraph checkpointer | durability *within* a turn |
| `wrap_tool_call` middleware | the interception point every guard hangs off |

What is left for open-refinery to write is what no framework has: the **stage
graph** across turns, the **contracts** that refuse a check's self-assessment,
the **worktree and forge** a diff travels through, the **ladder**, and the
**governance** wrapped around every call. That is the same division ghola makes,
against a different framework.

**On sub-agents.** `.claude/references/no-sub-agents.md` already draws the line
in the right place: "an agent's judgment stays inside a single step's
execution." So the rule is narrow and about *stages*, not about delegation —
**a phase never spawns a stage; the graph owns everything that crosses a turn.**

Inside a step, sub-agents are **supported but not the default answer**, and
they are for specific cases rather than a general parallelism tool:

- **`review`** — one reader per dimension (correctness, security, tests,
  conventions) instead of one reviewer asked to check everything. A general
  reviewer checks the thing it read most recently; separate readers with one
  question each do not.
- **`run`** — fanning out genuinely independent parts of an implementation, when
  the work actually decomposes. Not as a habit.

`plan`, `prove` and `improve` keep them off: their job is to reach *one*
verdict, and a fan-out there is a way to get three.

### 3.0.2 Parallelism is workers, not sub-agents

**The preferred way to go faster is to run more jobs at once, not to split one
job inside a turn.** Sub-agents fan out within a single step; workers fan out
across runs. The second is where the throughput is, and it is the one that
stays governable:

| | Sub-agents | Workers |
|---|---|---|
| Unit | one step of one run | a whole run |
| Bounded by | the phase's turn cap | the concurrency cap already in `concurrency.py` |
| Audit | calls attributed to one step | every run separately actor-stamped and subject-linked |
| Failure | a partial turn to reason about | one run fails, the rest are untouched |
| Cost | inside one quota consumption | attributed per run by `record_usage` |

So the reconciler (§3.9) is not a single-threaded loop that walks one run at a
time — it is **N workers claiming actionable runs**, each advancing one run by
one stage, bounded by the team concurrency cap `concurrency.slot()` already
enforces. Ten tickets go through the factory in parallel because ten runs are in
flight, each a clean governed unit, not because one run was shattered into
pieces that have to be reassembled.

That also keeps the worktree claim meaningful: one run, one worktree, one
branch, one pull request. Parallelism inside a run would have several turns
writing to the same checkout, which is the race the claim exists to prevent.

### 3.0.1 Integrations are user configuration, not deployment

The other half of the mapping, and a genuine divergence from ghola. There,
connecting to GitHub means configuring the **`github` worker** — a YAML file,
part of the deployment, changed by whoever runs the system.

Here, connecting to GitHub means **a user pastes a token into their settings**.
It is application data in the database, per-person, at runtime:

- no file to edit, no worker to configure, no restart, no shell access
- adding support for a provider is a catalog entry plus adapter functions
  (§2.2); *connecting* to it is not an engineering task at all
- because it is per-user (§2.2), two people on the same install reach the same
  service as themselves, which no amount of worker configuration can express
- and it is governed like everything else: encrypted at rest, verified before
  it is stored, audited on use, revocable in one click

The operator installs open-refinery once. After that, every connection is
someone's own setting.

New package `src/open_refinery/pipeline/`. `factory.py` (the recipe registry) is
left alone.

```
pipeline/
  graph.py       pure stage machine — next_stage(run, graph, result)
  spec.py        the stage-graph schema, its defaults, and validation errors
  serde.py       YAML ⇄ stage graph, for import/export only
  phases.py      phase config: built-in defaults ← DB rows, with provenance
  contracts.py   PROVEN:/VERDICT: parsing and downgrades
  document.py    the accumulating run document (one section per phase)
  workspace.py   git worktree lifecycle + the claim that stops two runs racing
  forge.py       Forge protocol + github / gitlab / local drivers
  agent.py       the deepagents harness — one turn, one phase
  middleware.py  GovernanceMiddleware — the governance boundary, per tool call
  actions.py     prepare_workspace · commit_and_push · open_pull_request · watch · teardown
  runner.py      the reconciler: advance one run by one stage, idempotently
  ladder.py      constraints, capabilities, rungs, withheld grants, the delivery gate
```

### 3.1 The stage graph

A pipeline is **rows in SQLite**. Shown here as YAML because that is the
import/export format and it reads better than a JSON column, but nothing on disk
is the source of truth. This is the built-in `ship-a-ticket` default:

```yaml
name: ship-a-ticket
first: prepare
terminal: [landed, closed, failed]

model: claude-sonnet-5        # workflow default; a stage may override

stages:
  prepare: { action: prepare_workspace, next: plan }

  plan:
    phase: plan
    model: claude-opus-5      # spend the thinking model once, on the largest blast radius
    requires: [spec]
    produces: [plan]
    skip_when: [revision, rework]
    on_error: continue
    next: run

  run:
    phase: run
    requires: [spec]
    produces: [work]
    on_refusal: { goto: run, max: 2, stop_when_identical: true }
    next: prove

  prove:
    phase: prove
    requires: [work]
    produces: [proof]
    contract: proven
    revert_worktree_changes: true     # a check may run; it may not repair
    next: review

  review:
    phase: review
    requires: [work]
    produces: [review]
    contract: verdict
    next: commit

  commit:
    action: commit_and_push
    on_refusal: { goto: run, max: 2, stop_when_identical: true }
    next: publish

  publish: { action: open_pull_request, next: waiting }

  waiting:
    action: watch_pull_request
    on_merge: landed
    on_close: closed
    on_comment: rework

  rework: { action: prepare_workspace, next: run }
```

**Storage.** One `Pipeline` row — `id, name, version, owner_id, first,
terminal (JSON), model, stages (JSON), created_at` — matching how `Process`
already stores `stages` / `transitions` / `gates` / `checks`. Saving bumps
`version` and writes a new row; a `Run` pins the `pipeline_version` it started
under, so **editing a pipeline never changes a run already in flight**. Old
versions are kept, which is what makes "why did this run do that" answerable
months later.

**YAML is a format, not a home.** `GET /pipelines/{id}/export` emits the document
above; `POST /pipelines/import` parses one. That keeps ghola's copy-a-file
ergonomics and lets a pipeline be reviewed in a pull request, without any state
living outside the database, the audit trail or the approval workflow.

`graph.py` is **pure**: `next_stage(run, graph, result)` is a function of three
dicts. Every branch — refusal, revision cap, identical-refusal stop, contract
downgrade, optional/opt-in, terminal — is unit-testable with no agent, no git,
and no forge. This is the property that makes the factory worth writing this way.

### 3.2 Creating and wiring a workflow — the builder

Four ways in, all writing the same rows:

1. **Template gallery** — `ship-a-ticket`, `quick-fix`, `strict-review`,
   `docs-only`, each with a one-line "what you give up by using this" note.
   Shipped as `Pack` entries, the mechanism already in the product.
2. **Visual builder** — a stage list. Each stage: a phase or an action, what it
   requires and produces, its contract, its refusal policy, its next stage. The
   existing `<Pipeline>` component already renders a stage graph; it gains edit
   affordances. Saving writes the JSON columns directly.
3. **Import / export YAML** — paste or upload a document for people who would
   rather type it or keep it in a repo, with `POST /pipelines/validate`
   returning errors that name the offending stage.
4. **From a tracker's columns** — `list_workflow()` already discovers a Jira /
   Linear / GitHub-Issues board's statuses. Those become stages.

**Config on a workflow**: a `model:` key at the top (the default) and per stage
(the override), plus `oversight:`, `max_revisions:`, and per-stage `tools:`.
Model names resolve through the existing `Target` + `Route` machinery, so
failover, quotas, cost attribution, region and compliance filtering all apply
unchanged — a workflow saying `model: claude-opus-5` is *routing config*, not a
second way to reach a provider.

**Triggering a run**: `POST /runs {work_item_id, pipeline_id}`, a **Run** button
on any work item, autostart on tracker sync, and inbound webhooks (§3.8).

### 3.3 Phases — the harness

A `Phase` row is a named turn configuration: `model`, `thinking_level`,
`max_turns`, `tools` (an allowlist), `prompt`. Six ship as defaults, editable in
the UI, following ghola's shape:

| phase | model | may | may not |
|---|---|---|---|
| `refine` | opus | read | write. It decides what to ask for |
| `plan` | opus | read | write. Deciding and building are separate turns |
| `run` | sonnet | read, write, execute | — this is where the tokens go |
| `prove` | sonnet | read, execute | **write.** A check may run; it may not repair |
| `review` | sonnet | read | write. A reviewer that fixes is grading its own work |
| `improve` | opus | read | write. The lane proposing charter changes cannot apply them |

`prove` and `review` are handed the spec and the diff — **never the run phase's
summary of its own work**. A check fed the work's own account of itself is
grading a story.

### 3.4 The agent

```python
agent = create_deep_agent(
    model=<LangChain model built from the routed Target + its decrypted credential>,
    system_prompt=<phase prompt + the repo's charter>,
    backend=CompositeBackend(
        default=StateBackend(),
        routes={"/workspace/": FilesystemBackend(root_dir=worktree)},
    ),
    middleware=[
        FilesystemMiddleware(backend=..., tools=<phase grant − ladder.withheld()>),
        GovernanceMiddleware(session, actor, audit, run),
    ],
    interrupt_on=<derived from the process oversight level>,
    checkpointer=SqliteSaver(<the app database>),
)
```

**`GovernanceMiddleware` is the whole point.** It wraps every tool call with the
governance open-refinery already has, now applied *inside* the turn:

- rung-3 ladder predicates — deterministic, refusing in the rule's own words
- `policies.enforce(role, action, resource)` — the existing RBAC gate
- `consume_quota` + `record_usage` — cost attribution at the call site
- `scan_content` on arguments and results — the existing content filter
- one `AuditSink.write` per call, subject-linked to the run

This is what makes 3.0 coherent rather than "open-refinery ships an agent": the
platform governed the call site before, and it governs the same call site now.

### 3.5 Oversight → interrupts → the approvals queue

`oversight.LEVELS` is already a five-rung dial. It maps onto `interrupt_on`:

| level | a person answers | refuses without asking |
|---|---|---|
| `manual` | every call | nothing |
| `assisted` | every write | reads run |
| `supervised` | what a ladder rule marks `ask` | the ladder, deterministically |
| `autonomous` | nothing; notified out of band | the ladder, and `ask` degrades to **refuse** |
| `dark` | nothing | the ladder, and `ask` degrades to **refuse** |

**`ask` never becomes `allow`** at any level — ghola's rule, and the right one.
An unattended factory reading "ask" as "yes" has answered a question nobody put.

An interrupt lands in the **existing approvals queue**: approval chains, minimum
approver role, SLA, escalation and notifications all apply with no new code.
Approving resumes the LangGraph thread with `Command(resume=...)`.

### 3.6 Contracts — a check that grades itself is not a check

Ported from ghola, pure, and matching the structured-output rule:

- `PROVEN: yes` with no command line under any criterion → downgraded to `unproven`.
  Evidence or it did not happen.
- A `concerns` or `blocker` verdict naming no `file.ext:line` → downgraded to
  `unreadable`. An objecting review that names nothing is a mood.
- **An answer that cannot be parsed is never read as a pass.** It becomes
  `unreadable`, which a person looks at. This is what stops a check whose output
  format drifted from reading as approval for weeks.

The parsed `Answer` is stored **structured** on `RunStep` — value, findings,
evidence, `downgraded_from`, why — never as a prose blob.

### 3.7 The forge

A `Forge` Protocol (protocols over inheritance, per the working rules) with four
questions: open a request, read its state, read what people said, say something
back.

```python
class Forge(Protocol):
    def open_pr(self, cred, repo, branch, base, title, body) -> dict: ...
    def pr_state(self, cred, repo, number) -> dict: ...
    def comments(self, cred, repo, number) -> list[dict]: ...
    def say(self, cred, repo, number, text) -> None: ...

FORGES = {"github": ..., "gitlab": ..., "local": ...}
```

`local` is no forge at all — the request is a markdown file in the repository.
It needs no account and no token, it is the shortest path to seeing the factory
work end to end, and it is the proof the seam is a seam rather than a rename.

### 3.8 Intake — tickets in

Three ways, all landing on the same `create_work_item` → `POST /runs`:

1. **Sync** — `sync_tracker()` exists; it gains an `autostart` flag.
2. **Inbound webhooks** — `POST /intake/{integration_id}` with a per-integration
   HMAC secret, for Jira / Linear / GitHub Issues. (`webhooks.py` is outbound
   today; this is the other direction.)
3. **Manual** — a Run button, or `POST /runs`.

**Rework** closes the loop: `watch_pull_request` polls the PR; a human comment
that is not the factory's own moves the run to `rework`, which re-prepares the
workspace and re-runs with the comment as the brief.

### 3.9 Durability

ghola gets this from iii's durable queue. open-refinery gets it from the
database it already has:

- The `Run` row **is** the durable state.
- A pool of **workers** claims actionable runs and advances each by exactly one
  stage (§3.0.2). Claiming is a conditional update on the run's recorded stage,
  so two workers cannot take the same run.
- Every stage guards on that recorded stage, so at-least-once delivery does the
  work once.
- A crash between stages **resumes rather than restarts** — the next worker to
  tick picks the run up where it stopped.
- Concurrency is bounded by the team cap `concurrency.slot()` already enforces,
  so parallelism is governed rather than merely fast.

No Redis, no Celery — both already deferred in PLAN.md, and neither is needed
for this property.

---

## 4. The ladder

The one idea from ghola worth taking wholesale. A constraint has a **rung**: the
mechanism that carries it. "Money is Decimal" in a markdown file is rung 0, and
prose is a request. The same sentence as a hook that refuses the write is a
guarantee.

| Rung | Carried by | Sees | In open-refinery |
|---|---|---|---|
| 0 | prose in the charter | nothing. It asks | `Standard` rows (packs) — already shipped |
| 1 | the grant | function ids, before any call | `Phase.tools` minus `ladder.withheld()` |
| 2 | a hook on the call | the arguments, before the write lands | the target repo's own pre-commit hook |
| 3 | a callback in the turn | the call; may hold it for a person | `GovernanceMiddleware` |
| 4 | the delivery gate | the finished diff, before the commit | `commit_and_push` |
| 5 | CI | the merged tree, after everyone left | surfaced from the forge's checks API |

Two consequences, both the point. **A rung is a place, not a strictness** — rung 3
sees a call and not a diff, rung 4 sees a diff and never the call, so a rule that
matters names both. And **climbing costs something** — pick the cheapest rung that
can actually see the thing the rule is about.

A `Constraint` row: `text, layer (project|team|org), rung, predicate, scope,
withholds[]`. `GET /ladder` returns both ladders plus `withheld` — the list the
factory subtracts from a phase's grant before the turn starts.

### 4.1 Promotion and demotion — the factory improves itself

The ladder is not a report. A rung is a *place a rule is carried*, so moving a
rule up the ladder is **work**: promoting "no secrets in source" from rung 0 to
rung 2 means somebody writes the predicate and wires the hook. That work is
exactly what the factory does.

So the loop closes:

```
improve lane reads the record  →  proposes a promotion, citing the runs
      ↓
   a human approves                        ← the first gate
      ↓
the promotion becomes a work item          ← ordinary governed work
      ↓
the factory runs it: writes the predicate, wires the rung
      ↓
   a pull request                          ← the second gate; a human merges
```

**The factory implements its own governance improvements, after human
approval.** That is the point of having a factory at all: the thing that ships
work can ship the rules that constrain it, through the same gate as everything
else, leaving the same audit trail.

**Promotion and demotion are not symmetric**, and the asymmetry is the safety
property:

| | Promotion (more enforcement) | Demotion (less enforcement) |
|---|---|---|
| Proposed by | the improve lane, from evidence | a person, or the improve lane |
| Approval | one approver | the process's **approval chain**, at `min_approver_role` or above |
| Implemented by | **the factory**, as a normal run → PR | a person. The factory proposes, never performs |
| If nothing is approved | the rule stays where it is — safe | the rule stays where it is — safe |

A demotion is the one move that makes the system weaker, so it never runs
unattended and the factory never carries it out itself. Everything else about
the two paths is identical, including that **nothing is applied without a
merge** — the ladder commits no code of its own.

Every move is audited (`ladder-move`), carries the evidence it was proposed
from, and names the runs that motivated it. A proposal that cannot be traced to
evidence is dropped rather than repaired — a lane that always finds three things
is one nobody believes by the third time.

### 4.2 Capabilities climb too

The second ladder, joined to the first at rung 1: a constraint *withholds* a
function, a capability *grants* one. Promoting a capability from `project` to
`org` is the same shape of work — and the same two gates — as promoting a
constraint. `GET /ladder` returns both sides plus the net `withheld` list,
because a phase's effective grant is the one number both ladders exist to
produce.

---

## 5. Install, run, operate

Step 1 of the product path, and where the borrowed operator tooling pays off.

**Fixes to what is broken today**

- Commit `src/open_refinery/static/.gitkeep` so a clean `uv sync` builds the
  wheel without `make ui` having run first.
- A root `conftest.py` sets a test `SECRET_KEY`, so `make test` is green on a
  fresh clone.

**New commands**

| Command | Does |
|---|---|
| `open-refinery init` | generate `SECRET_KEY`, write `.env`, create the DB, migrate, print the URL |
| `open-refinery doctor` | SECRET_KEY set · DB writable and migrated · `git` present · every credential verifying, named · a model reachable · forge auth good · `deepagents` importable. **The answer to "why did that fail" is usually here.** |
| `open-refinery config` | every effective setting **with the source that produced it** — built-in default, environment variable, or database setting. A default is never a magic number you go hunting for in the code. |
| `open-refinery run <work-item>` | trigger a run from the terminal |
| `open-refinery pipeline check` | validate a pipeline and print the stage graph *before* paying for one |

`doctor` and `config` are the highest-value things in this document that are not
the factory itself.

---

## 6. Sequencing

Each phase ends green (`make test`), and every schema change ships its migration
and its `DOWNGRADES` reverse.

| # | Version | Ships |
|---|---|---|
| 0 | 2.13.0 | ✅ Install fixes · `conftest` · `init` · `doctor` · `config` · **audit chain hardened** (keyed links, signed checkpoints, authenticated head, full-export signature). A clean clone installs, tests and serves. |
| 0.1 | 2.13.1 | `targets --check` — prove a model target authenticates without paying for a run (§9.1). |
| 1 | 2.14.0 | **Tokens only.** `credentials.py` + catalog + API + Connections UI. Every OAuth and OIDC path deleted; migration drops `connect_states`. |
| 1.5 | 2.14.5 | **The authority model** (§2.5). `authority.py`; customizable roles with explicit powers + admin role CRUD; `require()` guards stop naming role literals; `owner_scope` splits operations from audit; the `layer` naming collision; the `"senior"` fail-open repaired. |
| 2 | 2.15.0 | **Sign-up.** `org.signup` modes, `POST /auth/signup`, onboarding that ends on a verified credential. |
| 3 | 2.16.0 | **The graph.** `spec.py`, `graph.py`, `contracts.py`, `document.py`, `phases.py`, the `Pipeline` + `Run` + `RunStep` models. Pure and fully tested — no agent, no git, no forge. |
| 4 | 2.17.0 | **Workspace + forge.** `workspace.py`, `forge.py` (github/gitlab/local), `actions.py`. A run reaches a real PR with a stub phase. |
| 5 | 2.18.0 | **The harness.** `deepagents`, `agent.py`, `GovernanceMiddleware`, routing through `Target`, oversight → interrupts → the approvals queue. |
| 6 | 2.19.0 | **The ladder.** `Constraint`, rungs, withheld grants, the delivery gate, `/ladder` + UI. |
| 7 | 2.20.0 | **Intake + builder.** Inbound webhooks, autostart, rework-from-comment, the workflow builder and template gallery. |
| 8 | **3.0.0** | Default pipeline packs, the Runs dashboard with a live trace, the `improve` lane, `docs/ADOPTING.md` + `docs/LIMITATIONS.md`, release. |

Phase 4 is the first one where the product does something it cannot do today.
Phases 0–3 are all groundwork, and phase 3 is deliberately a pure-function
milestone so the state machine is proven before an agent is attached to it.

## 7. The 3.0 acceptance test

One scripted path, run end to end against a scratch repository with the `local`
forge, so it needs no accounts:

```
pip install open-refinery
open-refinery init && open-refinery serve
→ sign up (first admin)
→ paste an Anthropic key and a GitHub PAT; both verify and name the account
→ pick the "ship-a-ticket" template, set the model, save
→ connect GitHub Issues; sync; a ticket arrives as a work item
→ Run
→ plan · run · prove · review · commit · publish
→ a pull request, with the run document as its body, citing audit record ids
→ nothing merged itself
```

When that runs from a clean machine without a detour, it is 3.0.

## 8. Risks

| Risk | Handling |
|---|---|
| `deepagents` + LangChain + LangGraph in core | Taken deliberately (§1). Pin a floor, and keep `agent.py` the only module importing it, so the blast radius of an API change is one file. |
| The harness/platform thesis change | Stated in PLAN.md (§1), not smuggled in. The governance seam is unchanged. |
| Agent writes outside the worktree | `FilesystemBackend(root_dir=worktree)` is the boundary; rung 1 withholds what a phase never needs; rung 4 sees the finished diff. |
| Cost runaway | `max_turns` per phase, existing quotas at the call site, and windowed rate caps. `consume_quota` already refuses before consuming. |
| Prompt injection from a ticket body | A ticket is untrusted data. It reaches a phase as a quoted spec, never as instructions, and rung 3 governs every call it could provoke. |
| Schema frozen at 1.0 | Every 3.0 table is **new**; no existing column changes type. Additive only, as the rule requires. |

---

## 9. Parity gaps — what else ghola has

Everything above covers ghola's core: the stage graph, phases, contracts, the
worktree, the forge, the ladder, oversight, rework, `doctor` and `config`. This
section is the sweep for what is *left*, so the gaps are decisions rather than
discoveries.

Three are already **ahead** and need no work: the audit log (hash-chained,
keyed, queryable, exportable, retention-managed — ghola's is a file), oversight
(a five-rung dial with approval chains, SLA and escalation, against ghola's
four), and RBAC/quotas/content-filtering, which ghola has no equivalent of.

### 9.1 Must land in 3.0

| Gap | ghola | Plan |
|---|---|---|
| **Per-repository factory config** | `repos.toml` — base branch, `max_revisions`, prepare/cleanup commands, which forge, per repo | **Real gap.** `Repository` has no factory config at all. Add columns: `base_branch`, `forge`, `max_revisions`, `prepare_cmd`, `cleanup_cmd`. Without it every repo gets identical treatment, which fails on the first repo whose tests need a setup step. **Phase 4.** |
| **Charter → the agent** | the target repo's `AGENTS.md` / `.agents/` reach the turn via the `directory` worker | `ingest.py` already *reads* exactly these surfaces — into `Claim` rows, for governance scoring. Nothing feeds them to the model. Wire them as deepagents `memory=[...]`, and enabled `Standard` rows (packs) as `skills=[...]`. Cheap, and it is the difference between an agent that knows the house style and one that guesses. **Phase 5.** |
| **`make models`** | prints what the router can actually reach | `doctor` counts targets but never calls one. Add `open-refinery targets --check`: resolve each target, authenticate, report reachable/unreachable. "Why did every run fail at routing" should not need a run to answer. **Phase 0.1 — small, and it pays back immediately.** |
| **`make turn PHASE=… PROMPT=…`** | one ad-hoc turn in a workspace, outside any job | No equivalent, and no way to test a phase's prompt or tool grant without paying for a whole run. Add `open-refinery turn --phase plan --prompt … --repo …`. **Phase 5**, alongside the harness. |
| **`idea:` → a spec** | `make idea IDEA="a rough sentence"` runs `refine` before anything is built | The `refine` phase is in the phase table but intake (§3.8) only covers tickets that are already written. A ticket body is often a sentence. Wire `refine` as the opt-in first stage it already is in the default pipeline. **Phase 7.** |

### 9.2 Should land in 3.0

| Gap | ghola | Plan |
|---|---|---|
| **The improve lane** | reads its own audit log and job records, proposes changes, **drops any proposal it cannot trace to evidence**, applies nothing — an accepted proposal becomes a spec that goes through the same pipeline | Listed in Phase 8 but too thinly for what it is. open-refinery has the raw material already — `postmortem.py`, `debt.py`, `analysis.py`, `anomalies.py`, and a far better evidence base than ghola's files. The two rules worth porting exactly: **evidence or the proposal is dropped** (a lane that always finds three things is one nobody believes by the third time), and **nothing is applied** — a proposal becomes a work item and goes through the same gate as any other work. The one exception, as in ghola, is a ladder move, and a move that *reduces* enforcement needs approval. |
| **Prompt evals** | `evals/*.json`, `settings/evals.yaml`, `make eval`, and a doc that says read this *before you edit a prompt* | `experiments.py` does A/B with control/treatment and significance — the machinery exists but is aimed at process changes, not prompts. Phase prompts are the highest-leverage, least-tested thing in the factory. Point the existing experiment machinery at phase prompts and ship two starter evals, as ghola does. |
| **Cost is marked before it is spent** | `make help` puts a `$` against every target that sends a paid turn | A small idea that repays constantly. The Run button, the CLI and the pipeline builder should all say what a run will cost before it starts — targets already carry `unit_cost` and phases carry `max_turns`, so an estimate is arithmetic we already have the inputs for. |

### 9.3 Deliberately not ported

| | Why |
|---|---|
| **Drop-in extension directories** (`actions/`, `guards/`, `predicates/`, `forges/`) | ghola finds a `.py` by filename with no registration. That is right for a kit you clone and own; it is **arbitrary code execution as a feature** in a multi-user self-hosted server, and it is file-based state (§1). The governed equivalent: guards and predicates are `Constraint` rows with a named, versioned predicate from a registry; a new forge or action is a package entry point, installed deliberately. Less convenient, and the convenience is the part that does not survive multi-tenancy. |
| **`worker-compose.yaml` / the 26 workers** | Architectural, not a gap. deepagents is the framework (§3.0); open-refinery is one process with one database, which is the deployment story the product already promises (`pip install`, `serve`). |
| **ghola's file-based job and document store** | Deliberate for a starter kit — `cat state/jobs/<id>.json` is a debugging tool. Wrong here: it is state outside the audit trail and the approval workflow (§1). |
| **`make up` / `down` / `status`** | Multi-process lifecycle management for an engine plus workers. One `serve` process needs none of it. |

### 9.4 The one thing ghola has that is genuinely hard to match

ghola's `make` surface is **the whole operator interface**, and it is legible:
one screen, grouped, with a `$` against anything that spends money. Every
capability is reachable from a terminal without a browser.

open-refinery's CLI grew by accretion. **§2.6 is the answer**: the CLI is a peer
surface to the web app, split between server maintenance (direct to the database)
and doing the work (through the API, so governance applies). Phase 0 added
`init`, `doctor` and `config`; every later phase ships its application commands
alongside its routes rather than after them — `credentials` in Phase 1, `runs`
and `run` in Phase 4, `ladder` in Phase 6.

Shipping them per-phase rather than saving a CLI push for Phase 8 is deliberate:
a command written beside its route stays honest about what the API can actually
do, and a governance product whose only surface is a SPA is one nobody can
script, cron or debug over ssh.
