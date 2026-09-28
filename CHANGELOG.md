# Changelog

All notable changes to open-refinery are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/); versions follow semver.

## [2.21.0] — 2026-09-27

*Providers, models, forges and trackers — as ports. **9 → 19 providers**, and
adding the next one is a single entry.*

### Fixed
- **Two provider lists disagreed.** `executor.py` knew Anthropic and OpenAI;
  `pipeline/agent.py` knew only Anthropic. A target routed to OpenAI worked for
  `/execute` and **failed inside a harness turn** — the same target, a different
  answer depending on which path reached it. One registry now
  (`models_port.py`), read by both, with a test asserting neither keeps its own.
- **A gateway's suggested models did not route back to it.** OpenRouter
  suggested `anthropic/claude-sonnet-5`, which resolved to *Anthropic* and asked
  for the wrong key; Groq's suggestions resolved to nobody. Found by a port
  contract test, not by a user.

### Added
- **`models_port.py`** — one model port, nine providers: Anthropic · OpenAI ·
  Google · Groq · Mistral · DeepSeek · OpenRouter · Azure OpenAI · Ollama.
  Routing is by longest prefix, so a provider adding `gpt-oss-` does not lose to
  `gpt-`, and an explicit `provider/model` always beats a guess. One code path
  via `init_chat_model`, so adding a provider is an entry rather than another
  `if provider ==` branch — which is the branch that let the two seams drift.
- **Two more forges**: **Gitea/Forgejo** and **Bitbucket**. Each is twenty lines
  because the seam already asks the four questions — open a request, read its
  state, read what people said, say something back.
- **`trackers.py`** — the loosest seam, now a protocol. It was a dict of dicts,
  so "does this one list issues?" was a key lookup. Adds **GitLab Issues** and
  **Shortcut** alongside GitHub Issues, Jira and Linear, and every tracker can
  hand over its columns for a process to adopt.
- **The connect screen is derived from the ports**, not repeated beside them.
  That list was written twice and drifted; now a provider added to a port shows
  up in Connections without anybody remembering to add it.
- **`tests/test_ports.py`** — the contract each seam keeps: every model routes,
  every suggestion routes *back*, every forge answers all four questions, every
  tracker satisfies the protocol, and every provider reaches the connect screen
  saying what its credential must carry.

750 tests pass.

## [2.20.0] — 2026-09-27

*Phase 5 on the [road to 3.0](docs/PLAN-3.0.md): the harness. A phase now runs a
real turn, and every tool it reaches for is governed.*

### Added
- **`deepagents` as a core dependency**, pinned `>=0.7,<0.8` with a ceiling
  because it is pre-1.0 and carries pillar 2. **`pipeline/agent.py` is the only
  module that imports it** — a test enforces that, so an upstream API change has
  a one-file blast radius rather than reaching the factory.
- **`pipeline/phases.py`** — what one turn is allowed to be: model, thinking,
  turn cap, **tool grant**, and the prompt it is actually asked. The grant is
  **rung 1** of the ladder: a phase is not told not to edit, it is *never handed
  an editor*, which is why `prove` and `review` need no predicate to be stopped
  from repairing what they find. Seven ship; a team overrides a row, and only
  what it sets is overridden.
- **`pipeline/middleware.py`** — governance per tool call, and **no framework in
  it**: `Governed` decides, `agent.py` adapts it to the harness's hook. The
  content filter runs over arguments *including nested ones*, quota is checked
  before it is consumed, and every call is audited against its run — so a run's
  whole tool history is one query.
  - A refusal is **handed back to the model as a tool result**, not raised. An
    exception ends the turn; a refusal the model can read is one it can work
    around, which is the difference between a governed agent and a broken one.
- **`pipeline/agent.py`** — the turn. The filesystem is rooted at the run's
  worktree so it cannot write outside; the repository's own rules reach it as
  `memory` (what `ingest` was reading all along); and the model is resolved
  through the **actor's own credential**, so cost attributes to the person
  accountable for the work.
- **Oversight becomes interrupts.** `manual` asks about every call, `assisted`
  about every write, `supervised` about execution. At `autonomous` and `dark`
  nothing is asked — **`ask` never becomes `allow`**, it degrades to the ladder
  refusing. An unknown level falls back to `supervised`, so a typo cannot
  silently mean "nobody is asked".
- `GET /phases` (open — a constraint nobody can read is one nobody can rely on)
  and `PUT /phases/{name}` (`approve:harness`, because the harness is the
  lead's). `open-refinery phases` prints what each may do.

### Changed
- **A run uses the harness when the person who started it has a model key, and
  the stub when they do not.** A fresh install walks the whole graph offline,
  and connecting a key is the only thing that has to change to make it real.
  Somebody *else's* key does not make your run real.

### Not yet verified
A live model call. The wiring is tested up to the call itself — the grant, the
interrupts, the governance decisions, the brief, and the failure when no key is
connected — but no turn has been run against a real provider in this session.

701 tests pass.

## [2.19.0] — 2026-09-27

*Phase 4 on the [road to 3.0](docs/PLAN-3.0.md): the worktree, the forge, and
the delivery gate. **A run can now reach a real pull request.** The harness is
still a stub — Phase 5 attaches it — so the phase that would write code writes
nothing, and the gate correctly refuses a run with no diff.*

### Added
- **`pipeline/workspace.py`** — a git worktree per run, off its own branch, so
  several runs against one repository do not trip over each other. `git` here
  **never uses a shell**: passing `git add -A && git commit -m x` as a command
  tries to spawn a program with that literal name, which fails in a way that
  reads like a commit that worked. A repository's *own* commands
  (`prepare_cmd`, `test_cmd`) do go through a shell, because a repo says
  `pip install -e .` and means it — safe only because that string comes from
  the repository's config rather than from a model.
- **`pipeline/forge.py`** — a `Forge` protocol answering four questions, with
  **github**, **gitlab** and **local** drivers. `local` is no forge at all: the
  request is a markdown file, a merge is whether git says the branch is an
  ancestor of the base, and it needs no account or token. It is the shortest
  path to seeing this work, and the proof the seam is a seam rather than a
  rename. GitHub reports a merged request as `closed`, so the two are told
  apart explicitly or every merge reads as an abandonment.
- **`pipeline/actions.py`** — `prepare_workspace` · `commit_and_push` ·
  `open_pull_request` · `watch_pull_request` · `teardown`, each returning the
  same shape a phase does so the state machine does not care which ran.
  - **The delivery gate.** Nothing changed → an *error*, because pushing a
    branch with no commits on it is the failure that looks most like success.
    The repository's hook refusing → a **refusal**, which sends the run back
    with the hook's own words as the brief; reading a non-zero exit as success
    would silently disable the revision loop.
  - The pull request body **is the run document** — the account of the work is
    already written by the time a person reads it.
  - A comment the factory wrote is not a reviewer's: it pushes with the
    operator's credentials and *is* the author, so telling them apart by author
    would find none.
- **`pipeline/runner.py`** — advances a run by exactly one stage and writes
  back, so a crash between stages resumes rather than restarts. `POST
  /runs/{id}/advance` and `open-refinery runs advance`.
- **Per-repository factory config** (migration **v26**): `base_branch`,
  `forge`, `max_revisions`, `prepare_cmd`, `cleanup_cmd`, `test_cmd`. Without
  it every repo gets identical treatment, which fails on the first one whose
  tests need a setup step.

### Fixed
- **A check could destroy the work it was checking.** `prove` carries
  `revert_worktree_changes`, and reverting everything uncommitted wiped what
  the run phase had just built — the delivery gate then reported an empty diff.
  The work is now staged before a check runs, so reverting restores it and only
  what the check touched goes back. Found by tracing a real run stage by stage,
  and pinned by two tests.
- The `run_id[:12]` slice lived in three places and a test guessed it wrong.
  One `worktree_path()` decides.

668 tests pass, including 30 that drive real git repositories rather than mocks.

## [2.18.0] — 2026-09-27

*Phase 3 on the [road to 3.0](docs/PLAN-3.0.md): the workflow canvas, plus the
frontend cleanup it needed first.*

### Added
- **The workflow canvas** (`frontend/src/Canvas.tsx`). The canvas **is** the
  builder, not a picture of one: what you draw is what gets saved, and saving
  writes a new version rather than editing in place.
  - **Edges are typed and drawn differently** — `next` solid, a refusal amber
    and dashed going backwards, the pull-request outcomes in their own colours.
    A revision loop drawn like ordinary flow is invisible until it costs a turn.
  - **The inspector is the stage's config**: phase or action, model, contract,
    the approval gate, the refusal policy, `requires` / `produces`. Adding a
    preferred model is clicking a node.
  - **Validation is inline, not on save** — `/pipelines/validate` on a 250 ms
    debounce, so an unreachable stage shows up while you are drawing it. Save is
    disabled while the graph is invalid.
  - Node positions persist on the pipeline, so a graph opens how it was left.
- **Four templates to build from**, each saying what it **gives up** — a
  template chosen without knowing that is a decision nobody made.
  `ship-a-ticket` (the full loop) · `quick-fix` (one turn; no plan, no proof, no
  review, no revision loop) · `strict` (everything on, plus a second reader for
  the security surface) · `docs-only` (no proof stage — nothing to run).
  Every one keeps the commit gate and ends with a person.
- `GET /pipelines/templates` and `/pipelines/templates/{name}`.

### Fixed
- **`/pipelines/templates` was being read as a pipeline id.** FastAPI matches in
  declaration order, and `/pipelines/{pipeline_id}` was declared first, so every
  literal below it was shadowed — the route existed in the schema and 404'd in
  practice. The literal paths now sit above the catch-all, and
  `test_route_coverage.py` **resolves** these paths instead of only checking the
  schema, which is the gap that let it through.

## [2.17.0] — 2026-09-27

*Phase 2 on the [road to 3.0](docs/PLAN-3.0.md): the stage graph, as a pure
state machine. Deliberately the milestone with **no agent, no git and no
forge** — the factory's whole behaviour is decidable before any of those
exist.*

### Added
- **`pipeline/spec.py`** — the stage graph. A stage names a **phase** (a turn of
  the harness) or an **action** (something the factory does itself), never both.
  Validation is strict about the two ways to write a pipeline that looks fine
  and hangs: a stage nothing reaches, and a stage with no way out. Errors name
  the **offending stage**, because an error naming a JSON path is one somebody
  ignores. Reachability follows *every* edge — walking `next` alone reports
  `rework` unreachable, since it is reached only by `on_comment`.
- **`pipeline/graph.py`** — `advance` and `plan_next`, pure functions of three
  dicts. Every branch is testable with a literal: the revision cap, an
  **identical refusal** (a gate repeating itself word for word has shown its
  complaint is not about the diff), `on_error: continue`, the pull-request
  outcome edges, and the three lookalike skip conditions — `skip_when`,
  `optional` (opt-**out**) and `opt_in`, which are separate because conflating
  them makes every optional stage default-on.
- **`pipeline/contracts.py`** — a check that grades itself is not a check.
  `PROVEN: yes` with no command under it is downgraded to `unproven`; an
  objecting review naming no `file.py:line` is downgraded to `unreadable`; and
  **an answer that cannot be parsed is never read as a pass**, which is what
  stops a check whose output format drifted from reading as approval for weeks.
  Absorbs `attestations.py`, per the system review.
- **`pipeline/document.py`** — the run document, which each stage appends to, so
  the pull request body is **already written** by the time a person reads it.
  A re-run replaces its section rather than appending; two contradictory
  "What was built" sections is worse than either.
- **`Pipeline` / `Run` / `RunStep`** (migration **v26**). Saving a pipeline
  writes a **new version** rather than editing in place, and a run pins the
  version it started under — so an edit never reaches work already in flight,
  and the graph a finished run followed is still readable months later. A
  downgraded answer is stored **structured**, so "how often did prove claim yes
  without evidence" is a question about the factory rather than about one run.
- **Routes**: `/pipelines` (read open — a developer must see the stages their
  work moves between; saving is `approve:factory`), `/pipelines/validate` for
  the canvas, `/pipelines/{id}/export`, `/pipelines/templates/default`,
  `/runs`, `/runs/{id}/next` (pure, so it answers without touching anything),
  `/runs/{id}/approve`.
- **CLI**: `open-refinery pipelines list|show|check|save` and
  `runs list|start|show|next|approve`. `pipelines check` prints the stage graph
  **before you pay for a run**, which is what the machine being pure buys.

### Notes
- `ship-a-ticket` ships as the default to build from. Its shape carries three
  decisions: deciding and building are separate turns on different models, a
  check may run and may not repair, and nothing merges itself.
- **You cannot approve your own run** — the gate is a second pair of eyes or it
  is nothing.

619 tests pass (130 new), and the surface is verified end to end against a
running server.

## [2.16.0] — 2026-09-27

*Phase P on the [road to 3.0](docs/PLAN-3.0.md): authorization is derived from
permissions held on the person, never from a role name.*

### Changed
- **Permissions moved onto the user.** A user carries a set, and **that set is
  the only thing ever checked** — no indirection, so two people doing similar
  jobs can differ without anybody inventing a role. Twelve permissions:
  `approve:<layer>` · `propose:<layer>` · `run:factory` · `manage:users` ·
  `read:audit` · `see:operations`, over four layers (`code` · `harness` ·
  `factory` · `charter`).
- **Roles became presets** — named starting points (`developer` · `lead` ·
  `platform` · `admin` · `auditor`) copied onto a user at creation and never
  read again. Editing a preset does not change anyone who already exists; the
  API and the tests say so plainly rather than letting people assume otherwise.
- `lead` owns the harness, `platform` owns the factory, and **`admin` approves
  nothing** — the account that grants access is not the account that approves
  what ships.
- Guards are pure functions of the caller's set: no session, no lookup, and
  nothing a stale row can fool.

### Removed
- **A second authorization system.** A regex table in `web.py` matched paths to
  role *names* and ran as middleware **on top of** the per-route dependencies.
  Two sources of truth that could disagree — and did, the moment permissions
  moved: a grant took effect in `/me` and was still refused by the middleware.
  Deleted, with every route it covered given an explicit permission guard.

### Added
- `POST /users` adds a person and sets their permissions in one call.
  `GET|PUT /users/{id}/permissions` edits them afterwards.
  `PUT|DELETE /presets/{name}` defines your own starting points.
  `GET /permissions` lists the vocabulary, each with a line saying what it means.
  `GET /permissions/approvers/{layer}` answers "who do I ask" with **people**.
- A refusal names who can actually sign it: *"you do not hold approve:factory —
  ask platform@example.com"*.

### Fixed
- **You cannot change your own permissions.** Holding `manage:users` lets you
  set other people's and is not a back door to holding everything else.
- **`/events` requires `read:audit`.** It was open-but-scoped, relying on the
  deleted middleware for its refusal — and "everyone can read the parts about
  themselves" is the wrong default for an audit log.
- **Preset ranks are declared, not derived from dict order**, which had put
  `auditor` (read-only) *above* `admin` in approval chains.

### Fixed (regression from 2.15.0)
- **Proposals, approval workflows, packs and standards had no routes.** The
  system review removed the governance *landscape* view, and those four shared
  its router. Nothing failed, because each is tested by driving its module
  directly — so the suite proved the code worked while the product had no way
  to reach it. Proposals are one of the four pillars, so this was a regression
  rather than a trim. All restored, with the new permission guards (enabling a
  pack is now `approve:charter`, since a pack seeds standards the harness
  reads).
- **`tests/test_route_coverage.py`** closes the gap: one assertion per pillar
  capability that it is reachable, plus the inverse — that a removed feature
  leaves no dead route behind, which would accept a request and do something
  unexpected.

Migration **v25**, which backfills every existing user from the preset they were
created with, so an upgrade changes nobody's access. **491 tests pass.**

## [2.15.0] — 2026-09-27

*Phase R on the [road to 3.0](docs/PLAN-3.0.md): the system review (§12) applied.
**2,110 lines net removed** — 2,902 deleted, 792 added.*

The review measured every feature against the four pillars — a software factory,
a harness, a queue of workers, and the business features (audit, observation,
proposals). An import graph showed nothing orphaned, so the problem was never
dead code: it was surface built during the 2.x governance track for a product
that still cannot open a pull request.

### Removed
- **`factory.py` + `authz.py`** — the original 0.1.0 demo core, a recipe
  registry with an `Authorizer` protocol. Nothing in the product imported it:
  only `cli demo` and two test files. It also occupied the name the real factory
  needs. (`web.py:_match_authz_rule` is unrelated despite the name.)
- **SCIM** — IdP provisioning whose partner, OIDC SSO, went in 2.14.0. SCIM
  without SSO provisions accounts for a login flow that no longer exists.
- **Access recertification** — a compliance-maturity feature for an org that has
  not shipped one agent-written line.
- **Systems** — grouping repos into "services" for a coverage rollup the factory
  never reads.
- **Invitations** — superseded: an admin adds a user and attaches permissions.
- **Repo coverage / `Claim` rows** — "does this repo's prose match its
  enforcement" is the **ladder's** question, answered at a rung.
- **Rollback** — once a run produces a pull request, rolling back is `git revert`
  and another run.
- **The governance landscape view** — duplicated by `/roles`, `/policies` and
  the canvas.

### Changed
- **`debt` + `analysis` + `anomalies` + `postmortem` → `improve.py`** (451 → 171
  lines). Four modules each reading the audit trail for a slice, disagreeing
  about vocabulary. Now one lane with two rules: **every finding names the
  events it came from**, and **an untraceable finding is dropped rather than
  repaired** — a lane that always finds three things is one nobody believes by
  the third time. `GET /improve` and `/improve/proposals`; nothing is applied.
- **One health score, not three.** The per-area split let a team celebrate a
  good `charter` score while the factory refused every run.
- **`ingest` is repurposed.** It read a repo's agent config into coverage scores
  nobody acted on; it now returns the **charter** for the harness to be handed
  (deepagents `memory=` / `skills=`).
  - The default is **`.agents/` and `AGENTS.md`** — tool-neutral, because the
    charter belongs to the repository rather than to whichever agent reads it.
  - **Any agent is supported**: `Repository.charter_paths` overrides the
    default, and `AGENT_PRESETS` (claude · cursor · copilot · windsurf · aider ·
    cline · gemini) makes that a pick rather than research. An override
    **replaces** the default rather than adding to it — a team that says where
    their charter lives means there, not there plus a guess. Migration **v24**.

### Shape
74 modules → **60**. 129 routes → **91**. 423 tests pass.

## [2.14.5] — 2026-09-27

*Phase 1.5 on the [road to 3.0](docs/PLAN-3.0.md): authority becomes data, and
roles become definable.*

### Changed
- **Authority is no longer a rank ladder.** `developer < platform < admin`
  compared with `at_least()` meant admin could do everything platform could —
  convenient, and not a separation of duties. A role now carries explicit
  powers on its row (`authority.py`), and **`admin` approves nothing**: it
  manages users and reads audit, so a compromised admin account can create
  users and read the log but cannot merge a change or weaken a rule.
- **A `lead` role**, because the product is both a harness and a factory and
  each needs an owner. Lead approves `harness` and `charter` (phases, prompts,
  tool grants, the standards turns read); platform approves `factory` (the
  stage graph, delivery, routing, quotas). A lead changing a prompt does not
  need platform, and platform changing a route does not need a lead.
- **`auditor` gains a role row.** It existed as a bare string `current_user`
  returned for a time-boxed grant; a row makes it checkable and visible in
  `/roles`.
- **Route guards ask what a role may *do*.** Every `require("platform","admin")`
  literal is gone, replaced by `manages_users` / `reads_audit` /
  `sees_operations` / `approves(layer)`. A team that defines `reviewer`, or
  splits platform in two, gets working routes with no code change.
- **`owner_scope` keys on `sees_operations`**, so admin no longer sees
  everyone's repos, work items, targets or routes.

### Added
- **Roles are definable.** `PUT /roles/{name}` and `DELETE /roles/{name}`
  (user management), `GET /roles/layers` for the editor, and
  `open-refinery roles list|layers|set|rm`. The built-ins are a **standard
  configuration, not a limit**.
  - **You cannot edit the role you hold** — otherwise granting yourself more
    authority is a single PUT away.
  - Built-ins cannot be changed or deleted; a role still assigned to someone
    cannot be deleted; an unknown layer is rejected; every change is audited.
  - Omitted powers are left alone, so setting a rank does not silently clear
    what a role may approve.

### Fixed
- **The approval gate could be satisfied by anyone.** `role_rank()` returns 0
  for a role that does not exist, so `at_least(developer, "senior")` was
  **True** — and migration v2 set exactly `'senior'` as every process's default
  `min_approver_role`, a role nothing ever seeded. Any process left on that
  default had **no effective approval minimum**. `at_least` now fails closed,
  `authority.*` fails closed on unknown role *and* unknown layer, and migration
  **v23** repairs the rows carrying the dead default.
- **`/events` would have locked admin out of the audit trail.** It scoped with
  `owner_scope`, which is now operations-keyed. Added `audit_scope()` — the two
  answer different questions, and sharing one helper hid that.

## [2.14.0] — 2026-09-27

*Phase 1 on the [road to 3.0](docs/PLAN-3.0.md): every service is reached with a
key or a token, and no authorization-code flow remains anywhere in the product.*

### Added
- **One credential surface.** `credentials.py` is the catalog for every
  connectable service across three families — **model** (Anthropic, OpenAI,
  Ollama), **forge** (GitHub, GitLab, local) and **tracker** (GitHub Issues,
  Jira, Linear). Each entry declares the fields to ask for, **where to mint the
  key**, and **exactly what permissions it needs**, so the Connections screen can
  answer "what do I paste here" without the reader leaving to search.
- **Credentials are personal.** A run uses the runner's own key, so a pull
  request is authored by the person accountable for it and cost attributes to a
  real actor. `for_actor()` resolves the actor's own credential, then an
  org-wide one *only* for providers marked shareable, then raises `NoCredential`
  — never a silent fallback to someone else's key, which would attribute one
  person's work to another in the audit trail.
- **Model keys may be shared; forge and tracker tokens may not.** A model key is
  a billing relationship, an access token is an identity. Publishing an org-wide
  key is platform's call, not admin's.
- **Verified before stored.** Nothing is saved that does not authenticate, and a
  provider's own refusal is surfaced verbatim (`github rejected the credential:
  HTTP Error 401`). `verify` re-checks a stored key — a credential revoked
  upstream is otherwise invisible until something tries to use it. `rotate`
  replaces the secret in place, keeping the id so nothing referencing it breaks,
  and refuses a replacement that does not authenticate.
- Routes: `GET /credentials/catalog`, `POST|GET /credentials`,
  `POST /credentials/{id}/verify`, `PUT /credentials/{id}`,
  `DELETE /credentials/{id}`. Connect, rotate and revoke are all audited.
- **`open-refinery credentials`** — `catalog · list · add · verify · rotate · rm`.
- **`client.py`** — the CLI's HTTP client. Application commands go **through the
  API**, never around it: the backend is the governance boundary, and a command
  writing to SQLite directly would bypass RBAC, policy, quota and the audit
  trail. Server maintenance (`init`, `migrate`, `serve`, `doctor`, `config`,
  `create-admin`, `seed`) stays on the database, because it runs on the box.

### Removed
- **Every authorization-code flow.** `oauth.py` and `oidc.py`, GitHub OAuth
  login, `/auth/sso/*`, `/integrations/{kind}/oauth/*`,
  `/targets/{id}/oauth/*`, `deps.provider_creds`, the `ConnectState` model, and
  the `GITHUB_CLIENT_ID` / `GITLAB_CLIENT_ID` environment fallbacks — which were
  product configuration wearing a server variable's clothes.
- `GET /auth/providers` now reports `{"password": true, "mfa": true}`. Humans
  sign in with email + password + optional TOTP; machines with API tokens;
  services with keys and PATs.

### Developer experience
- **`make setup`** — one command from a clean clone to a signed-in local
  environment: generates `.env` (mode 600) if absent, then seeds. **`make reseed`**
  drops `devtest.db` and seeds again, because `seed` requires an empty database
  and there was no way back.
- **The seed prints passwords, not just API tokens.** It created users with
  passwords and printed only tokens, so signing in to the dashboard it had just
  seeded meant reading the source.
- **The seed ships a model target and a route**, with no credential — the
  executor falls back to its echo stub, so `POST /execute` works on a fresh
  clone with no network and no API key. Adding a real key makes the same path
  live.

### Fixed
- **A developer could not see the process their own work items sit on.**
  `GET /processes` was owner-scoped, so a board owned by platform was invisible
  to the developer holding work on it — they could own an item and not see the
  stages it moves between. A process is a shared workflow definition, not
  personal property: reading is open to any authenticated user, authoring stays
  platform-gated.

### Changed
- `Integration` becomes the single credential store for all three families, with
  `last_verified_at`, `status`, `status_detail` and `shared` (migration **v22**,
  with its reverse).
- Reading another person's connections is **admin's** (oversight, metadata only);
  publishing an org-wide model key is **platform's** (operations). First use of
  the authority model in §2.5 of the plan — the full refactor is Phase 1.5.

## [2.13.0] — 2026-09-27

*Phase 0 on the [road to 3.0](docs/PLAN-3.0.md): a clean clone installs, tests
and serves without a detour.*

### Added
- **`open-refinery init`** — first run in one command: generates a `SECRET_KEY`,
  writes `.env` at mode 600, creates the database and applies migrations, then
  prints the two lines needed to start. Refuses to clobber an existing env file
  without `--force`, because overwriting it rotates `SECRET_KEY` and makes every
  stored service token permanently unreadable.
- **`open-refinery doctor`** — what is missing or broken, in the order a person
  debugs in: secret key, database, admin user, audit chain, git, model SDKs,
  targets, connections, dashboard. Every non-passing check carries a **remedy**,
  not just a diagnosis. Exits non-zero on a failure, so it works in CI.
- **`open-refinery config`** — every effective setting **tagged with the source
  that produced it** (built-in default / environment / database), so a default is
  never a magic number to go hunting for. `--all` includes unset keys, `-v`
  explains each. Secrets report `(set)` and are never printed.
- **`config.py`** — the settings catalog: the one place a setting is declared,
  covering the six environment variables and seven database-backed keys the app
  actually reads.
- **`doctor.py`** — the checks, as pure functions of a session and an
  environment, so the whole report is testable without a server.

### Security
- **The audit chain is now tamper-*resistant*, not just tamper-evident.** Two of
  four attacks passed silently before this release; both are now regression
  tests (`tests/test_audit_tamper.py`, written failing first).
  - **Forged event + recomputed chain — was undetected.** `entry_hash` was an
    unkeyed `sha256`, so anyone with database write access could rewrite who did
    what, recompute every link and the head, and pass `verify_chain`. Links are
    now `HMAC-SHA256` under a key derived from `SECRET_KEY`, which lives in the
    environment and never in the store.
  - **Deleting the oldest events — was undetected.** A deleted prefix was read as
    a legitimate retention purge and verified clean. `purge_events` now writes a
    **signed `AuditCheckpoint`** naming what it removed and where the surviving
    chain restarts; `verify_chain` refuses any gap no valid checkpoint accounts
    for, and a forged checkpoint fails its signature.
  - **Algorithm downgrade.** Relabelling rows as the legacy unkeyed construction
    is the one recomputation an attacker without the key *can* do. The chain head
    is now authenticated (`AuditChainState.signature`), so a wholesale rewrite
    produces a head they cannot sign.
  - **The signed export covered only the head** — so an attacker who rewrote
    history could export their forged head with a signature over it that verified
    perfectly. It now covers **every exported event**, and `verify_export()` is
    the auditor's side of that check.
  - **Key separation.** `SECRET_KEY` had three jobs (Fernet encryption, chain
    integrity, export signing). Each now gets a derived subkey by domain, so a
    leak of one does not compromise the others.
  - Pre-2.13 unkeyed rows still verify, so upgrades do not read as tampering.
    Migrations **v20** (`events.chain_algo`) and **v21** (`audit_chain_state.algo`,
    `.signature`), both with reverses in `DOWNGRADES`.
  - **What this still cannot stop**, stated plainly: someone holding `SECRET_KEY`,
    and someone deleting the database outright. Off-box mirroring answers the
    second and is on the 3.0 roadmap; nothing local answers the first. A rotated
    `SECRET_KEY` is indistinguishable from tampering — `doctor` says so.

### Fixed
- **A clean clone could not be installed.** The wheel force-includes
  `src/open_refinery/static`, which only existed after `make ui`, so `uv sync`
  failed with `Forced include not found`. The directory is now tracked via a
  `.gitkeep`.
- **`make test` failed on a clean clone.** 15 tests need `SECRET_KEY` and
  nothing set one; the failure read as a broken checkout rather than a missing
  export. A root `conftest.py` now sets a fixed test key.
- **`LOG_LEVEL` was documented but never read.** `.env.example` has advertised it
  since 0.3.0; `serve` now passes it to uvicorn. `HOST` and `PORT` resolve
  through the same catalog, so all three agree with what `config` reports.

## [2.12.1] — 2026-07-08

### Fixed
- `POST /recert/campaigns` returned an empty body — the campaign object was
  expired by the subsequent items-commit, so it serialized to `{}` (the campaign
  was created correctly; only the response was empty). Refresh before returning;
  added a route-level regression test. (The dashboard was unaffected — it reloads
  the list rather than reading the create response.)

## [2.12.0] — 2026-07-08

### Added
- **Access recertification campaigns (governance-maturity Phase 3.3 — completes
  Phase 3).** Periodic "re-attest who has access" reviews tracked to completion.
  - `new recert.py` + `routers/recert.py` + `RecertCampaign`/`RecertItem` tables
    (new tables — no migration). Opening a campaign snapshots every **active**
    user into a pending review item (email/role snapshotted).
  - A reviewer **certifies** (keep) or **revokes** (immediately deactivates the
    user via `users.active`) each item; the campaign auto-**closes** when nothing
    is pending. Every decision is audited (`recert-decision`).
  - **Overdue** open campaigns are flagged by the scheduler sweep — a deduped
    `recert-overdue` audit event (routable via 2.1).
  - Routes: `POST /recert/campaigns`, `GET /recert/campaigns[/{id}]`,
    `POST /recert/items/{id}/decide` (platform/admin author; oversight reads).
    UI: an **Access recertification** view (open campaigns, review, certify/revoke).

## [2.11.0] — 2026-07-08

### Added
- **SCIM 2.0 provisioning + group→role mapping (governance-maturity Phase 3.2).**
  The IdP provisions, updates, and deprovisions accounts automatically.
  - `new scim.py` + `routers/scim.py` — SCIM Users subset at `/scim/v2/Users`
    (create / list+filter / get / PUT+PATCH / DELETE), authenticated with a
    dedicated **provisioning token** (hash in settings, never a user token).
  - **Group → role mapping**: an IdP group maps to developer/platform/admin; the
    **most-privileged** mapped group wins, else a configurable default.
  - **Deprovisioning soft-deactivates** (`active=false`) instead of deleting —
    audit history is preserved and owner/actor references stay valid. Inactive
    users can no longer authenticate (password, token, or session).
  - Admin config: `GET /scim/config`, `POST /scim/token` (rotate, shown once),
    `POST /scim/group-map`; a **SCIM provisioning** card in Settings.

### Migrations
- v19: `users.active`. Additive; reversible.

## [2.10.0] — 2026-07-08

### Added
- **TOTP MFA for local accounts (governance-maturity Phase 3.1, part 2 — completes
  3.1).** Time-based one-time passwords (RFC 6238), **stdlib-only** (`hmac`), for
  local password logins; SSO logins inherit MFA from the IdP.
  - `new totp.py` (generate/verify ±1-step skew, constant-time compare, otpauth
    URI) + `mfa.py` (enroll → confirm → disable → login check). The TOTP secret is
    **encrypted at rest** and returned in the clear only once, at enrollment.
  - Routes: `GET /auth/mfa/status`, `POST /auth/mfa/enroll|confirm|disable`;
    `POST /auth/login` now returns `401 mfa_required` until a valid code is given.
  - UI: login prompts for the authenticator code on challenge; a "Two-factor
    authentication" card on the Overview (enroll / confirm / disable).
- **Hardening:** `POST /auth/login` now returns the user through the same
  safe projection as `/me` (`id/email/role/team_id/created_at`) — no hashes or
  the TOTP secret cross the wire.

### Migrations
- v18: `users.totp_secret` (encrypted), `users.mfa_enabled`. Additive; reversible.

## [2.9.0] — 2026-07-08

### Added
- **OIDC single sign-on (governance-maturity Phase 3.1, part 1).** Log in via the
  org's IdP (Okta, Entra, Google, Auth0…) — standards-only, **stdlib-only** (no
  SAML/crypto deps): OIDC discovery → authorization-code flow → the UserInfo
  endpoint for the verified email, matched to an **existing** user (the IdP is the
  auth + MFA authority; provisioning/group-mapping is Phase 3.2).
  - `new src/open_refinery/oidc.py` (discover / authorize_url / exchange_code /
    userinfo_email). Config in **encrypted settings** (`oidc.*`), secret write-only.
  - Routes: `GET/POST /auth/sso/config` (admin), `GET /auth/sso/login`,
    `GET /auth/sso/callback` (CSRF via a state cookie); `/auth/providers` now
    reports `sso` + `sso_name`.
  - UI: "Sign in with <IdP>" on the login screen; an admin **Single sign-on
    (OIDC)** card in Settings (self-hides for non-admins).
- MFA (TOTP for local accounts) follows in the next release to complete 3.1.

## [2.8.0] — 2026-07-08

### Added
- **Behavioral anomaly detection (governance-maturity Phase 2.3 — completes
  Phase 2).** `anomalies.scan` runs cheap, dependency-free heuristics over the
  audit trail and returns structured findings:
  - **denial-spike** — a burst of policy denials in the last hour;
  - **mass-change** — one actor making many mutations in a 15-minute window;
  - **off-hours-agent** — a harness identity active during off-hours (UTC night);
  - **harness-over-norm** — an agent running far above the agent-median volume.
  - `GET /anomalies` (oversight) feeds a "Behavioral anomalies" card + panel on
    the Overview. The scheduler sweep emits an `anomaly` audit event for each new
    high-severity finding (deduped off the append-only audit via the event
    `subject`), so notification rules (2.1) can route it. `anomaly` is a
    selectable notification trigger. Detection is a signal, never a block.

## [2.7.1] — 2026-07-07

### Changed
- **`web.py` decomposed into `routers/` + `deps.py` (internal refactor, no API
  change).** The 820-line `create_app` brain method (cyclomatic complexity 80)
  was split: shared FastAPI dependencies moved to `deps.py` (engine now comes
  from `request.app.state.engine`, so they're module-level), and the ~140 route
  handlers moved into nine cohesive `routers/*.py` modules (`core`, `ops`,
  `systems`, `governance`, `org`, `harness`, `workitem`, `routing`, `policy`),
  each an `APIRouter` included by a slim `create_app`. Route paths, auth, and
  behavior are unchanged (all 297 tests pass).
- CodeScene Code Health: `web.py` 5.1 → **10.0**; every new module scores 10.0
  except `routers/routing.py` at 9.68 (two OAuth callbacks legitimately take two
  URL path params + request + session). No health regression anywhere.

## [2.7.0] — 2026-07-07

### Added
- **Approval SLAs + escalation + segregation of duties (governance-maturity
  Phase 2.2).**
  - A process carries an **approval SLA** (`approval_sla_hours`, 0 = none). Each
    approval request derives a `due_at` deadline at request time.
  - An overdue pending request is **escalated once**: an `approval-overdue` audit
    event (hash-chained, and routable by a notification rule) plus a dedup stamp.
    The escalation sweep runs on the serve-path scheduler alongside ingest.
    `GET /approvals/overdue` lists the current overdue queue.
  - **Segregation of duties** — the requester may not approve their own request
    (in addition to the existing "one signature per chain" rule).
- UI: process form takes an "Approval SLA (hours)" field (badge on the card);
  `approval-overdue` is a selectable notification trigger.

### Migrations
- v17: `processes.approval_sla_hours`, `approval_requests.due_at` (indexed),
  `approval_requests.escalated_at`. Additive; reverse in `DOWNGRADES`.

## [2.6.0] — 2026-07-07

### Added
- **Governance notifications (governance-maturity Phase 2.1).** Rules match an
  audit event recipe (blank = any) and send a message to a channel — **Slack**
  (incoming webhook), **email** (the pluggable email port), or a plain **webhook**.
  Dispatched best-effort on every audit write (a broken channel never blocks the
  governed action). `GET/POST/DELETE /notification-rules`; a Notifications card in
  Settings (e.g. "denials → #security"). Adds Slack as a notify sink.
- **Policy changes are now audited** — create/delete emit a `policy-change` audit
  event, so they're hash-chained, appear in evidence, and can trigger alerts.

### Notes
- `notification_rules` is a new table (create_all) — no schema migration.

## [2.5.0] — 2026-07-07

### Added
- **Compliance evidence packs (governance-maturity Phase 1.3).** `GET
  /evidence?framework=<soc2|iso27001|hipaa|gdpr>` produces a framework-mapped
  bundle drawn from the tamper-evident audit chain, the role authorization
  matrix, versioned policy history + approval workflows, and attestations — each
  control marked met / partial / attention with a coverage %. Downloadable;
  ties to the chain's integrity result. UI: an Evidence tab (Insights).
- **Time-boxed auditor access.** Admins mint a read-only **auditor grant**
  (`POST/GET/DELETE /auditor-grants`, expiring token). Used as a bearer token it
  resolves to an `auditor` principal that can read evidence + the audit trail
  and **mutate nothing** (blocked by the authorization matrix); it expires on its
  own. Auditors sign in with the code on the login screen. This completes
  governance-maturity **Phase 1** (provable governance).

### Notes
- `auditor_grants` is a new table (create_all) — no schema migration.

## [2.4.0] — 2026-07-07

### Added
- **Versioned policy history (governance-maturity Phase 1.2).** Every policy
  create/delete is recorded as an immutable `PolicyVersion` — a full snapshot plus
  who/when/why. `GET /policies/history` (optionally per policy) returns the change
  log; `GET /policies/at?t=<ISO>` reconstructs the exact rule set **in effect at a
  point in time** (answers auditors' "what control existed when X happened?").
  Policy create now takes an optional `note`; delete records the actor + note.
  UI: a History drawer on Policies with a point-in-time picker + change log
  (each entry rendered as a rule sentence).

### Notes
- `policy_versions` is a new table (create_all) — no schema migration. Pack- and
  proposal-created policies are versioned automatically.

## [2.3.0] — 2026-07-07

### Added
- **Tamper-evident audit (governance-maturity Phase 1.1).** Every audit event is
  hash-chained to the previous (`entry_hash = sha256(prev_hash + canonical
  fields)`). `GET /audit/verify` recomputes the chain and flags any edit,
  insertion, or mid-chain deletion. `GET /audit/export` returns a portable,
  **signed** record (HMAC-SHA256 over the chain head with `SECRET_KEY`) an auditor
  can verify independently. Upgrades backfill the chain over existing events.
  UI: a "Verify trail" seal on the Audit log.
- **CSV audit export** — `GET /audit/export.csv` (filter by actor / recipe /
  subject / date), with the chain hashes included so the sheet stays
  tamper-evident. Export CSV / Export signed buttons on the Audit log.
- **More concept visuals** — approval chains (Proposals + Approvals queue) and
  work-item stage history now render as **pipelines** (current step lit), joining
  the process pipeline + governance layer lattice.

### Migration
- **v16** — `events.prev_hash` / `events.entry_hash` (indexed) + new
  `audit_chain_state` table. Reversible downgrade appended.

## [2.2.0] — 2026-07-06

**Role authorization model.** Each role is now restricted to its concerns, enforced
backend (403) and in the UI.

### Changed
- **Roles are scoped to responsibilities:**
  - **developer** — operates their own dev chain (services, repos, processes,
    agents, work, approvals) + their own insights (metrics, coverage).
  - **platform** — platform concerns (systems, targets, teams), governance
    authoring (policies, proposals), packs, and full org insights; approves gated
    moves. Does not operate dev work.
  - **admin** — **oversight only**: reporting/insights (metrics, usage, traffic,
    audits, experiments, audit log), governance landscape, and user
    administration (invitations, settings). No longer operates the factory.
  - Reads of operational data stay open for oversight (owner-scoped for
    developers); only mutations and oversight/config surfaces are role-gated.
- **Central authorization matrix** (`_AUTHZ_RULES` + middleware) — one place
  declares who may do what; every request is checked (403 out of scope). The UI
  mirrors it per-view and bounces off any disallowed view.
- **Invite your own level or lower** (was strictly lower) — a developer can invite
  a developer; platform can invite platform or developer; admin anyone.

### Notes
- **Behavior change:** an admin can no longer create repos / move work / configure
  platform targets — those are developer/platform actions now. Admin is the
  oversight/administration role. (Single-tenant; adjust role assignments if you
  relied on admin operating directly.)
- Work still only advances through its process's defined transitions + gates
  (no ad-hoc stage changes); rollbacks remain governed.

## [2.1.1] — 2026-07-06

### Changed
- **App flow ordered by entity dependency.** The nav (and the content order it
  mirrors) now runs services → repos → processes → harnesses → work → approvals —
  the order you actually build things in. The onboarding wizard follows the same
  flow.
- **Services available to everyone who needs them.** Integrations moved out of the
  platform-only group into the main flow as **"Services"** (ungated, owner-scoped)
  so platform *and* developers can connect the code hosts / trackers they use.
  The page is titled "Services" to match its nav label.
- **Admin onboarding invites the team.** The setup wizard gains an admin-only
  **Invite** step (platform/developer teammates who inherit the configured org).
- **Menu and content share one standard** — `TabsContent` render order matches the
  sidebar exactly, grouped and entity-ordered.

### Removed
- **Arbitrary configurable roles.** Roles are a fixed three-tier ladder
  (developer / platform / admin); the create/delete-role API is no longer exposed
  (arbitrary roles proved confusing). `GET /roles` remains for form dropdowns.

## [2.1.0] — 2026-07-06

A large UX + onboarding + agent-auth release.

### Added
- **Harness identities — auth for coding agents (Claude Code first).** A harness
  is a role-scoped **service-account** owned by a person; its token authenticates
  the agent's CLI to the platform, and every call it makes is governed by its
  role under the current enforcement mode (the proactive controls apply to agents
  exactly as to people). Two paths:
  - **OAuth device flow** (preferred, RFC 8628): agent starts a request → shows a
    code → a human approves it in the UI → agent polls for the token. Endpoints
    `POST /agent/device/{start,token,approve}`; token returned once.
  - **Minted token** (fallback): register → `OPEN_REFINERY_URL`/`OPEN_REFINERY_TOKEN`
    setup snippet. `GET/POST/DELETE /harnesses`, `POST /harnesses/{id}/rotate`,
    `GET /harnesses/catalog`. Catalog: Claude Code + LangGraph/Cursor/Aider/Codex.
- **GitHub Issues connector + workflow discovery.** A connector catalog
  (`GET /connectors`) with capabilities (source/tracker/workflow); GitHub Issues
  joins Jira/Linear as trackers. `GET /integrations/{id}/workflow` returns the
  tool's own columns/statuses — so a process is shaped from *your* board.
- **First-run setup wizard.** The first admin goes connect → import repo → enable
  a pack → **create the first process from a tracker's columns** → ship a first
  item. `GET /onboarding` + `POST /onboarding/complete`; later users inherit.
- **OAuth-first connect** (`ConnectService`), shared by Integrations + onboarding:
  one-click OAuth when configured, token fallback under "use a token instead".

### Changed
- **Left icon sidebar** replaces the two-level top nav (Lucide icons, collapsible,
  role-filtered) — snappier SPA feel.
- **Role-aware surfaces.** Developers get a trimmed, work-focused nav + a
  read-only **"My rules"** view (what governs them, not authoring); platform/admin
  see the full surface. Everyone lands on the visibility-first Overview.
- **Concept visuals.** Processes render as a **pipeline diagram** (gated stages
  locked, current stage lit, feedback loops noted); the Governance tab shows a
  **layer lattice** (factory ↓ harness ↓ charter); Overview cards gain icons;
  Metrics labels are humanized and actor IDs resolve to emails.
- **Brand.** New process-graph logo mark ("a dark factory with the lights on"),
  redesigned login, `favicon.svg` + `.png` + `.ico` + apple-touch; README + gh-pages
  branding refreshed.

### Migration
- **v15** — `users.kind` / `harness_kind` / `owner_id` (agent service accounts).
  `device_grants` is a new table (create_all). Reversible downgrade appended.
  `make seed` now marks seeded orgs onboarded (and sources `.env`).

## [2.0.2] — 2026-07-06

### Added
- **16 new packs** for broader canon coverage (catalog 15 → 31), including the
  requested **security** and **compliance**:
  - developer: secure-coding, api-design, refactoring, performance, accessibility,
    data-engineering, prompt-engineering
  - platform: containers, iac, secrets-management, incident-response (ships an
    Incident process), cost-optimization, release-management
  - admin: compliance-frameworks (ships a control-mapper agent), risk-management,
    data-privacy
- **Pack detail view** — `GET /packs/{key}` returns a pack's standards / example
  processes / governed artifacts; each marketplace card has a **View details**
  link that opens a drawer previewing what enabling it seeds.

### Changed
- **UI consistency pass across every tab.** All input-bearing forms now use a
  labeled-field layout with plain-language intros, sensible empty states, and
  guarded submit buttons — Work, Repos, Processes, Policies, Proposals, Packs,
  Governance, Systems, Integrations, Targets, Teams, Coverage, Experiments,
  Events, Invitations, Settings.
- **Governance reads as statements.** Policies, Proposals, and the Governance
  landscape render rules as plain sentences (via a shared `ruleSentence`), with a
  live preview while authoring. Proposal terminology clarified ("review tier
  (role)" vs a policy's artifact layer).
- **Packs use a modern on/off toggle** instead of enable/disable buttons.

### Fixed
- **`GET /me` / `GET /users` secret-field leak** — no longer return `pw_hash`,
  `pw_salt`, or `token_hash` (safe projection via `_public_user`).
- **`GET /health/areas` 500 (Audits tab)** — the `/health` route handler shadowed
  the imported `debt.health` scorer; renamed to `healthcheck`.
- **Proposed policy rules now carry `role` + `namespace`** through the approval
  applier, so an accepted proposal creates the same rule that was previewed.
- Two copy-paste empty-state strings corrected (Experiments, Invitations).

## [2.0.1] — 2026-07-06

### Security
- **`GET /me` no longer leaks secret fields.** It returned the raw `User` row,
  including `pw_hash`, `pw_salt`, and `token_hash`. `/me` (and `/users`) now
  return a safe projection (`id, email, role, team_id, created_at`) via a shared
  `_public_user` helper. Hashes and token hashes never cross the wire.

### Fixed
- **`GET /health/areas` 500 (the Audits tab).** The `/health` route handler was
  named `health`, shadowing the imported `debt.health` scorer, so the area-health
  call raised `TypeError`. Renamed the handler to `healthcheck` (path unchanged).

## [2.0.0] — 2026-07-06

**Feature-complete platform.** 2.0 is a milestone cut, not a breaking release —
the schema stays frozen at 1.0 and every 1.x release since has been additive and
backward-compatible, so upgrading from any 1.x is a drop-in `pip install -U`
(migrations run on `serve`). No API removals, no config changes.

### Road to 2.0 — what landed since 1.0
- **Rollbacks (1.10–1.13)** — first-class, governed revert to a prior stage with
  a full-deployment **reverse plan** (open category set: code, migrations, config,
  env, libraries, data, services, secret refs, infra, dns).
- **Enforcement v2 (1.14)** — pre-action `/authorize` gate (identity + intent
  before a tool/command/host-egress action) + per-namespace whitelists.
- **Teams + usage ledger + cost attribution + concurrency caps (1.15)**.
- **Routing policy inputs + traffic graph (1.16)** — region / compliance / cost
  route resolution; cross-agent traffic graph from the ledger.
- **Live logs + rollback apply-side (1.17)**.
- **UI/UX revamp round 2 (1.18)** — visibility-first Overview + Work board +
  right-hand detail/action drawer.

### Docs
- README + `docs/ARCHITECTURE.md` refreshed to cover the full 1.x surface
  (enforcement, rollbacks, teams/ledger/cost/concurrency, routing + traffic,
  jobs/scheduler/live/logs, the visibility-first dashboard).

### Deferred to 2.x
- Postgres (the engine still guards to SQLite), MFA, Celery/Redis scale-out,
  extending the drawer pattern to the remaining admin surfaces.

## [1.18.0] — 2026-07-06

### Changed
- **UI/UX revamp round 2 — visibility-first, workflow-oriented (M5 on the road to
  2.0).** The core loop moves off the CRUD wall:
  - **Overview home** (new default landing) — surfaces the few things needing
    attention as glanceable highlight cards (approvals awaiting, policy denials,
    failed invokes, rollbacks to apply, work in progress), the actionable ones
    accented; each card drills straight into its view. Plus a work-by-stage
    summary.
  - **Work board** — work items are shown as a board grouped by stage (not a
    table of action rows). Selecting a card opens a **right-hand detail drawer**
    with that item's stage, actions (move, approve, attest), history + rollback,
    live logs, and post-mortem — the secondary operations live in the drawer, not
    inline everywhere.
  - **Reusable `Drawer` slide-over** (overlay + Esc-to-close) as the detail/action
    surface pattern.
  - Broader Vitest coverage (Drawer open/close, Overview highlights + drill-in +
    empty state).

UI-only — no API or schema change. Admin/config tables are unchanged and remain
reachable; the revamp centers the workflow surface.

## [1.17.0] — 2026-07-06

### Added
- **Live run logs + rollback apply-side (M4 on the road to 2.0).**
  - **Live logs** — a per-work-item log tail streamed over the WS hub. A harness
    `POST /work-items/{id}/logs` (`{line, level}`); each line is fanned out live
    (WS `type: "log"`, keyed by the item) and kept in an in-process ring buffer
    (`GET …/logs` for recent lines). Ephemeral, same single-process ethos as the
    job runner / scheduler. Logs toggle per work item streams lines live.
  - **Rollback apply-side** — the harness reports whether it applied the reverse
    plan (it runs git/alembic/pip, not the platform): `POST
    /work-items/{id}/rollback/applied` (`{status: applied|failed, detail}`),
    recorded as a `rollback-applied` audit event and appended to the stage
    history — so the trail shows the outcome, not just the intent. Mark
    applied/failed buttons after a rollback.

## [1.16.0] — 2026-07-06

### Added
- **Routing policy inputs + traffic graph (M3 on the road to 2.0).**
  - **Routing policy inputs** — targets carry a `region`, `compliance` tags, and a
    per-unit `unit_cost`. An org-wide **routing policy** (`GET/PUT /routing-policy`,
    admin setting) filters route candidates that fail a required region /
    compliance tag and — with `prefer: "cost"` — orders survivors cheapest-first
    while priority stays dominant. A compliance/region requirement that no target
    meets yields no route (the call is blocked, not silently downgraded). Target
    form exposes region / compliance / cost; a routing-policy editor sits above
    the targets table.
  - **Traffic graph** — `GET /traffic` builds a cross-agent traffic graph from the
    usage ledger (the audit event digests the target away, so the ledger is the
    only wireable source): actor→target edges weighted by call count + units,
    actors tagged with their team. New Traffic tab.

### Migration
- **v14** — `targets.region` / `targets.compliance` / `targets.unit_cost`
  (additive, reversible downgrade appended).

## [1.15.0] — 2026-07-05

### Added
- **Teams, usage ledger, cost attribution + concurrency caps (M2 on the road to
  2.0).**
  - **Teams** — a user belongs to at most one `team` (`User.team_id`); teams are
    the unit of cost attribution and concurrency capping. `GET/POST/DELETE
    /teams`, `PUT /users/{id}/team`, and a `GET /users` (projected — never
    exposes password/token hashes). Teams tab + membership editor in the UI.
  - **Usage ledger** — every governed invoke appends a `LedgerEntry` (units,
    actor, team, target) so usage is queryable (the audit event digests units
    away). Cost attribution rolls up by team; `GET /usage`, Usage tab.
  - **Concurrency caps** — a team's `max_concurrency` (0 = unlimited) is enforced
    live at the invoke seam via an in-process in-flight counter; over the cap →
    `ConcurrencyExceeded` (`429`). Same single-process ethos as the job runner /
    scheduler (Redis-backed counter can replace it later, same `slot()` API).

### Migration
- **v13** — `users.team_id` (ALTER-added, indexed → the migration also creates
  the index). `teams` + `ledger_entries` are new tables (create_all). Reversible
  downgrade appended. `team_id` and the ledger columns are plain indexed columns,
  **not** DB foreign keys — an ALTER-added FK column can't be dropped by SQLite
  (would break the downgrade), and the ledger is an append-only historical log
  that must survive deletion of the team/target it references.

## [1.14.0] — 2026-07-05

### Added
- **Enforcement v2 (M1 on the road to 2.0).** The proactive gate now covers any
  action boundary, not just transitions and executor invokes:
  - **Pre-action authorize seam** — `POST /authorize` lets an out-of-process
    harness verify **identity + declared intent** against policy *before* it runs
    a **tool / command / host-egress** action (`{action, resource, namespace,
    intent}`). Permitted → `{"allowed": true, "mode": …}`; denied → `403`, and the
    refusal is audited (`denied` event) with the intent recorded.
  - **Per-namespace whitelists** — `decide`/`enforce` now honor a policy's
    `namespace`: a namespaced rule gates only requests in that namespace, a
    blank-namespace rule is global. Under strict/default-deny that gives a
    per-namespace whitelist (a set of namespaced `allow` rules). Policy form +
    table expose the namespace.

## [1.13.0] — 2026-07-05

### Added
- **Infrastructure + DNS rollback, and the reverse engine is now open-ended.**
  `infra` (restore prior infra state/version) and `dns` (restore prior record)
  join the change set. More importantly, `reverse_plan` no longer whitelists
  categories: `code` and `migrations` keep their bespoke reversals, and **every
  other `{name: {"old","new"}}` map is reversed generically** (restore each name
  to its first-seen `old`). Any deployment surface the harness reports — queues,
  CDN, certs, IAM, cron, or one not yet named — rolls back with no code change.
  The dashboard renders whatever categories a plan contains.

### Security
- The material-safety rule now spans **all** categories: `StageHistory.changes`
  is plaintext and digested into the audit trail, so every category carries
  *references* only (e.g. a secret's version/vault ref), never material.

## [1.12.0] — 2026-07-05

### Added
- **Rollback covers secret/credential rotations too.** A new `secrets` change-set
  category reverses a rotation by restoring the **prior credential reference**.
  **Security:** `secrets` `old`/`new` are references only — a credential version
  id, rotation id, or vault path — **never the secret material**. The change set
  is stored in `StageHistory.changes` and digested into the audit trail
  (plaintext), so material must never be placed there; the rollback plan restores
  the prior reference and the harness re-activates that credential version out of
  band. (Consistent with "only `SECRET_KEY` in env; everything else encrypted;
  secrets never returned by the API.")

## [1.11.0] — 2026-07-05

### Added
- **Rollback now covers env vars, data updates, and service vendor swaps too.**
  The transition change set gains three categories alongside code/migrations/
  config/libraries: `env` (environment variables — reverse restores the **prior
  value**), `data` (a data update — reverse restores the **prior snapshot**), and
  `services` (a service vendor swap — reverse restores the **prior vendor**). All
  invert the same way as config/libraries (restore each name to its pre-change
  value), so a reverse plan can now unwind the full deployment: code, DB
  migrations, config, env, dependencies, data, and services.

## [1.10.0] — 2026-07-05

### Added
- **Rollbacks as a first-class, governed feature.** Every work item now keeps an
  append-only `StageHistory`, so a work item can be reverted to a **known-good
  prior stage** — authorized (policy action `rollback`, honoring the enforcement
  mode and auditing refusals), recorded as a structured `rollback` audit event,
  and appended to the history.
- **Rollback reverses the whole change set, not just the stage.** A transition
  can carry the **PR's diff** categorized as `code` / `migrations` / `config` /
  `libraries`. A rollback computes a structured **reverse plan** across all of
  them — code revert-to-commit, DB **migration downgrades** (newest-first),
  config keys and library versions restored to their pre-change values — and
  returns it for the harness to apply (the platform governs the revert; it does
  not run git/alembic/pip itself). `POST /work-items/{id}/transition` accepts an
  optional `changes` manifest; `GET …/history` and `POST …/rollback` expose the
  trail and the plan.

### Note
- `StageHistory` is a brand-new table created by `create_all` on upgrade —
  additive, so no schema migration is required (the frozen-since-1.0 schema
  stays additive-only).

## [1.9.0] — 2026-07-05

### Added
- **Live UI via WebSockets.** A `/ws` channel (bearer token via query param)
  streams real-time updates — **background job** status changes and **new audit
  events** — so the dashboard reflects activity without polling. An in-process
  pub/sub **hub** fans events out from any thread (job runner, audit sink) via the
  server loop; the dashboard shows a **● live** indicator and toasts job
  completions. Adds the `websockets` dependency (WS transport for uvicorn).

### Note
- In-process hub (same ethos as the job runner / scheduler); a Redis/pub-sub
  backend can replace it for multi-process later, same `HUB.publish` API.

## [1.8.0] — 2026-07-05

### Added
- **Scheduled ingest.** A repo can auto-ingest on a cadence
  (`ingest_interval_hours`; 0 = manual). An in-process scheduler (daemon thread,
  started on `serve`) enqueues a **background ingest job** for each due repo and
  stamps `last_ingest_at`. `POST /repositories/{id}/schedule`; the Repos tab gains
  an **Auto-ingest (h)** field. Due-logic is pure/tested; the loop is thin, so a
  cron/Celery-beat backend can replace it later. Additive migration v12 (+ its
  downgrade). Built on the 1.7 job runner.

## [1.7.0] — 2026-07-05

### Added
- **Background job runner.** Long work can run **off the request path** to keep
  the UI responsive — an in-process, thread-based runner with **zero new
  dependencies** (the single `serve` process handles it). `enqueue` records a
  `Job`, returns immediately, and runs the work in a daemon thread with its own
  DB session; poll `GET /jobs/{id}` (or `GET /jobs`). Opt in per call:
  `POST /audits/run?background=true` and `POST /repositories/{id}/ingest?background=true`.
  New `jobs` table (additive). The runner is a **port** — a Celery/RQ backend can
  slot in later for horizontal scale without changing the `enqueue`/`get_job` API.

### Note
- In-process is the deliberate default (keeps deployment to one command). Scaling
  onto an external queue is opt-in, later. Unblocks scheduled ingest + a future
  WebSocket progress stream.

## [1.6.0] — 2026-07-05

### Added
- **Agent-run post-mortem.** `GET /work-items/{id}/postmortem` assembles a run's
  full trail — the audit timeline (transitions, invokes, **invoke-failures**,
  **policy denials**, approvals, attestations), latest attestation results,
  pending approvals, timings — then **deduces a likely root cause** (policy
  denial › target failure › failed attestation › rejected › stalled › clean) and
  **suggests concrete follow-ups** (review the blocking rule, check target
  creds/quota, fix the failing check, resubmit, close imitation surfaces, resolve
  poison). Heuristic over recorded facts. Dashboard: a **Post-mortem** toggle on
  each work item (root cause + findings + suggestions + timeline).

## [1.5.0] — 2026-07-05

### Added
- **Proactive enforcement layer.** Governance can now *restrain* actions, not
  just explain them after the fact:
  - **Whitelist / default-deny mode** — an admin setting `policy.enforcement`
    (`audit` default-allow, or `strict` whitelist). In `strict`, an action at a
    gate (work-item transition, executor invoke) proceeds **only if an explicit
    allow rule matches** — otherwise it's blocked. `decide` gained a
    `default_allow` flag; `enforcement_mode` resolves the setting.
  - **Every refused attempt is audited** — `enforce` writes a `denied` event
    (actor, action, resource, mode, reason) before raising, so refusals show in
    the Audit log in both modes (closing the prior gap where denials weren't
    recorded).
  - Governance landscape reports the active enforcement mode; Settings hints and
    a landscape badge surface it.

### Note
- This is the shift from *legible* automation (observe/audit) to *restrained*
  automation (block-before-act). Default stays `audit` — opt into `strict`.

## [1.4.1] — 2026-07-05

### Added
- **`open-refinery migrate`** — migrate the schema **up or down**. Up (default,
  or `--to N`) applies pending migrations; `--to N` below the current version
  **downgrades** to a pinned schema version (destructive — drops columns/data, so
  it requires `--yes`). Migrations still run automatically on `serve`; this gives
  an explicit, reversible way to move an existing install's database. Backed by a
  `DOWNGRADES` list (reverse of each migration) + `migrate_to`. README gains an
  **Upgrading** section.
- Migration **v11** — catch-up `CREATE INDEX IF NOT EXISTS` for the `pack`
  columns added by earlier `ALTER`s (upgraded installs missed those indexes,
  since `create_all` only builds indexes on new tables).

### Note
- **Standard practice, now documented:** every schema change ships a migration
  (new tables via `create_all`; columns via `ALTER`; ALTER-added indexed columns
  via `CREATE INDEX IF NOT EXISTS`). Covered by a 1.0-era → latest upgrade test.

## [1.4.0] — 2026-07-05

### Added
- **Ingest polish.** A **GitLab reader** (parity with GitHub — reads `.claude/`,
  `CLAUDE.md`/`AGENTS.md`, and code signals via the GitLab API). **Per-repo
  integration linking** — `Repository.integration_id` + `POST
  /repositories/{id}/integration` pick the exact source integration to ingest
  from (Repos tab source-picker); with no link, ingest falls back to the owner's
  first integration matching the repo's host. **Richer code signals** — CI
  (GitHub Actions / GitLab CI), Dockerfile, Makefile, docs dir, pre-commit.
  Readers are dispatched by integration kind. Additive migration v10.

## [1.3.0] — 2026-07-05

### Added
- **Systems — compose repositories into services.** A platform-level `System`
  groups repos (service / microservice group / server) and **rolls up their
  governance health**: average coverage score + total imitation surfaces across
  members. `GET/POST /systems`, `POST /systems/{id}/repos`,
  `GET /systems/{id}/coverage`, `DELETE /systems/{id}`. Dashboard **Systems** tab
  (Platform group) — pick member repos, roll up health. New `systems` table
  (additive; schema stays frozen).

## [1.2.0] — 2026-07-05

### Added
- **Governance layer graph.** Policies now carry an explicit **artifact layer** —
  `factory` > `harness` > `charter` (`Policy.layer`). Strict-override precedence
  resolves on the **lattice** of (author role rank, artifact layer): the role
  axis dominates, the artifact axis breaks ties. `decide`/`enforce`, the
  governance landscape's overrides, and the poison analysis (dead / contradiction)
  all resolve on the combined key. Pack-seeded artifacts are tagged with a layer
  (canon commands → `harness`, org agent → `factory`). Policies form + landscape
  show the layer. Additive migration v9 adds `policies.layer` (schema stays frozen).

## [1.1.0] — 2026-07-05

### Added
- **Packs bundle harness artifacts.** A pack can now seed governed **`Policy`
  artifacts** — rule / skill / command / agent — not just prose standards and
  processes. Seeded artifacts are **pack-tagged** (removed on disable) and
  **namespaced** (`Policy.namespace`, e.g. `canon/tdd`, `org`). Starter artifacts:
  a `tdd` command (tdd pack), a `review` command (code-review pack), and an org
  compliance-reviewer agent (org-policy pack). Additive migration v8 adds
  `policies.namespace` + `policies.pack` (schema stays frozen — additive only).

## [1.0.0] — 2026-07-03

**First stable release. Schema is frozen — post-1.0 changes are additive only.**

### Changed
- **Version 1.0.0**; package classifier is now Production/Stable.
- **Schema frozen** — the migration list is closed to restructures; future
  migrations add tables or nullable/default columns only (marker in
  `migrations.py`).

### Docs
- **docs/ARCHITECTURE.md** rewritten for the full platform — the transition loop,
  the executor pipeline, the governance stack, ports & adapters, data/config, and
  the embeddable library core.
- **README** status refreshed to the 1.0 feature set.

### The 1.0 surface (shipped across 0.1 → 0.13.x)
Admin-configurable roles · customizable processes (board/doctrine) with a
configurable oversight dial + quality-gate attestations · inline and async
chained approvals · policy governance (rule/skill/command/agent, strict override,
layered precedence) · per-layer approval workflows with auto-escalating
accept/deny/feedback · a curated pack marketplace (standards + processes) ·
targets/routing/windowed quotas with real Anthropic/OpenAI/MCP/API backends (API
key or OAuth) · content filtering · structured output · governance landscape +
poison/override analysis · repo coverage/drift + debt-audit health with GitHub
ingest · evals & experiments · webhooks · integrations (GitHub/GitLab/Jira/Linear)
· metrics · a complete attributed audit trail · a React/shadcn dashboard (grouped
nav, marketplace, empty states, Vitest) bundled in the wheel · self-hosted API
docs with live Try-it-out. Only `SECRET_KEY` in the environment; everything else
encrypted in the DB. `pip install open-refinery && open-refinery serve`.

## [0.13.22] — 2026-07-03

### Changed
- **Grouped navigation + progressive disclosure.** The ~17 tabs are now organized
  into groups — **Work · Governance · Platform · Insights · Admin** — with a group
  selector in the header; only the active group's tabs are shown (one group at a
  time). Empty/role-gated groups are hidden. **Admins land on Insights** (metrics
  first — their high-level view); everyone else lands on Work. Completes the core
  1.0 UI revamp (palette · marketplace · empty states · Vitest · grouped nav).

### Note
- Remaining for 1.0: full docs pass + **schema freeze**.

## [0.13.21] — 2026-07-03

### Added
- **Empty states** across the list tabs — repos, processes, targets, routes,
  quotas, policies, proposals, integrations, invitations, and the audit log now
  show a clear "nothing yet" row instead of a blank table (shared `EmptyRow`).
- **Frontend tests (Vitest)** — component tests with a **mocked API** covering
  empty / populated / role-gated states (EmptyRow + the Packs marketplace).
  `make ui-test` (or `bun run test` in `frontend/`). Test files are excluded from
  the production `tsc` build.

## [0.13.20] — 2026-07-03

### Changed
- **UI revamp (part 1).** New **palette** — purple primary, yellow highlight,
  green success, red failure/blocking (replaces blue/green/purple/orange).
  **Pack marketplace** — the Packs page is now a browsable card grid grouped by
  layer, with enable/disable and an enabled count. **Decluttered tab nav** —
  tabs regrouped (Work · Governance · Platform · Insights · People/Config) and
  the audit-trail tab relabeled **Audit log** (distinct from **Audits**).

### Note
- UI revamp continues: grouped-nav labels / progressive disclosure, graceful
  empty states, and **Vitest** component tests (mocked API) are the remaining
  1.0 UI work.

## [0.13.19] — 2026-07-03

### Changed
- **`seed` is now minimal** — three role users, one repo, one board process, two
  work items: enough to sign in and see the app working. A fresh production
  install still seeds nothing and goes to the setup wizard / `create-admin`.

### Added
- **Packs seed example processes** — enabling a pack can create process
  templates (removed on disable). The **workflows** pack ships **Bug Fix**,
  **Feature**, and **Spec-driven Delivery**; **tech-debt** ships a **Debt
  Remediation** doctrine. (`Process.pack` tag added.)
- **Expanded the canon** — new packs **code-review** and **agile** (developer),
  **ci-cd** and **observability** (platform), and broader **software-general**,
  **platform-engineering**, and **infrastructure** standards.

### Note
- Pack catalog is curated canon — modern team-workflow, software-engineering, and
  platform-engineering standards; expansion is ongoing.

## [0.13.18] — 2026-07-03

### Added
- **Audit retention / purge** — `POST /audit/purge?days=N` (admin) deletes audit
  events older than the retention window; `purge_events` helper. Purge control on
  the Audit tab. (Data **residency** is a self-hosted deploy concern — the DB
  lives wherever you install it; documented, not code.)
- **Experiment-tagged runs (control / treatment)** — `execute(...)` accepts
  `experiment_id` + `arm` (`/execute` body too); a tagged run feeds its `units`
  into the experiment's **control** (`arm="control"` → before) or **treatment**
  (→ after) eval automatically (best-effort), so live work builds the before/after
  samples without a manual `record_eval`. `add_sample` helper accumulates into the
  matching eval run.

## [0.13.17] — 2026-07-03

### Added
- **Generic `api` target backend** — an `api` target now makes a real HTTP POST
  of the payload to its endpoint (connects by API key or OAuth token; parses a
  JSON response when `output_schema` is set). Registered as `EXECUTORS["api"]`
  (was the stub); transport injectable.
- **Quota rate windows** — a quota can carry `window_seconds`; usage resets once
  the rolling window elapses, giving per-minute/hour rate caps (0 = lifetime cap,
  as before). Enforced pre-call, so a blocked call still consumes nothing.
  Targets tab quota form gains a window field.

## [0.13.16] — 2026-07-03

### Added
- **Cascading suggestions.** When no approval workflow is configured for a
  layer, a proposal now **cascades up the role ladder** from the proposer —
  every role ranked above them, lowest first (a developer's idea escalates
  dev → … → platform → admin), each step still accept / deny / feedback. Plus a
  free-text **`suggestion`** proposal kind so anyone can send an idea up the
  chain (adopted on full accept; no artifact created). Dashboard Proposals tab
  gains a kind toggle (policy rule / suggestion).

## [0.13.15] — 2026-07-03

### Added
- **Evals & experiments.** Run a change as an `Experiment` at a layer
  (project / platform / harness / charter): state a **hypothesis** + the
  **change**, record **before/after** eval samples per metric and round, and
  `analyze` compares them — **delta**, effect size (**Cohen's d**), a
  significance test on the difference of means (stdlib `NormalDist` z-test, no
  scipy), and a plain **verdict** (significant improvement / regression / no
  effect / insufficient data). Iterate by recording another round (analysis uses
  the latest). `GET/POST /experiments`, `POST /experiments/{id}/evals`,
  `GET /experiments/{id}/analysis`, `POST /experiments/{id}/conclude`. Dashboard
  **Experiments** tab. Results stored structured (samples + summary), not prose.

### Note
- Significance is a normal-approximation z-test — fine for reasonable n; use a
  proper t-test/scipy offline for small samples. Tagging live work runs *as*
  experiments (isolated from normal metrics) is a follow-up.

## [0.13.14] — 2026-07-03

### Added
- **More starter packs** — `tdd` (red/green/refactor), `atdd` (acceptance-first,
  three amigos, given/when/then), `spec-driven` (spec-first, derive tests+impl,
  keep in sync), `ui-verification` (headless Puppeteer/Playwright checks, visual
  snapshots, state matrix), and `tech-debt` (identify/track, budget remediation,
  boy-scout rule, a remediation-doctrine process). All developer-layer, enable
  via the CLI or Packs tab.

### Changed
- **README value prop** refreshed to lead with the **governance policy layer**,
  **configurable oversight strategy**, and **human approval gates**.

## [0.13.13] — 2026-07-03

### Added
- **Target OAuth handshake** — connect a target by **OAuth** as well as API key
  (parity with integrations). `POST /targets/{id}/oauth/{provider}/start` →
  authorize URL; `GET /targets/{id}/oauth/{provider}/callback` exchanges the code
  (reusing the configured provider's client creds + `oauth.PROVIDERS`) and stores
  `{"provider", "access_token"}` in the target's encrypted credential — which the
  model/MCP backends already read. `set_target_credential` added. Dashboard: per-
  target **OAuth: <provider>** connect buttons for each configured provider.

## [0.13.12] — 2026-07-03

### Changed
- **Brand is "Open Refinery"** (title case) across the UI — the header, the
  login / setup / accept-invite screens, the welcome toast, and the browser tab
  title (both the dynamic `Open Refinery · <page>` and the `index.html` title).

## [0.13.11] — 2026-07-03

### Added
- **Real MCP target backend.** `mcp` targets now make a JSON-RPC **`tools/call`**
  over HTTP (Streamable-HTTP SSE replies tolerated). Payload is
  `{"tool": name, "arguments": {...}}` (a bare string is the tool name); connects
  by API key or OAuth token; honors a target's `output_schema` via the server's
  `structuredContent`. Registered as `EXECUTORS["mcp"]` (was the stub). Transport
  is injectable, so request shaping, auth, SSE parsing, structured output, and
  error handling are covered offline.

## [0.13.10] — 2026-07-03

### Added
- **Webhooks.** Register an endpoint with an optional **event filter** (recipe
  names; blank = all) and a generated **signing secret** (shown once, stored
  encrypted). Audit events fan out to matching active endpoints as a JSON POST
  with an `X-OpenRefinery-Signature: sha256=<hmac>` header; the last delivery
  status is recorded. `GET/POST/DELETE /webhooks` (platform/admin). Dashboard:
  a **Webhooks** card in Settings. Delivery is synchronous best-effort today
  (errors swallowed) — a background runner is the post-1.0 job-queue item.
- **Swagger "Try it out" is now authenticated.** The OpenAPI schema declares a
  Bearer security scheme, so `/api-docs` shows an **Authorize** button — paste a
  token once and call any endpoint live from the browser.

## [0.13.9] — 2026-07-03

### Added
- **Ingest repo surfaces** (`POST /repositories/{id}/ingest`). Reads a repo's
  real surfaces via a connected **GitHub integration** and turns stated behaviors
  into `Claim`s: **charter** ← `.claude/` docs (headings/bullets), **harness** ←
  `CLAUDE.md`/`AGENTS.md`, **code** ← structural signals (tests dir, CI present).
  Each new claim gets a heuristic backing read — `has_instruction` if it echoes
  an authored policy/standard, `has_gate` if the org has a gated process. Re-ingest
  is idempotent (dedupe by repo+surface+text). Coverage/charter-health now run on
  reality instead of hand-seeded claims. Dashboard: **Ingest from source** button
  on the Coverage tab.

### Note
- The reader is injectable; extraction/dedup/backing are tested offline. The live
  GitHub read is best-effort (returns nothing on any error rather than failing).
  Follow-up: schedule ingest, and per-repo integration linking (today it uses the
  repo owner's first GitHub integration).

## [0.13.8] — 2026-07-03

### Added
- **Debt audits & health.** Run an audit per area — **factory** (rule config:
  dead/contradiction/redundant), **harness** (artifact prompt-injection),
  **charter** (repo coverage + imitation surfaces) — each scored **0–100** with
  concrete **insights** ("what to try next", ordered by impact). `run_audit`
  persists an `Audit` row so health is trackable/reportable over time.
  `GET /health/areas` (live scores), `GET /audits` (history), `POST /audits/run`
  (`?area=all|factory|harness|charter`). Dashboard **Audits** tab: area health
  cards + run + history. Reuses governance analysis + repo coverage as signals.

### Note
- Next: **ingest** — populate repo `Claim`s from real sources (`.claude/` charter,
  harness config, code signals) via the GitHub integration, triggered per repo
  like tracker sync, so coverage/charter-health run on reality, not seeded claims.

## [0.13.7] — 2026-07-03

### Added
- **Real OpenAI model backend** — a credentialed `gpt*`/`o1`/`o3`/`o4` (or
  `provider: openai`) target makes a real **Chat Completions** call via the
  official SDK, honoring `output_schema` through a `json_schema` response format
  and returning completion-token `units`. Registered alongside Anthropic in
  `MODEL_BACKENDS`; `pip install open-refinery[providers]` now pulls both SDKs.
- **Connect by API key *or* OAuth token** — backends read the target credential
  as `api_key`, `token`, **or `access_token`**, so a target connected via OAuth
  (token stored in the encrypted credential) works the same as an API-key target.

### Note
- Interactive OAuth *handshake* for targets (authorize → callback → store token,
  like the GitHub integration) and the **MCP** transport are the next slice; MCP
  and generic API targets still use the stub.

## [0.13.6] — 2026-07-03

### Added
- **Real Anthropic model backend.** The executor's `model` targets now dispatch
  by provider: with a credential (`{"provider":"anthropic","api_key":...}` or a
  `claude*` endpoint + key) a real **Anthropic Messages API** call runs via the
  official SDK — honoring a target's `output_schema` through structured outputs,
  returning output-token `units`, and treating a `refusal` stop reason as a
  failure (so the executor fails over). **No credential (or no real backend) →
  the stub**, so a fresh install still works offline and the suite stays hermetic.
  Model id = the target `endpoint` (default `claude-opus-4-8`). Anthropic SDK is
  an opt-in extra: `pip install open-refinery[providers]`.

### Note
- OpenAI and MCP register as provider slots (`MODEL_BACKENDS`) but ship the stub;
  a Claude-independent OpenAI backend and the MCP transport are follow-ups.
- The live API path can't be exercised in CI (no key); dispatch, request
  building, structured parsing, and refusal handling are covered against a
  stand-in SDK.

## [0.13.5] — 2026-07-03

### Added
- **Repo-level drift & coverage.** Each governance **`Claim`** sits on a repo
  **surface** (charter / harness / code) and records whether an **instruction**
  and a **gate** back it. Per repo: **coverage** (fraction fully backed, overall
  + per surface, 0–100 health score), **imitation surfaces** (claims with no
  instruction *and* no gate — reads as governed, isn't; the prime action
  targets), and **drift** across all three axes (charter↔harness, charter↔code,
  harness↔code — claims on one surface missing on another).
  `GET /repositories/{id}/coverage`, `GET/POST /repositories/{id}/claims`,
  `DELETE /claims/{id}`. Dashboard **Coverage** tab. Claims are authored/seeded
  today; auto-ingesting real `.claude/`, harness config, and code signals is a
  follow-up connector.

## [0.13.4] — 2026-07-03

### Added
- **Governance analysis — poison flags** (`GET /governance/analysis`; per-role
  visibility). Static analysis over the rule set + artifact content flags: **dead**
  rules (shadowed by a strict higher-layer opposite rule), **contradictions**
  (same-layer opposite-effect overlapping rules), **redundant** rules (covered by
  a broader same-effect rule), and **prompt_injection** in skill/command/agent
  `content` (starter pattern set). Each finding carries the author layer + an
  **insight**; a viewer sees only findings at or below their layer, with per-type
  **metrics**. The admin governance landscape's `violations` is now populated from
  this (was stubbed). Dashboard: a **Governance flags** card in the Metrics tab.

### Note
- Drift proper (config vs. what's actually enforced; charter/harness vs. code)
  is the next **repo-level** slice.

## [0.13.3] — 2026-07-03

### Added
- **Per-layer approval workflows** — govern changes *to* governance. Admins
  configure, per role **layer**, the ordered approval chain
  (`GET/POST /approval-workflows`, admin). A **change proposal**
  (`POST /proposals`) walks that chain with three outcomes at each step —
  **accept** (advance; applies the change on the last slot), **deny** (stop),
  **feedback** (send back to the proposer to **revise & resubmit**). Separation
  of duties: a distinct signer per slot, each at or above the slot's role.
  `POST /proposals/{id}/review`, `/resubmit`, `GET /proposals`. First supported
  change is **policy-create** (authored at the proposer's layer, so it inherits
  the right strict-precedence rank); the applier registry is extensible.
  Dashboard **Proposals** tab (propose, review, resubmit; admin workflow config).

### Note
- Roadmap: **governance analysis** — flag rules that never fire (dead),
  contradictions, likely prompt injection, and **drift**, per role level with
  metrics + insights (feeds the landscape's stubbed `violations`).

## [0.13.2] — 2026-07-03

### Added
- **Admin governance landscape** (`GET /governance`, admin-gated; dashboard
  **Governance** tab) — the read view over roles + the layer graph: the role
  ladder with user counts, **rules grouped by layer** (author role rank, highest
  first), and **what overrides what** (strict rules shadowing a lower-layer,
  opposite-effect rule). Drift/violations are stubbed (empty) pending
  enforcement-outcome logging — a later slice.

## [0.13.1] — 2026-07-03

### Added
- **Governance layer graph (strict precedence).** A rule's layer is the rank of
  its author's role (the **platform → developer** axis). `decide`/`enforce` now
  resolve strict rules along that graph: the **highest-ranked** strict rule wins
  and cannot be overridden by a lower layer (ties at that rank deny-override);
  with no strict rule, plain deny-overrides applies. `decide` takes an optional
  `rank_of` (defaults to a flat single layer, preserving prior behavior);
  `enforce` builds it from each policy owner's role rank.

### Note
- The **factory → harness → charter** artifact axis is folded into the role-rank
  axis for now (chosen model). A separate `layer` field + 2-D lattice remains a
  future option (see PLAN). Per-layer approval workflows and the admin
  governance landscape are still upcoming 0.13.x slices.

## [0.13.0] — 2026-07-03

### Changed
- **Roles are admin-configurable data, not a hardcoded enum.** A `roles` table
  (name + rank) is seeded on a fresh store with the minimal ladder
  **developer < platform < admin**; admins add and re-rank more (senior, lead,
  team leads — whatever the org needs) via `GET/POST/DELETE /roles` (a new
  **Roles** concern, admin-gated). Rank comparisons (`at_least`, `role_rank`),
  invitation gating, per-process approver/chain validation, and user creation
  now resolve roles from the store. The admin role and any in-use role cannot
  be deleted. Default per-process `min_approver_role` is now **platform**.

### Added
- **Packs** — opt-in, role-gated **starter** bundles of guidance (`Standard`s).
  The base install seeds almost nothing (roles + the first admin); topic content
  ships as packs: **software-general / charter** (developer), **platform-general
  / infrastructure** (platform), **org-policy** (admin). Enable/disable via the
  CLI (`open-refinery packs list|enable|disable`) or the dashboard **Packs** tab;
  `GET /packs`, `POST /packs/{key}/enable|disable`, `GET /standards`. Enabling is
  role-gated (`at_least`); reading standards is open to any authed user.
- **Policies are authored governed harness artifacts** — a policy now has a
  `kind` ∈ **rule / skill / command / agent** (hooks TBD). Rules keep the
  allow/deny gate (deny-overrides); skills/commands/agents carry `content`.
- **Strict rules** — a rule may be marked **strict** (a lower layer may not
  override it): strict rules decide alone, deny-overrides among them. Strict's
  **default is an admin Setting** (`policy.strict_default`, off unless set).

### Note
- Pre-1.0 schema churn: the `lead` role baked in at 0.12.6 is gone from the
  defaults — orgs add it (or any tier) themselves. New `roles` / `pack_states` /
  `standards` tables + `policies` columns land via migration v5. Recreate the
  dev database if in doubt.
- Roadmap (0.13.x, see PLAN): real target backends (Anthropic/OpenAI/MCP); the
  **layer graph** (factory→harness→charter | platform→developer) with strict
  precedence; **per-layer approval workflows** (accept/deny/feedback cascade);
  **packs bundling artifacts** (e.g. a TDD pack shipping a `tdd` command/skill,
  namespaced); the **admin governance landscape** (defined-where, overrides,
  drift, violations). Post-1.0: **admin-managed MFA**.

## [0.12.6] — 2026-07-03

### Added
- **`lead` role** — five-role ladder (developer < senior < **lead** < platform <
  admin). Concerns: developer ⊂ senior (repo work); senior at repo level (may
  suggest team-layer changes); lead approves/applies those and may suggest
  infrastructure changes; platform approves those and owns policy; admin audits.

### Note
- Roadmap: **cascading suggestions** — a proposal escalates up the role chain,
  each level able to accept / deny / send feedback (revise & resubmit).

## [0.12.5] — 2026-07-03

### Changed
- **Config lives in the database, not the environment.** OAuth provider client
  id/secret are stored in an encrypted `Setting` store and resolved from there
  (environment variables remain a fallback). Managed in the UI by platform/admin
  via a new **Settings** tab and `/settings` API (values are encrypted at rest
  and never returned — only keys). **Only `SECRET_KEY` is now required in the
  environment.**

## [0.12.0] — 2026-07-03

### Added
- **User invitations** — a user invites a **strictly lower** role by email
  (admin → any below, platform → senior & below, senior → developer). The invite
  carries an **expiring token** (default 7 days, configurable) and the assigned
  role; the invitee opens the link and **sets their own password** to register.
  Endpoints: `POST /invitations`, `GET /invitations`,
  `/invitations/{id}/revoke`, `/invitations/lookup`, `/invitations/accept`.
  Dashboard "Invitations" tab (senior+) and an accept-invite screen.
- **Email as a port/adapter** — `EmailSender` protocol with a default
  `LinuxMailSender` (local `mail`); swappable (SMTP/others later; UI-configurable
  with the DB settings work).

### Changed
- Dashboard branding is **"open refinery"** (no dash); the browser tab title is
  `open refinery · <page>`.

## [0.11.0] — 2026-07-03

### Added
- **Structured output in the executor** — a target may declare an
  `output_schema`; when set, the executor validates the model's output against it
  (object shape, required keys, declared types), content-filters string leaves,
  and persists/returns it **structured** (not stringified). Output that doesn't
  conform fails the call. Free-text remains the fallback when no schema is set.
  Aligns with `.claude/rules/structured-output.md`. (Real Anthropic/OpenAI/MCP
  backends land next.)

## [0.10.0] — 2026-07-03

### Added
- **Async approval queue** — request a gated move now, approve it later. Pending
  requests are a queue (dashboard "Approvals" tab); `POST
  /work-items/{id}/request-approval`, `GET /approvals`, `/approvals/{id}/approve`
  and `/reject`.
- **Chained approvals** — a process's `approval_chain` (ordered roles, e.g.
  `["senior","platform"]`) requires each slot signed by a **distinct** approver
  at or above that role, in order; the move applies when the chain completes.
  Defaults to `[min_approver_role]`.
- **Developer experience**: self-hosted Swagger UI at `/api-docs`;
  `frontend/src/api-types.ts` generated from the OpenAPI schema for
  backend/frontend type parity; `.claude/references/` design-lineage notes.

## [0.9.0] — 2026-07-03

### Added
- **`senior` role** — a four-role authority ladder (developer < senior <
  platform < admin). Seniors perform escalated operations and approve
  developers' risky (gated) moves.
- **Configurable per-process risk profile** — a process's `min_approver_role`
  (with oversight level, gated steps, and required checks) sets how much
  oversight it demands and who may approve; nothing is hardcoded, all UI-managed.
- **API token rotation** — `POST /me/token/rotate` (old token invalidated).

### Note
- Seeds are opt-in and load *example* data only (now including a `senior` user);
  a fresh instance is always empty until setup. Pre-1.0 schema churn accepted;
  the schema freezes at 1.0.

## [0.8.0] — 2026-07-03

### Added
- **Executor** — `POST /execute` runs the governed outbound pipeline for a
  process/step: resolve route → role-based invoke authorization → quota →
  secrets injection (credential decrypted at the call site, never returned) →
  content filter (payload and response) → pluggable backend → audit
  (`invoke` / `invoke-failed`), with **failover** across candidate routes.
  Real model/MCP/API backends register in `EXECUTORS`; a stub ships by default.

## [0.7.0] — 2026-07-03

### Added
- **Policy governance** — org-wide `(effect, role, action, resource)` rules with
  a deny-overrides engine (default allow), enforced on work-item transitions by
  the actor's role (`403` on denial). Platform/admin manage policies.
- **Content filtering** — `scan_content` redacts secrets and PII (emails, card
  numbers, AWS keys, bearer tokens); `POST /content/scan`.
- Dashboard "Policies" tab with a content-filter tester.

## [0.6.0] — 2026-07-03

### Added
- **Targets, routing, and quotas** — the Platform layer's outbound governance:
  - **Targets**: models, MCP servers, and backend APIs, with credentials
    encrypted at rest.
  - **Routing**: routes map a process (optionally a step) to a target by
    priority; a step-specific route wins ties.
  - **Quotas**: per-target usage caps enforced *before* a call — a blocked call
    consumes nothing (`429` on the API).
  - Dashboard "Targets" tab for managing all three.

## [0.5.0] — 2026-07-03

### Changed
- **Data layer ported to SQLModel** (SQLAlchemy + Pydantic). Entities are now
  typed table models; modules use per-request `Session`s instead of hand-written
  `sqlite3` SQL. Keeps the migration runner and the audit event store; opens the
  door to other backends (Postgres, …).

### Note
- Pre-0.5 databases are **not migrated** across this change (the `processes`
  table was restructured). Recreate the database. Breaking schema churn is
  accepted before 1.0.0; structural migrations begin at 1.0.

## [0.4.0] — 2026-07-03

### Added
- **Integrations** — connect external services from the dashboard:
  - Source hosts **GitHub** and **GitLab**: verify a connection, browse remote
    repositories, and import them as `Repository` entities (idempotent).
  - Trackers **Jira** and **Linear**: **work-item sync** — import issues as work
    items, deduped by an external reference and recorded as `sync` audit events;
    re-syncing skips already-imported issues.
  - Connect via **API token or OAuth**, gated per provider on its client
    credentials; credentials stored **encrypted at rest** (Fernet via
    `SECRET_KEY`) and never returned by the API.
  - Disconnect integrations; `GET /integrations/{id}/issues` and `/sync`.
- **Email + password login** (`POST /auth/login`) as the primary user sign-in;
  API tokens remain for programmatic clients.
- **Versioned schema migrations** (`PRAGMA user_version` + append-only list);
  `work_items.external_ref` shipped as the first migration.
- **USER_GUIDE.md** — fresh-VPS deployment walkthrough (install, background
  serve, create-admin, login, ports, HTTPS/TLS on 443 via a reverse proxy).

### Changed
- Service credentials generalized to an encrypted JSON credential (Jira uses
  site/email/token; other providers use a token).
- Dev `SECRET_KEY` moved out of the Makefile into a gitignored `.env`; `make dev`
  sources it. `.env.example` lists every configurable value.

## [0.3.0] — 2026-07-03

### Added
- FastAPI server with a bundled React + shadcn/ui dashboard (light/dark/auto).
- Auth: local accounts, API tokens, **GitHub OAuth** sign-in, roles
  (developer / platform / admin), ownership scoping, first-run setup wizard.
- Process engine: steps with feedback loops, board and doctrine archetypes, and
  a governed transition loop.
- Oversight levels L0–L4 with approvals and attestation-based quality gates.
- Metrics read-model and an attributed, append-only audit trail.
- SQLite persistence; `pip install open-refinery && open-refinery serve`.

## [0.1.0] — 2026-07-03

### Added
- Initial proof of concept: the core governed-production loop
  (authorize → produce → record → audit → log) as an embeddable library.
