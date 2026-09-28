"""The ladder — where a rule is carried.

Write "money is Decimal" in `AGENTS.md` and you have **rung 0**, which is prose,
and prose is a request. Write a predicate that refuses the write and you have
rung 2, which is a guarantee. Same rule, same words, different thing entirely.

| rung | carried by | sees |
|---|---|---|
| 0 | prose in the charter | nothing. It asks |
| 1 | the tool grant | function ids, before any call |
| 2 | a hook on the call | the arguments, before the write lands |
| 3 | a callback in the turn | the call, and it may hold it for a person |
| 4 | the delivery gate | the finished diff, before the commit |
| 5 | CI | the merged tree, after everybody left |

Two things follow, and both are the point.

**A rung is a place, not a strictness.** Rung 3 sees a call and never a diff;
rung 4 sees a diff and never the call. Neither can see what the other sees, so a
rule that matters names both.

**Climbing costs something.** Rung 0 is free and enforces nothing. Rung 2 needs
a predicate somebody writes and maintains. Rung 5 catches everything, and it
catches it after everybody has gone home. Pick the cheapest rung that can
actually see the thing your rule is about.

Capabilities climb the same ladder in the other direction: a constraint
*withholds* a function, a capability *grants* one. They join at rung 1, which is
why `withheld()` is the one number both sides exist to produce.
"""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass, field

from sqlmodel import Session, select

from .models import Constraint, now_iso

CONSTRAINT, CAPABILITY = "constraint", "capability"

# What each rung can actually see. Stated here because "promote this to rung 4"
# is a decision somebody has to make with the trade-off in front of them.
RUNGS: dict[int, str] = {
    0: "prose in the charter — sees nothing, and asks",
    1: "the tool grant — function ids, before any call",
    2: "a hook on the call — the arguments, before the write lands",
    3: "a callback in the turn — the call, and it may hold it for a person",
    4: "the delivery gate — the finished diff, before the commit",
    5: "CI — the merged tree, after everybody left",
}

# Which rungs this product carries itself. Rung 2 is the target repository's own
# commit hook and rung 5 is its CI, so both are real and neither is ours.
OURS = (0, 1, 3, 4)


@dataclass(frozen=True)
class Verdict:
    """What the ladder said about one call or one diff."""

    refused: bool = False
    why: str = ""
    rule: str = ""
    rung: int = 0

    @property
    def allowed(self) -> bool:
        return not self.refused


# --- predicates -------------------------------------------------------------
# A rule becomes mechanical by naming a predicate. They are **registered**, not
# loaded from a file: dropping a .py into a directory is right for a kit you
# clone and own, and is arbitrary code execution as a feature in a multi-user
# server (see PLAN-3.0 §9.3).

PREDICATES: dict[str, dict] = {}


def predicate(name: str, *, about: str, sees: str = "args"):
    """Register a predicate. `sees` is `args` (rung 3) or `diff` (rung 4)."""
    def wrap(fn):
        PREDICATES[name] = {"fn": fn, "about": about, "sees": sees}
        return fn
    return wrap


_SECRETS = re.compile(
    r"(AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----|"
    r"(?:api[_-]?key|secret|password|token)\s*[=:]\s*['\"]?[A-Za-z0-9/+_-]{16,})",
    re.I)


@predicate("no-secrets", about="No credentials in source.", sees="args")
def _no_secrets(*, args: dict, **_) -> str:
    """"" to allow, else why it was refused — in the rule's own words."""
    text = _flatten(args)
    return "a credential must not be written into source" if _SECRETS.search(text) else ""


@predicate("no-force-push", about="Never rewrite published history.", sees="args")
def _no_force_push(*, args: dict, **_) -> str:
    text = _flatten(args).lower()
    if "push" in text and ("--force" in text or "-f " in text):
        return "force-pushing rewrites history somebody else may have pulled"
    return ""


@predicate("no-secrets-in-diff", about="No credentials in the diff.", sees="diff")
def _no_secrets_in_diff(*, diff: str, **_) -> str:
    added = "\n".join(l for l in (diff or "").splitlines() if l.startswith("+"))
    return "the diff adds a credential" if _SECRETS.search(added) else ""


@predicate("no-migration-without-downgrade",
           about="Every migration ships its reverse.", sees="diff")
def _migration_reverse(*, diff: str, **_) -> str:
    added = "\n".join(l for l in (diff or "").splitlines() if l.startswith("+"))
    if "MIGRATIONS" in added and "DOWNGRADES" not in added:
        return "a migration without its reverse cannot be rolled back"
    return ""


def _flatten(value) -> str:
    if isinstance(value, dict):
        return " ".join(_flatten(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return " ".join(_flatten(v) for v in value)
    return str(value)


# --- the rules --------------------------------------------------------------

def add(session: Session, text: str, *, layer: str, rung: int, author_id: str,
        side: str = CONSTRAINT, predicate_name: str = "",
        withholds: list[str] | None = None, scope: str = "*") -> Constraint:
    """Put a rule on the ladder.

    A rung it cannot be carried at is refused: rung 2 and 3 need a predicate,
    and rung 1 needs something to withhold. Storing a rule at a rung nothing
    enforces is how a system ends up believing it is protected.
    """
    if rung not in RUNGS:
        raise ValueError(f"rung must be one of {sorted(RUNGS)}")
    if rung in (2, 3, 4) and not predicate_name:
        raise ValueError(
            f"rung {rung} is carried by a predicate — {RUNGS[rung]}. "
            "Give it one, or keep the rule at rung 0 until somebody writes it")
    if predicate_name and predicate_name not in PREDICATES:
        raise ValueError(f"unknown predicate: {predicate_name!r} "
                         f"(have {', '.join(sorted(PREDICATES))})")
    if rung == 1 and not withholds:
        raise ValueError("rung 1 is the grant — say which tools it withholds")

    rule = Constraint(text=text, layer=layer, rung=rung, side=side,
                      predicate=predicate_name, withholds=list(withholds or []),
                      scope=scope or "*", author_id=author_id)
    session.add(rule)
    session.commit()
    session.refresh(rule)
    return rule


def rules(session: Session, *, side: str | None = None,
          enabled_only: bool = True) -> list[Constraint]:
    stmt = select(Constraint).order_by(Constraint.rung.desc(), Constraint.created_at)
    rows = list(session.exec(stmt))
    if side is not None:
        rows = [r for r in rows if r.side == side]
    if enabled_only:
        rows = [r for r in rows if r.enabled]
    return rows


def withheld(session: Session, *, phase: str = "", scope: str = "") -> tuple[str, ...]:
    """**Rung 1**: the tools a phase must not be handed.

    The one number both ladders exist to produce — a constraint withholds a
    function, a capability grants one, and this is the net.
    """
    out: set[str] = set()
    for rule in rules(session):
        if rule.rung != 1 or not _in_scope(rule.scope, phase or scope):
            continue
        if rule.side == CONSTRAINT:
            out |= set(rule.withholds or [])
        else:
            out -= set(rule.withholds or [])    # a capability gives one back
    return tuple(sorted(out))


def evaluate(session: Session, *, tool: str, args: dict,
             actor_id: str = "") -> Verdict:
    """**Rung 3**: a callback inside the turn, refusing in the rule's own words.

    Called by `pipeline/middleware.py` around every tool call. Deterministic —
    the ladder decides what a *rule* says; a person is asked by the approval
    gate, and neither pretends to be the other.
    """
    for rule in rules(session):
        if rule.rung != 3 or not _in_scope(rule.scope, tool):
            continue
        spec = PREDICATES.get(rule.predicate)
        if spec is None or spec["sees"] != "args":
            continue
        why = spec["fn"](args=args, tool=tool, actor_id=actor_id)
        if why:
            return Verdict(refused=True, why=f"{why} ({rule.text})",
                           rule=rule.id, rung=3)
    return Verdict()


def gate(session: Session, *, diff: str, scope: str = "") -> Verdict:
    """**Rung 4**: the delivery gate, over the finished diff.

    Sees what no rung below it can: rung 3 sees a call and never the diff, and a
    commit message, a pull request body and a reply are not part of any diff, so
    nothing below has seen them either.
    """
    for rule in rules(session):
        if rule.rung != 4 or not _in_scope(rule.scope, scope):
            continue
        spec = PREDICATES.get(rule.predicate)
        if spec is None or spec["sees"] != "diff":
            continue
        why = spec["fn"](diff=diff, scope=scope)
        if why:
            return Verdict(refused=True, why=f"{why} ({rule.text})",
                           rule=rule.id, rung=4)
    return Verdict()


def _in_scope(pattern: str, value: str) -> bool:
    if not pattern or pattern == "*":
        return True
    return fnmatch.fnmatch(value or "", pattern)


# --- moving a rule ----------------------------------------------------------

@dataclass(frozen=True)
class Move:
    """A proposed change of rung, and what it would take."""

    rule_id: str
    frm: int
    to: int
    direction: str               # promotion | demotion
    needs_predicate: bool = False
    why: str = ""

    @property
    def is_promotion(self) -> bool:
        return self.direction == "promotion"


def plan_move(session: Session, rule_id: str, to: int) -> Move:
    """What moving this rule would mean. Pure — nothing is changed."""
    rule = session.get(Constraint, rule_id)
    if rule is None:
        raise ValueError(f"unknown rule: {rule_id!r}")
    if to not in RUNGS:
        raise ValueError(f"rung must be one of {sorted(RUNGS)}")

    direction = "promotion" if to > rule.rung else "demotion"
    return Move(rule_id=rule_id, frm=rule.rung, to=to, direction=direction,
                needs_predicate=(to in (2, 3, 4) and not rule.predicate),
                why=RUNGS[to])


def move(session: Session, rule_id: str, to: int, *, approver_id: str,
         predicate_name: str = "") -> Constraint:
    """Carry a rule at a different rung.

    **Promotion and demotion are not symmetric**, and the asymmetry is the
    safety property. A promotion adds enforcement, so it needs one approver and
    the factory can implement it. A demotion *removes* enforcement — it is the
    one move that makes the system weaker, so it never runs unattended and the
    factory never performs it (see PLAN-3.0 §4.1). Both are audited by the
    caller, which owns the sink.
    """
    planned = plan_move(session, rule_id, to)
    rule = session.get(Constraint, rule_id)

    if planned.needs_predicate and not predicate_name:
        raise ValueError(
            f"rung {to} is carried by a predicate — {RUNGS[to]}. "
            "A rule promoted to a rung nothing enforces is worse than one left "
            "at rung 0, because it looks enforced")
    if predicate_name:
        if predicate_name not in PREDICATES:
            raise ValueError(f"unknown predicate: {predicate_name!r}")
        rule.predicate = predicate_name

    rule.rung = to
    rule.moved_by = approver_id
    rule.moved_at = now_iso()
    session.add(rule)
    session.commit()
    session.refresh(rule)
    return rule


def view(session: Session) -> dict:
    """Both ladders, plus the net grant — what `GET /ladder` returns."""
    all_rules = rules(session, enabled_only=False)
    return {
        "rungs": [{"rung": n, "sees": RUNGS[n], "ours": n in OURS} for n in sorted(RUNGS)],
        "constraints": [_brief(r) for r in all_rules if r.side == CONSTRAINT],
        "capabilities": [_brief(r) for r in all_rules if r.side == CAPABILITY],
        "withheld": list(withheld(session)),
        "predicates": [{"name": n, "about": p["about"], "sees": p["sees"]}
                       for n, p in sorted(PREDICATES.items())],
    }


def _brief(rule: Constraint) -> dict:
    return {"id": rule.id, "text": rule.text, "layer": rule.layer,
            "rung": rule.rung, "sees": RUNGS.get(rule.rung, ""),
            "predicate": rule.predicate, "withholds": list(rule.withholds or []),
            "scope": rule.scope, "enabled": rule.enabled,
            "mechanical": bool(rule.predicate) or rule.rung == 1}
