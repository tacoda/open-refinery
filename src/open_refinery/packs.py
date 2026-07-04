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

from .models import PackState, Standard, User
from .policies import PolicyDenied
from .users import at_least


@dataclass(frozen=True)
class Pack:
    key: str
    role: str          # minimum role that may enable/disable it (the layer it serves)
    title: str
    description: str
    standards: tuple[tuple[str, str, str], ...]  # (topic, title, body)


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
             ("remediation-doctrine", "Remediation doctrine (process)",
              "A doctrine process — detect → triage → patch → verify → close, with a feedback loop from verify → patch."),
         )),
    Pack("platform-general", "platform", "Platform",
         "Platform-layer topics.", (
             ("platform-basics", "Platform standards",
              "Govern how work reaches targets: identity, authorization, quotas, audit. The platform governs; it does not do the harness's job."),
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
