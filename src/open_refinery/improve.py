"""The improve lane — what went wrong, and what would have prevented it.

One lane over the audit trail, replacing four modules that each read it for a
slice: `debt` scored areas, `analysis` found contradictions, `anomalies` watched
behaviour, `postmortem` explained one item. They shared a shape and disagreed
about vocabulary.

It reads two things: the **rules** (contradictions, injection text, denial
spikes) and the **runs** (stages that keep failing, revisions burned to no end,
holds nobody clears). The second half is what makes "self-improving" mean
anything — a stage that fails on every repo is a fact about the workflow, and it
is already sitting in `run_steps` waiting to be counted.

Two rules, both borrowed from ghola and both load-bearing:

- **Evidence or it is dropped.** Every finding names the events it came from. A
  finding that cannot be traced is discarded rather than repaired — a lane that
  always finds three things is one nobody believes by the third time.
- **Nothing is applied.** A finding becomes a *proposal*, and a proposal goes
  through the same approval path as any other change (§4.1). The lane that
  proposes changes to the rules does not get to be the one thing that escapes
  the gate everything else goes through.

Read-only, and pure apart from the queries.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from sqlmodel import Session, select

from .models import Event, Policy, User

# What a finding costs the score it appears in. Ordered by how much a human
# would care, not by how easy it is to detect.
WEIGHT = {"prompt_injection": 20, "contradiction": 15, "denial_spike": 12,
          "stage_failure": 15, "stalled_hold": 12, "revision_churn": 10,
          "dead_rule": 8, "over_norm": 8, "mass_change": 10, "redundant": 3}

_INJECTION = [re.compile(p, re.I) for p in (
    r"ignore (all |any )?previous instructions",
    r"disregard (the )?(above|prior|system)",
    r"you are now",
    r"reveal (your )?(system )?prompt",
)]


@dataclass
class Finding:
    """One thing that went wrong, and the events proving it."""

    kind: str
    detail: str
    severity: str = "medium"
    evidence: tuple[str, ...] = ()        # event / policy ids
    suggestion: str = ""

    @property
    def traced(self) -> bool:
        """Whether this finding can be traced to something a person can open."""
        return bool(self.evidence)

    def as_dict(self) -> dict:
        return {"kind": self.kind, "detail": self.detail, "severity": self.severity,
                "evidence": list(self.evidence), "suggestion": self.suggestion}


# --- the detectors ---------------------------------------------------------

def _overlap(a: str, b: str) -> bool:
    return a == b or "*" in (a, b)


def contradictions(session: Session) -> list[Finding]:
    """Two rules on the same action+resource with opposite effects — so which
    one applies depends on evaluation order rather than on anyone's intent."""
    rules = list(session.exec(select(Policy)))
    out = []
    for i, a in enumerate(rules):
        for b in rules[i + 1:]:
            if (a.effect != b.effect and _overlap(a.action, b.action)
                    and _overlap(a.resource, b.resource)):
                out.append(Finding(
                    "contradiction",
                    f"{a.effect} and {b.effect} both match {a.action}:{a.resource}",
                    severity="high", evidence=(a.id, b.id),
                    suggestion="delete one, or make the narrower rule strict"))
    return out


def injections(session: Session) -> list[Finding]:
    """Prompt-injection shaped text stored in a rule the harness will read."""
    out = []
    for rule in session.exec(select(Policy)):
        text = rule.content or ""
        if any(rx.search(text) for rx in _INJECTION):
            out.append(Finding(
                "prompt_injection",
                f"rule {rule.id[:8]} contains instruction-override text",
                severity="high", evidence=(rule.id,),
                suggestion="a rule the agent reads must not try to reprogram it"))
    return out


def denial_spikes(session: Session, *, threshold: int = 5) -> list[Finding]:
    """One actor refused repeatedly — either a rule is wrong or something is
    probing it. Both are worth a person's attention."""
    denied = [e for e in session.exec(select(Event)) if e.recipe == "denied"]
    per_actor = Counter(e.actor for e in denied)
    out = []
    for actor, n in per_actor.items():
        if n >= threshold:
            ids = tuple(e.artifact_id for e in denied if e.actor == actor)[:10]
            out.append(Finding(
                "denial_spike", f"{actor} was refused {n} times",
                severity="high" if n >= threshold * 2 else "medium",
                evidence=ids,
                suggestion="check whether the rule is wrong before assuming the actor is"))
    return out


def over_norm(session: Session, *, factor: int = 3) -> list[Finding]:
    """An agent doing far more than its peers. Not wrong by itself — worth
    looking at, which is exactly what a finding is for."""
    agents = {u.id for u in session.exec(select(User)) if u.kind == "agent"}
    if len(agents) < 2:
        return []
    counts = Counter(e.actor for e in session.exec(select(Event)) if e.actor in agents)
    if not counts:
        return []
    average = sum(counts.values()) / len(counts)
    return [Finding("over_norm",
                    f"{actor} produced {n} events against an average of {average:.0f}",
                    evidence=(actor,),
                    suggestion="confirm the workload is intended, or cap it with a quota")
            for actor, n in counts.items() if n > average * factor]


# --- the factory watching itself -------------------------------------------
# The detectors above read the *rules*. These read the **runs** — what the
# factory actually did. That is the half that makes "self-improving" mean
# something: a stage that fails on every repo is a fact about the workflow, and
# it is sitting in `run_steps` waiting to be counted.


def stage_failures(session: Session, *, threshold: int = 3) -> list[Finding]:
    """The same stage erroring across several runs.

    One run failing is a bad ticket. The same stage failing on three is the
    workflow, and the difference is worth saying out loud — a team debugging
    ticket by ticket will not notice the pattern that a count makes obvious.
    """
    from .models import RunStep

    bad = [s for s in session.exec(select(RunStep)) if s.outcome == "error"]
    per_stage: dict[str, list] = {}
    for step in bad:
        per_stage.setdefault(step.stage, []).append(step)

    out = []
    for stage, steps in per_stage.items():
        runs = {s.run_id for s in steps}
        if len(runs) < threshold:
            continue
        out.append(Finding(
            "stage_failure",
            f"stage {stage!r} errored in {len(runs)} runs: {steps[-1].why[:120]}",
            severity="high" if len(runs) >= threshold * 2 else "medium",
            evidence=tuple(s.id for s in steps[:10]),
            suggestion=f"fix what {stage} depends on, or make the stage optional — "
                       "a stage that always fails is a gate nobody chose"))
    return out


def revision_churn(session: Session, *, threshold: int = 2) -> list[Finding]:
    """Runs that used up their revisions and still failed.

    The contract was never met, so the model was asked the same thing until the
    budget ran out. Usually the contract is unreachable, not the model unable.
    """
    from .models import Run

    burned = [r for r in session.exec(select(Run))
              if r.outcome == "failed" and r.revisions >= threshold]
    if not burned:
        return []
    return [Finding(
        "revision_churn",
        f"{len(burned)} runs exhausted their revisions and failed",
        severity="medium", evidence=tuple(r.id for r in burned[:10]),
        suggestion="check the stage contract is reachable before raising "
                   "max_revisions — paying for more attempts at an impossible "
                   "check is the expensive way to fail")]


def stalled_holds(session: Session, *, days: int = 2) -> list[Finding]:
    """Runs held for a person who never came.

    A gate nobody clears is not oversight, it is a queue. Naming it is the only
    way the org finds out the approver moved team.
    """
    from datetime import datetime, timedelta, timezone

    from .models import Run

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    stuck = []
    for run in session.exec(select(Run)):
        if not run.held or run.outcome:
            continue
        try:
            when = datetime.fromisoformat(run.updated_at)
        except ValueError:
            continue
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        if when < cutoff:
            stuck.append(run)

    if not stuck:
        return []
    return [Finding(
        "stalled_hold",
        f"{len(stuck)} runs have been waiting on a person for over {days} days",
        severity="high", evidence=tuple(r.id for r in stuck[:10]),
        suggestion="find out who owns that gate, or lower the stage's oversight "
                   "— a hold nobody clears is a queue wearing a gate's name")]


DETECTORS = (contradictions, injections, denial_spikes, over_norm,
             stage_failures, revision_churn, stalled_holds)


# --- the lane --------------------------------------------------------------

def findings(session: Session) -> list[Finding]:
    """Every finding that can be traced to evidence. Untraceable ones are
    **dropped** rather than reported — see the module docstring."""
    out: list[Finding] = []
    for detect in DETECTORS:
        out += [f for f in detect(session) if f.traced]
    return out


def score(session: Session) -> dict:
    """A health score out of 100, and what is costing it.

    Deliberately one number over the whole system rather than one per area: the
    three-area split it replaces invited a team to celebrate a good `charter`
    score while the factory refused every run.
    """
    found = findings(session)
    cost = sum(WEIGHT.get(f.kind, 5) for f in found)
    return {"score": max(0, min(100, 100 - cost)),
            "findings": [f.as_dict() for f in found],
            "total": len(found)}


def proposals(session: Session) -> list[dict]:
    """Findings as proposals — what to put in front of a person.

    **Nothing here is applied.** Each carries the evidence it came from so a
    reviewer can open the events rather than take the lane's word for it.
    """
    return [{"title": f.detail, "kind": f.kind, "severity": f.severity,
             "suggestion": f.suggestion, "evidence": list(f.evidence)}
            for f in findings(session) if f.suggestion]


def propose_finding(session: Session, kind: str, detail: str, *, repo_id: str,
                    proposer_id: str):
    """Turn one finding into a proposal that goes through the ordinary gate.

    The caller names the finding; **the server supplies the evidence.** Taking
    the evidence from the request would let anyone attach a plausible list of
    ids to an invented problem, which is the one thing "evidence or it is
    dropped" is meant to prevent. A finding that is no longer there is refused,
    because a proposal outliving its evidence is exactly the stale request a
    reviewer cannot check.
    """
    from .approval_workflows import propose

    match = next((f for f in findings(session)
                  if f.kind == kind and f.detail == detail), None)
    if match is None:
        raise LookupError(
            f"no current finding {kind!r} matching that detail — it may have "
            "been fixed already, or the evidence may have aged out")

    return propose(session, "work", "create", {
        "repo_id": repo_id,
        "title": match.detail,
        "spec": f"{match.detail}\n\n{match.suggestion}",
        "finding": match.kind,
        "evidence": list(match.evidence),
    }, "platform", proposer_id)
