"""Compliance evidence packs — turn the audit trail, policies, versioned history,
and attestations into a framework-mapped bundle an auditor can read.

A pack answers, per control: *is there evidence this control is enforced?* — the
tamper-evident audit chain, the role authorization matrix, versioned policy
history + approval workflows, quality-gate attestations, and enforcement mode.
Framework maps are representative starters; orgs extend them.
"""

from __future__ import annotations

from sqlmodel import Session, func, select

from .models import (
    ApprovalWorkflow,
    Attestation,
    Event,
    Policy,
    PolicyVersion,
    User,
)
from .policies import enforcement_mode
from .store import verify_chain

FRAMEWORKS = ("soc2", "iso27001", "hipaa", "gdpr")


def _facts(session: Session) -> dict:
    """Raw evidence gathered once, referenced by control mappings."""
    def count(model):
        return session.exec(select(func.count()).select_from(model)).one()
    recipes: dict[str, int] = {}
    for e in session.exec(select(Event.recipe)):
        recipes[e] = recipes.get(e, 0) + 1
    chain = verify_chain(session)
    rules = list(session.exec(select(Policy).where(Policy.kind == "rule")))
    return {
        "chain": chain,
        "enforcement_mode": enforcement_mode(session),
        "policies_total": count(Policy),
        "rules_total": len(rules),
        "strict_rules": sum(1 for p in rules if p.strict),
        "policy_versions": count(PolicyVersion),
        "approval_workflows": count(ApprovalWorkflow),
        "attestations": count(Attestation),
        "audit_events": count(Event),
        "denials": recipes.get("denied", 0),
        "approvals": recipes.get("approval", 0),
        "users": count(User),
        "recipes": recipes,
    }


def _met(cond: bool, partial: bool = False) -> str:
    return "met" if cond else ("partial" if partial else "attention")


# control_id → (title, requirement, evaluator(facts) → (status, evidence dict))
def _controls(f: dict) -> dict:
    chain_ok = f["chain"].get("ok")
    return {
        "access-control": ("Access control", "Only authorized roles perform actions",
            (_met(f["rules_total"] > 0), {"enforcement_mode": f["enforcement_mode"],
             "rules": f["rules_total"], "strict_rules": f["strict_rules"]})),
        "audit-logging": ("Audit logging", "Actions are logged in a tamper-evident trail",
            (_met(bool(chain_ok) and f["audit_events"] > 0, partial=f["audit_events"] > 0),
             {"events": f["audit_events"], "chain_intact": chain_ok, "chain_head": f["chain"].get("head")})),
        "change-management": ("Change management", "Governance changes are versioned + approved",
            (_met(f["policy_versions"] > 0, partial=True),
             {"policy_versions": f["policy_versions"], "approval_workflows": f["approval_workflows"]})),
        "monitoring": ("Monitoring & enforcement", "Violations are blocked and recorded",
            (_met(f["enforcement_mode"] == "strict", partial=f["denials"] >= 0),
             {"enforcement_mode": f["enforcement_mode"], "denials_recorded": f["denials"]})),
        "quality-gates": ("Quality gates / verification", "Required checks attested before release",
            (_met(f["attestations"] > 0, partial=True), {"attestations": f["attestations"]})),
    }


# framework → [(control_id, external ref)]
_MAP = {
    "soc2": [("access-control", "CC6.1"), ("audit-logging", "CC7.2"),
             ("change-management", "CC8.1"), ("monitoring", "CC7.3"), ("quality-gates", "CC8.1")],
    "iso27001": [("access-control", "A.9.1"), ("audit-logging", "A.12.4"),
                 ("change-management", "A.12.1.2"), ("monitoring", "A.16.1"), ("quality-gates", "A.14.2")],
    "hipaa": [("access-control", "164.312(a)"), ("audit-logging", "164.312(b)"),
              ("change-management", "164.308(a)(1)"), ("monitoring", "164.308(a)(6)")],
    "gdpr": [("access-control", "Art.32"), ("audit-logging", "Art.30"),
             ("change-management", "Art.5(2)"), ("monitoring", "Art.33")],
}


def evidence_pack(session: Session, framework: str) -> dict:
    if framework not in FRAMEWORKS:
        raise ValueError(f"unknown framework: {framework!r} (expected {FRAMEWORKS})")
    from .models import now_iso
    facts = _facts(session)
    controls_def = _controls(facts)
    controls = []
    for cid, ref in _MAP[framework]:
        title, requirement, (status, evidence) = controls_def[cid]
        controls.append({"control": ref, "id": cid, "title": title,
                         "requirement": requirement, "status": status, "evidence": evidence})
    met = sum(1 for c in controls if c["status"] == "met")
    return {
        "framework": framework, "generated_at": now_iso(),
        "integrity": facts["chain"],  # tamper-evidence of the underlying trail
        "summary": {"controls": len(controls), "met": met,
                    "coverage_pct": round(100 * met / len(controls)) if controls else 0},
        "facts": {k: facts[k] for k in ("enforcement_mode", "rules_total", "strict_rules",
                  "policy_versions", "approval_workflows", "attestations", "audit_events")},
        "controls": controls,
    }
