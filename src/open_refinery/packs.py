"""Packs — opt-in, role-gated bundles of starter guidance ("standards").

The base install seeds almost nothing (roles + the first admin). Topic content
ships as **packs**: a developer enables software/charter packs, platform enables
platform/infrastructure packs, admin owns the high-level org-policy pack. A pack
is a code-defined catalog entry; enabling it seeds its `Standard` rows (idempotent)
and records a `PackState`. Enable/disable is gated by role; reading the resulting
standards is open to any authenticated user.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlmodel import Session, select

from .models import PackState, Process, Standard, User
from .policies import PolicyDenied
from .processes import create_process
from .users import at_least


@dataclass(frozen=True)
class Pack:
    key: str
    role: str          # minimum role that may enable/disable it (the layer it serves)
    title: str
    description: str
    standards: tuple[tuple[str, str, str], ...]  # (topic, title, body)
    processes: tuple[dict, ...] = ()             # example process templates to seed


# The catalog. Bodies are short starters — orgs edit them after enabling.
PACKS: tuple[Pack, ...] = (
    Pack("software-general", "developer", "General software",
         "Design, testing, standards, best practices, idioms, conventions.", (
             ("software-design", "Software design",
              "Prefer simple, cohesive modules. Manage complexity; design load-bearing decisions twice."),
             ("testing", "Testing",
              "Non-trivial logic ships with a test. Prove a bug with a failing test before fixing it."),
             ("standards", "Coding standards",
              "Match existing style. Small, reviewable changes; no speculative abstractions."),
             ("conventions", "Conventions & idioms",
              "Follow the language and framework idioms. Consistency over novelty."),
             ("version-control", "Version control",
              "Small, focused commits with clear messages; short-lived branches; never commit secrets."),
             ("error-handling", "Error handling",
              "Validate at trust boundaries; fail loud, not silent; don't swallow exceptions."),
             ("documentation", "Documentation",
              "Document the why, not the what. Keep READMEs and runbooks current with the code."),
             ("dependencies", "Dependencies",
              "A new dependency needs a reason; prefer the stdlib. Pin and audit what you add."),
         )),
    Pack("code-review", "developer", "Code review",
          "How to review and be reviewed.", (
              ("small-prs", "Small pull requests",
               "Keep PRs small and single-purpose; large PRs get shallow reviews."),
              ("review-checklist", "Review checklist",
               "Correctness, tests, readability, security, and performance — in that order."),
              ("blocking-vs-nit", "Blocking vs nit",
               "Mark comments as blocking or nit; don't block a merge on style preferences."),
              ("review-sla", "Review SLA",
               "Review within one business day; a stalled PR is work-in-progress that isn't shipping."),
          )),
    Pack("agile", "developer", "Team workflow (agile)",
          "Modern team-workflow canon.", (
              ("wip-limits", "Limit work in progress",
               "Finish before starting; WIP limits expose bottlenecks and cut lead time."),
              ("definition-of-done", "Definition of done",
               "Agree what 'done' means (tests, review, docs, deployed) before starting."),
              ("small-batches", "Small batches",
               "Ship small and often; small batches lower risk and shorten feedback."),
              ("retrospect", "Retrospect & improve",
               "Reflect regularly; turn findings into one concrete change, then measure it."),
          )),
    Pack("charter", "developer", "Charter",
         "Agent charter basics (harness detail abstracted).", (
             ("charter-basics", "Charter basics",
              "The charter defines how agents work here: scope, guardrails, and review gates. Keep it current and pruned."),
         )),
    Pack("tdd", "developer", "TDD",
         "Test-driven development.", (
             ("red-green-refactor", "Red / green / refactor",
              "Write a failing test (red), the least code to pass it (green), then refactor with the test green."),
             ("test-first", "Test first",
              "Write the test before the implementation. Prove a bug with a failing test before fixing it."),
             ("small-steps", "Small steps",
              "One behavior per test; keep the red-to-green loop short so a failure points at one change."),
         )),
    Pack("atdd", "developer", "ATDD",
         "Acceptance-test-driven development.", (
             ("acceptance-first", "Acceptance criteria as tests",
              "Turn each acceptance criterion into an executable test before building; the story is done when they pass."),
             ("three-amigos", "Three amigos",
              "Product, dev, and QA agree on examples before work starts — shared understanding, not handoff."),
             ("given-when-then", "Given / when / then",
              "Express acceptance tests as Given (context) / When (action) / Then (observable outcome)."),
         )),
    Pack("spec-driven", "developer", "Spec-driven development",
         "Specification as the source of truth.", (
             ("spec-first", "Spec first",
              "Write and agree the spec before code. The spec — not the implementation — is the source of truth."),
             ("derive-from-spec", "Derive tests + impl from the spec",
              "Generate acceptance tests and implementation from the spec; a change starts by changing the spec."),
             ("spec-in-sync", "Keep the spec in sync",
              "When behavior changes, update the spec in the same change — drift between spec and code is charter debt."),
         )),
    Pack("ui-verification", "developer", "UI verification",
         "Verify rendered UI, not just unit logic.", (
             ("headless-checks", "Headless browser checks",
              "Drive the UI with Puppeteer/Playwright: navigate, assert rendered state and key elements exist."),
             ("visual-snapshots", "Visual snapshots",
              "Capture screenshots of critical screens/states and diff against a baseline to catch visual regressions."),
             ("state-matrix", "State matrix",
              "Verify empty / populated / error / role-gated states, not just the happy path."),
         )),
    Pack("tech-debt", "developer", "Tech-debt processes",
         "Process patterns for finding, tracking, and paying down debt.", (
             ("identify-track", "Identify & track",
              "Run debt audits (factory/harness/charter); log findings as work items with an owner and a health impact."),
             ("budget-remediation", "Budget remediation",
              "Reserve a fixed capacity each cycle for debt paydown; ratchet the health score up, never down."),
             ("boy-scout", "Boy-scout rule",
              "Leave touched code cleaner than you found it — small, in-scope cleanups over big-bang refactors."),
         ),
         processes=(
             {"name": "Debt Remediation", "archetype": "doctrine",
              "stages": ["detect", "triage", "patch", "verify", "close"],
              "transitions": [["detect", "triage"], ["triage", "patch"], ["patch", "verify"],
                              ["verify", "close"], ["verify", "patch"]],  # verify→patch loop
              "gates": ["close"]},
         )),
    Pack("workflows", "developer", "Workflow processes",
         "Ready-made processes: bug fix, feature, spec-driven delivery.", (
             ("bug-fix", "Bug fix",
              "Reproduce with a failing test, fix, verify the test passes, then close."),
             ("feature", "Feature",
              "A board: backlog → in-progress → review → done."),
         ),
         processes=(
             {"name": "Bug Fix", "archetype": "doctrine",
              "stages": ["reproduce", "fix", "verify", "close"],
              "transitions": [["reproduce", "fix"], ["fix", "verify"], ["verify", "close"],
                              ["verify", "fix"]],  # verify→fix loop
              "gates": ["close"]},
             {"name": "Feature", "archetype": "board",
              "stages": ["backlog", "in-progress", "review", "done"], "gates": ["done"]},
             {"name": "Spec-driven Delivery", "archetype": "doctrine",
              "stages": ["spec", "tests", "implement", "verify", "ship"],
              "transitions": [["spec", "tests"], ["tests", "implement"], ["implement", "verify"],
                              ["verify", "ship"], ["verify", "implement"], ["tests", "spec"]],
              "gates": ["ship"]},
         )),
    Pack("platform-general", "platform", "Platform engineering",
         "Platform-engineering canon.", (
             ("platform-basics", "Platform standards",
              "Govern how work reaches targets: identity, authorization, quotas, audit. The platform governs; it does not do the harness's job."),
             ("golden-paths", "Golden paths",
              "Offer paved, opinionated defaults for the common case; make the right thing the easy thing."),
             ("self-service", "Self-service",
              "Teams provision and ship without tickets; the platform is a product with users, not a gatekeeper."),
             ("platform-as-product", "Platform as a product",
              "Treat internal tooling as a product: measure adoption, gather feedback, iterate."),
             ("guardrails-not-gates", "Guardrails, not gates",
              "Prefer automated guardrails (policy, defaults) over manual approval gates where risk allows."),
         )),
    Pack("ci-cd", "platform", "CI/CD & delivery",
          "Continuous integration and delivery canon.", (
              ("trunk-based", "Trunk-based development",
               "Integrate to a shared trunk daily behind feature flags; avoid long-lived branches."),
              ("pipeline-gates", "Pipeline gates",
               "Every change passes automated build, test, and security gates before merge/deploy."),
              ("deploy-small-often", "Deploy small and often",
               "Small, frequent, automated deploys lower risk and mean-time-to-recovery."),
              ("rollback", "Fast rollback",
               "Every deploy has a rollback path; progressive rollout with health checks before widening."),
          )),
    Pack("observability", "platform", "Observability & SRE",
          "Observability and reliability canon.", (
              ("three-pillars", "Logs, metrics, traces",
               "Instrument all three; correlate them by request/trace id for real debuggability."),
              ("slos", "SLOs & error budgets",
               "Define SLOs from user-facing symptoms; spend the error budget deliberately."),
              ("alert-on-symptoms", "Alert on symptoms",
               "Page on user-visible symptoms, not causes; every alert must be actionable."),
              ("blameless-postmortems", "Blameless postmortems",
               "After incidents, fix systems not people; track action items to closure."),
          )),
    Pack("infrastructure", "platform", "Infrastructure",
         "Microservices, security, DB migration rollout, release rollout.", (
             ("microservices", "Microservices",
              "Define service boundaries and ownership. Keep contracts explicit and versioned."),
             ("security", "Security",
              "Least privilege. Secrets encrypted at rest. Validate at trust boundaries."),
             ("db-migration", "DB migration rollout",
              "Backward-compatible migrations (expand/contract). Roll out the schema before code depends on it."),
             ("release-rollout", "Release rollout",
              "Progressive rollout with a rollback path. Watch metrics before widening."),
         )),
    Pack("org-policy", "admin", "Org policy",
         "High-level organization policies.", (
             ("compliance", "Compliance example",
              "Example: all code must adhere to HIPAA. Replace with your organization's binding policies."),
         )),
)

_BY_KEY = {p.key: p for p in PACKS}


def pack_by_key(key: str) -> Pack | None:
    return _BY_KEY.get(key)


def list_packs(session: Session) -> list[dict]:
    """Catalog with each pack's enabled state (for the UI / CLI)."""
    states = {s.key: s.enabled for s in session.exec(select(PackState))}
    return [{"key": p.key, "role": p.role, "title": p.title,
             "description": p.description, "enabled": states.get(p.key, False)}
            for p in PACKS]


def _authorize(session: Session, pack: Pack, user: User) -> None:
    if not at_least(session, user.role, pack.role):
        raise PolicyDenied(f"enabling the {pack.key!r} pack requires {pack.role}+")


def enable_pack(session: Session, key: str, user: User) -> dict:
    pack = pack_by_key(key)
    if pack is None:
        raise ValueError(f"unknown pack: {key!r}")
    _authorize(session, pack, user)

    existing = {s.title for s in session.exec(select(Standard).where(Standard.pack == key))}
    for topic, title, body in pack.standards:
        if title not in existing:  # idempotent
            session.add(Standard(pack=key, topic=topic, title=title, body=body, owner_id=user.id))

    have_proc = {p.name for p in session.exec(select(Process).where(Process.pack == key))}
    for spec in pack.processes:
        if spec["name"] not in have_proc:  # idempotent
            create_process(session, spec["name"], spec["archetype"], spec["stages"], user.id,
                           transitions=spec.get("transitions"), gates=spec.get("gates"),
                           oversight=spec.get("oversight", "supervised"), pack=key)

    state = session.get(PackState, key) or PackState(key=key, updated_by=user.id)
    state.enabled = True
    state.updated_by = user.id
    session.add(state)
    session.commit()
    return {"key": key, "enabled": True}


def disable_pack(session: Session, key: str, user: User) -> dict:
    pack = pack_by_key(key)
    if pack is None:
        raise ValueError(f"unknown pack: {key!r}")
    _authorize(session, pack, user)

    for std in session.exec(select(Standard).where(Standard.pack == key)):
        session.delete(std)
    for proc in session.exec(select(Process).where(Process.pack == key)):
        session.delete(proc)
    state = session.get(PackState, key) or PackState(key=key, updated_by=user.id)
    state.enabled = False
    state.updated_by = user.id
    session.add(state)
    session.commit()
    return {"key": key, "enabled": False}


def list_standards(session: Session, *, pack: str | None = None) -> list[Standard]:
    """Seeded guidance — readable by any authenticated user."""
    stmt = select(Standard)
    if pack is not None:
        stmt = stmt.where(Standard.pack == pack)
    return list(session.exec(stmt.order_by(Standard.pack, Standard.title)))
