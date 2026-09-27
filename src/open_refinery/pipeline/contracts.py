"""What a check's answer has to look like, and what invalidates it.

**A check that grades itself is not a check.** `prove` claims the software
works and `review` claims the diff is sound, and both claims are worth exactly
what the evidence under them is worth. A contract is how that gets enforced
without asking a model to be honest about its own output.

Two rules do most of the work, and they are the same rule twice:

- **`PROVEN: yes` with no command under it is downgraded to `unproven`.**
  Evidence or it did not happen.
- **An objecting review naming nothing is downgraded.** A verdict of `concerns`
  that points at no file and line is a mood.

And one that matters more than either: **an answer that cannot be parsed is
never read as a pass.** It becomes `unreadable`, which a person looks at. The
failure this prevents is a check whose output format drifted, quietly reading as
approval for weeks.

This absorbs what `attestations.py` did — "a check was attested before entering
this step" and "a check's claim must carry evidence" are the same idea, and this
is the stricter half. Everything here is pure: a contract is a dict and an
answer is a string.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

BUILT_IN: dict[str, dict] = {
    "proven": {
        "marker": "PROVEN:",
        "values": ["yes", "no", "partial"],
        # Never a pass. `unproven` is the honest state for an answer nobody
        # could read, and it is not the same as `no`.
        "unparseable": "unproven",
        "patterns": {
            # A line that ran something. Deliberately syntactic: a model saying
            # it ran a command is not a transcript containing one.
            "evidence": r"^\s*[$>]\s+\S",
        },
        "requires": [
            {"when": ["yes"], "at_least_one": "evidence", "otherwise": "unproven",
             "why": "a proof with no command under it is a claim, not a proof"},
        ],
    },
    "verdict": {
        "marker": "VERDICT:",
        "values": ["pass", "concerns", "blocker"],
        "unparseable": "unreadable",
        "patterns": {
            # A finding names a place. `app.py:9 — …` counts; a paragraph does not.
            "finding": r"^\s*[-*]?\s*\S+\.\w+:\d+",
        },
        "requires": [
            {"when": ["concerns", "blocker"], "at_least_one": "finding",
             "otherwise": "unreadable",
             "why": "an objecting review that names nothing is a mood"},
        ],
    },
}

# Values that mean the pipeline should act rather than carry on.
OBJECTING = frozenset({"concerns", "blocker", "no", "unproven", "unreadable"})


@dataclass(frozen=True)
class Answer:
    """What a check actually said, after the contract has had its say."""

    value: str = ""
    raw: str = ""
    findings: tuple[str, ...] = ()
    evidence: tuple[str, ...] = ()
    downgraded_from: str = ""
    why: str = ""

    @property
    def downgraded(self) -> bool:
        return bool(self.downgraded_from)

    @property
    def objects(self) -> bool:
        """Whether this is a complaint the pipeline should act on."""
        return self.value in OBJECTING

    def as_dict(self) -> dict:
        """Structured, because a persisted result must be queryable rather than
        re-parsed from prose later."""
        return {"value": self.value, "findings": list(self.findings),
                "evidence": list(self.evidence),
                "downgraded_from": self.downgraded_from, "why": self.why}


def contract(name: str, config: dict | None = None) -> dict:
    """One contract: a team's file merged over the built-in, or the built-in."""
    built_in = BUILT_IN.get(name)
    if built_in is None and not config:
        return {}
    return {**(built_in or {}), **(config or {})}


def matches(pattern: str, text: str) -> tuple[str, ...]:
    if not pattern:
        return ()
    rx = re.compile(pattern, re.MULTILINE)
    return tuple(line.strip() for line in text.splitlines() if rx.match(line))


def read(text: str, spec: dict) -> Answer:
    """Parse an answer against a contract, applying every downgrade.

    The marker is looked for at the **start of a line**, so a check that
    mentions `VERDICT:` mid-sentence while explaining itself does not
    accidentally declare one.
    """
    text = str(text or "")
    marker = str(spec.get("marker") or "")
    values = [str(v).lower() for v in (spec.get("values") or [])]
    unparseable = str(spec.get("unparseable") or "unreadable")
    patterns = spec.get("patterns") or {}

    findings = matches(str(patterns.get("finding") or ""), text)
    evidence = matches(str(patterns.get("evidence") or ""), text)

    declared = _declared(text, marker, values)
    if not declared:
        return Answer(value=unparseable, raw=text, findings=findings, evidence=evidence,
                      why=f"no readable {marker or 'verdict'} line")

    found = {"finding": findings, "evidence": evidence}
    for rule in spec.get("requires") or []:
        if declared not in [str(v).lower() for v in (rule.get("when") or [])]:
            continue
        needed = str(rule.get("at_least_one") or "")
        if not found.get(needed):
            return Answer(value=str(rule.get("otherwise") or unparseable), raw=text,
                          findings=findings, evidence=evidence,
                          downgraded_from=declared, why=str(rule.get("why") or ""))

    return Answer(value=declared, raw=text, findings=findings, evidence=evidence)


def _declared(text: str, marker: str, values: list[str]) -> str:
    if not marker:
        return ""
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.upper().startswith(marker.upper()):
            continue
        said = stripped[len(marker):].strip().strip(".").lower()
        for value in values:
            if said == value or said.startswith(value + " "):
                return value
    return ""
