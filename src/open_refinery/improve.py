"""The improve lane — what went wrong, and what would have prevented it.

One lane over the audit trail, replacing four modules that each read it for a
slice: `debt` scored areas, `analysis` found contradictions, `anomalies` watched
behaviour, `postmortem` explained one item. They shared a shape and disagreed
about vocabulary.

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


DETECTORS = (contradictions, injections, denial_spikes, over_norm)


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
