# Changelog

All notable changes to open-refinery are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/); versions follow semver.

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
