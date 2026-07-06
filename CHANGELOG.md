# Changelog

All notable changes to open-refinery are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/); versions follow semver.

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
