"""Agent-run post-mortem — assemble a run, deduce a likely root cause, suggest next steps.

A "run" is a work item's lifecycle. This gathers everything recorded about it —
the audit timeline (transitions, invokes/failures, policy **denials**, approvals,
attestations), the latest attestation results, pending approvals, and the repo's
governance signals (imitation surfaces, poison) — then applies simple heuristics
to name the most likely **root cause** and propose concrete **follow-up actions**.

Heuristic, not magic: it reads the recorded facts and points you at them.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime

from sqlmodel import Session

from .analysis import analyze
from .attestations import attestations_for
from .approvals import list_approvals
from .repo_governance import coverage
from .store import query_events
from .work_items import get_work_item

# severity order for choosing the root cause (highest first)
_ORDER = ["policy_denial", "target_failure", "failed_attestation", "rejected", "stalled"]


def _seconds_between(a: str, b: str) -> float:
    return abs((datetime.fromisoformat(b) - datetime.fromisoformat(a)).total_seconds())


def postmortem(session: Session, work_item_id: str) -> dict:
    item = get_work_item(session, work_item_id)
    if item is None:
        raise ValueError(f"unknown work item: {work_item_id!r}")

    events = list(reversed(query_events(session, subject=work_item_id, limit=1000)))  # oldest→newest
    timeline = [{"recipe": e.recipe, "actor": e.actor, "at": e.created_at} for e in events]
    counts = Counter(e.recipe for e in events)
    duration = _seconds_between(events[0].created_at, events[-1].created_at) if len(events) > 1 else 0.0

    atts = attestations_for(session, work_item_id)
    failed_checks = [name for name, ok in atts.items() if not ok]
    pending = [r for r in list_approvals(session, work_item_id=work_item_id) if r.status == "pending"]

    findings: list[dict] = []
    suggestions: list[str] = []

    def add(kind: str, severity: str, detail: str, suggestion: str) -> None:
        findings.append({"type": kind, "severity": severity, "detail": detail})
        suggestions.append(suggestion)

    if counts.get("denied"):
        add("policy_denial", "high",
            f"{counts['denied']} action(s) were blocked by policy enforcement.",
            "Review the blocking rule (Governance › Policies); adjust it or the enforcement mode.")
    if counts.get("invoke-failed"):
        add("target_failure", "high",
            f"{counts['invoke-failed']} target invocation(s) failed.",
            "Check the target's credential and quota; add a failover route for the process/step.")
    if failed_checks:
        add("failed_attestation", "high",
            f"Quality gate check(s) failed: {', '.join(failed_checks)}.",
            f"Fix the failing check(s) — {', '.join(failed_checks)} — then re-attest and retry.")
    if counts.get("change-deny") or counts.get("approval-rejected"):
        add("rejected", "medium", "A change/approval was rejected in review.",
            "Address the reviewer feedback and resubmit the proposal / request.")
    if pending:
        add("stalled", "medium",
            f"{len(pending)} approval request(s) still pending; the run is waiting on a signer.",
            "Approve or reject the pending request (Approvals tab) to unblock the run.")

    # repo-context suggestions (not root-cause, but actionable follow-ups)
    cov = coverage(session, item.repo_id)
    if cov["imitation"]:
        suggestions.append(
            f"Close {cov['imitation']} imitation surface(s) on this repo (Coverage tab): add a backing instruction + gate.")
    poison = [f for f in analyze(session)["findings"] if f["type"] in ("contradiction", "dead")]
    if poison:
        suggestions.append(f"Resolve {len(poison)} governance poison finding(s) (dead / contradicting rules).")

    root = next((f for k in _ORDER for f in findings if f["type"] == k), None)
    root_cause = root["detail"] if root else "No failure signals — the run proceeded cleanly."

    return {
        "work_item_id": work_item_id, "title": item.title, "current_stage": item.current_stage,
        "duration_seconds": round(duration),
        "counts": dict(counts), "timeline": timeline,
        "attestations": atts, "pending_approvals": len(pending),
        "root_cause": root_cause, "findings": findings, "suggestions": suggestions,
    }
