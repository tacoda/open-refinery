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

from .models import PackState, Policy, Process, Standard, User
from .policies import PolicyDenied, create_policy
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
    artifacts: tuple[dict, ...] = ()             # governed Policy artifacts (rule/skill/command/agent)


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
          ),
          artifacts=(
              {"kind": "command", "layer": "harness", "namespace": "canon/code-review", "content":
               "review: check correctness, tests, readability, security, and performance; "
               "mark each comment blocking or nit; approve or request changes."},
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
         ),
         artifacts=(
             {"kind": "command", "layer": "harness", "namespace": "canon/tdd", "content":
              "tdd: write a failing test for the next behavior, run it (red), write the "
              "minimum code to pass (green), then refactor with the test green."},
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
         ),
         artifacts=(
             {"kind": "agent", "layer": "factory", "namespace": "org", "content":
              "compliance-reviewer: before close, confirm the change meets the org's binding "
              "policies (e.g. HIPAA); flag anything that doesn't."},
         )),

    # ── developer tier ──────────────────────────────────────────────────────
    Pack("secure-coding", "developer", "Secure coding",
         "Write code that resists the common vulnerability classes.", (
             ("input-validation", "Validate untrusted input",
              "Validate and normalize everything crossing a trust boundary; reject by default."),
             ("injection", "Prevent injection",
              "Parameterize queries and commands; never build them by string concatenation."),
             ("authz-checks", "Check authorization every time",
              "Enforce access at the resource, not the route; don't trust client-supplied identity."),
             ("no-secrets-in-code", "No secrets in code",
              "Keep credentials out of source and logs; load from a secret store at runtime."),
             ("least-privilege", "Least privilege",
              "Grant the narrowest scope that works; expire and rotate access."),
         ),
         artifacts=(
             {"kind": "command", "layer": "harness", "namespace": "canon/secure-coding", "content":
              "security-review: check input validation, injection, authz, secret handling, and "
              "dependency risk; return {passed, findings, severity}."},
         )),
    Pack("api-design", "developer", "API design",
         "Design APIs that are predictable and evolvable.", (
             ("contract-first", "Contract first",
              "Agree the schema/contract before implementing; generate types from it."),
             ("versioning", "Version deliberately",
              "Version breaking changes; add fields additively; never repurpose a field."),
             ("idempotency", "Idempotency",
              "Make writes safe to retry (idempotency keys); network calls will be retried."),
             ("pagination", "Pagination & limits",
              "Page large collections; bound every list response; document the limits."),
             ("error-shape", "Consistent errors",
              "Return a stable, typed error shape with codes a client can branch on."),
         )),
    Pack("refactoring", "developer", "Refactoring",
         "Change structure without changing behavior.", (
             ("tests-green", "Tests green throughout",
              "Refactor only under a passing test suite; run it before and after each step."),
             ("small-steps", "Small steps",
              "Rename, extract, inline in tiny commits; a broken step should point at one change."),
             ("no-behavior-change", "No behavior change",
              "A refactor changes structure, not behavior; separate refactors from feature changes."),
             ("boy-scout", "Leave it cleaner",
              "Make in-scope cleanups as you pass through; avoid big-bang rewrites."),
         )),
    Pack("performance", "developer", "Performance",
         "Make it fast — after making it correct.", (
             ("measure-first", "Measure first",
              "Profile before optimizing; fix the measured bottleneck, not the guessed one."),
             ("budgets", "Performance budgets",
              "Set budgets (latency, payload, queries) and fail the build when they regress."),
             ("avoid-premature", "Avoid premature optimization",
              "Prefer clarity until a measurement says otherwise; document any speed-for-clarity trade."),
             ("cache-carefully", "Cache carefully",
              "Cache with explicit invalidation and TTLs; a stale cache is a correctness bug."),
         )),
    Pack("accessibility", "developer", "Accessibility",
         "Build UIs everyone can use.", (
             ("semantic-html", "Semantic markup",
              "Use the right element for the job; semantics give assistive tech meaning for free."),
             ("keyboard", "Keyboard operable",
              "Everything works without a mouse; visible focus, logical tab order, no traps."),
             ("contrast", "Color & contrast",
              "Meet WCAG contrast; never encode meaning in color alone."),
             ("aria-sparingly", "ARIA sparingly",
              "Prefer native elements; add ARIA only when semantics are missing, and test it."),
         )),
    Pack("data-engineering", "developer", "Data engineering",
         "Build pipelines that stay trustworthy.", (
             ("idempotent-jobs", "Idempotent jobs",
              "Make jobs safe to re-run; reprocessing a window must not double-count."),
             ("schema-contracts", "Schema contracts",
              "Version data schemas; validate on read; evolve additively (expand/contract)."),
             ("data-quality", "Data quality checks",
              "Assert freshness, volume, and null/range expectations; alert on violations."),
             ("backfills", "Safe backfills",
              "Plan backfills as reversible, rate-limited batches with a verification step."),
         )),
    Pack("prompt-engineering", "developer", "Prompt engineering",
         "Author reliable model-driven steps (harness-side).", (
             ("clear-instructions", "Clear instructions",
              "State the task, constraints, and output contract explicitly; show one example."),
             ("structured-output", "Structured output",
              "Demand a schema (JSON/tool) for anything machine-consumed or audited, not prose."),
             ("evals", "Evaluate changes",
              "Gate prompt changes on an eval set; measure before/after, don't eyeball."),
             ("context-hygiene", "Context hygiene",
              "Give the model only what it needs; stale or excess context degrades output."),
         )),

    # ── platform tier ───────────────────────────────────────────────────────
    Pack("containers", "platform", "Containers & orchestration",
         "Package and run services predictably.", (
             ("immutable-images", "Immutable images",
              "Build once, promote the same artifact across environments; never patch in place."),
             ("small-images", "Minimal images",
              "Start from slim/distroless bases; fewer packages, smaller attack surface."),
             ("resource-limits", "Requests & limits",
              "Set CPU/memory requests and limits so one workload can't starve the node."),
             ("health-probes", "Health probes",
              "Expose liveness/readiness probes; don't route traffic before ready."),
         )),
    Pack("iac", "platform", "Infrastructure as code",
         "Declare infrastructure; never click-ops it.", (
             ("declarative", "Declarative",
              "Describe desired state in versioned code; the tool reconciles reality to it."),
             ("plan-before-apply", "Plan before apply",
              "Review a diff/plan before applying; applies go through the same review as code."),
             ("state-management", "Manage state",
              "Store state remotely with locking; never edit it by hand."),
             ("no-manual-drift", "No manual drift",
              "Change infra only through code; detect and reconcile out-of-band drift."),
         )),
    Pack("secrets-management", "platform", "Secrets management",
         "Handle credentials without leaking them.", (
             ("no-plaintext", "No plaintext secrets",
              "Never store secrets in code, config, or logs; use a vault/secret store."),
             ("rotation", "Rotate regularly",
              "Rotate credentials on a schedule and on compromise; automate it."),
             ("short-lived", "Prefer short-lived",
              "Use short-lived, scoped tokens over long-lived static keys where possible."),
             ("least-scope", "Least scope",
              "Scope each secret to one consumer and the narrowest permission set."),
         )),
    Pack("incident-response", "platform", "Incident response",
         "Respond to incidents calmly and consistently.", (
             ("sev-levels", "Severity levels",
              "Define sev levels with clear criteria so response matches impact."),
             ("single-commander", "One incident commander",
              "A single commander coordinates; responders own workstreams, not the whole."),
             ("comms-cadence", "Communicate on a cadence",
              "Post regular status updates to a known channel; over-communicate during impact."),
             ("runbooks", "Runbooks",
              "Keep tested runbooks for known failure modes; link them from alerts."),
         ),
         processes=(
             {"name": "Incident", "archetype": "doctrine",
              "stages": ["detect", "triage", "mitigate", "resolve", "review"],
              "transitions": [["detect", "triage"], ["triage", "mitigate"], ["mitigate", "resolve"],
                              ["resolve", "review"], ["mitigate", "triage"]],
              "gates": ["review"]},
         )),
    Pack("cost-optimization", "platform", "Cost optimization (FinOps)",
         "Treat spend as an engineering metric.", (
             ("measure-spend", "Measure spend",
              "Attribute cost to teams/services with tagging; you can't optimize what you can't see."),
             ("rightsizing", "Rightsize",
              "Match resources to real usage; reclaim idle and over-provisioned capacity."),
             ("autoscale", "Autoscale",
              "Scale with demand; don't pay peak prices for trough load."),
             ("budgets-alerts", "Budgets & alerts",
              "Set budgets per team/service and alert on anomalous spend early."),
         )),
    Pack("release-management", "platform", "Release management",
         "Ship versions predictably.", (
             ("semver", "Semantic versioning",
              "Communicate change intent through versions; breaking changes bump major."),
             ("changelogs", "Keep a changelog",
              "Record notable changes per release so consumers can upgrade with confidence."),
             ("feature-flags", "Feature flags",
              "Decouple deploy from release; dark-launch and ramp behind flags."),
             ("deprecation", "Deprecation policy",
              "Announce, provide a migration path, and set a sunset date before removing."),
         )),

    # ── admin tier ──────────────────────────────────────────────────────────
    Pack("compliance-frameworks", "admin", "Compliance frameworks",
         "Map controls to a framework and keep evidence.", (
             ("control-mapping", "Map controls",
              "Map each framework control (SOC2/ISO/HIPAA/GDPR) to a concrete, owned safeguard."),
             ("evidence", "Collect evidence continuously",
              "Automate evidence capture; an audit should be a query, not a scramble."),
             ("audit-cadence", "Audit cadence",
              "Review controls on a schedule; treat gaps as tracked, owned work items."),
         ),
         artifacts=(
             {"kind": "agent", "layer": "factory", "namespace": "org/compliance", "content":
              "control-mapper: for a change, identify affected controls and confirm evidence "
              "exists; flag unmapped or unevidenced controls."},
         )),
    Pack("risk-management", "admin", "Risk management",
         "Make risk explicit and owned.", (
             ("risk-register", "Risk register",
              "Maintain a register: likelihood, impact, owner, and mitigation for each risk."),
             ("threat-modeling", "Threat modeling",
              "Threat-model significant changes; ask what can go wrong before it does."),
             ("risk-acceptance", "Explicit acceptance",
              "Accepted risks are recorded, time-boxed, and signed off by an accountable owner."),
         )),
    Pack("data-privacy", "admin", "Data privacy",
         "Handle personal data lawfully and minimally.", (
             ("data-minimization", "Minimize",
              "Collect only what you need, for only as long as you need it."),
             ("retention", "Retention policy",
              "Define and enforce retention; delete on schedule, not never."),
             ("pii-handling", "Handle PII carefully",
              "Classify, encrypt, and restrict access to personal data; log access."),
             ("dsar", "Data-subject requests",
              "Have a process to find, export, and erase a subject's data on request."),
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


def pack_detail(session: Session, key: str) -> dict | None:
    """A pack's full contents — examples of what enabling it seeds: standards,
    example processes, and governed policy artifacts. Read-only preview."""
    pack = pack_by_key(key)
    if pack is None:
        return None
    enabled = (session.get(PackState, key) or PackState(key=key)).enabled
    return {
        "key": pack.key, "role": pack.role, "title": pack.title,
        "description": pack.description, "enabled": enabled,
        "standards": [{"topic": t, "title": ti, "body": b} for t, ti, b in pack.standards],
        "processes": [{"name": s["name"], "archetype": s.get("archetype", ""),
                       "stages": s.get("stages", [])} for s in pack.processes],
        "artifacts": [{"kind": a.get("kind", "rule"), "effect": a.get("effect", "allow"),
                       "role": a.get("role", "*"), "action": a.get("action", "*"),
                       "resource": a.get("resource", "*"), "namespace": a.get("namespace", ""),
                       "content": a.get("content", "")} for a in pack.artifacts],
    }


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

    if not session.exec(select(Policy).where(Policy.pack == key)).first():  # idempotent
        for a in pack.artifacts:
            create_policy(session, a.get("effect", "allow"), user.id, kind=a.get("kind", "rule"),
                          role=a.get("role", "*"), action=a.get("action", "*"),
                          resource=a.get("resource", "*"), strict=a.get("strict", False),
                          content=a.get("content", ""), namespace=a.get("namespace", ""),
                          layer=a.get("layer", "charter"), pack=key)

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
    for pol in session.exec(select(Policy).where(Policy.pack == key)):
        session.delete(pol)
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
