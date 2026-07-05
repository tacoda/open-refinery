# Changelog

All notable changes to open-refinery are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/); versions follow semver.

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
