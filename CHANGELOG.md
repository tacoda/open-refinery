# Changelog

All notable changes to open-refinery are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/); versions follow semver.

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
