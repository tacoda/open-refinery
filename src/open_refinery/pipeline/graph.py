"""The stage machine — where a run goes next, and why.

`advance` is a pure function of three dicts: the run, the graph, and what just
happened. Every branch the factory can take is decidable here, so the whole of
its behaviour is testable without an agent, a worktree or a forge. The
alternative — discovering what the pipeline does by sending real work through
it — is what makes a factory expensive to change.

The result is a `Move`: where to go, why, and what to record. Nothing here
performs anything.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .spec import BLOCKED, Graph, Stage

# What running a stage produced.
OK, REFUSED, ERROR, BLOCKED_ON_PERSON = "ok", "refused", "error", "blocked"
OUTCOMES = (OK, REFUSED, ERROR, BLOCKED_ON_PERSON)


@dataclass(frozen=True)
class Result:
    """What a stage's work came back with."""

    outcome: str = OK
    # The refusal's own words. Compared verbatim against the last one, because
    # a gate repeating itself has already shown its complaint is not about the
    # diff — a second attempt costs a turn and learns nothing.
    reason: str = ""
    # For a stage watching a pull request: `merge`, `close`, `comment`.
    event: str = ""
    produced: tuple[str, ...] = ()
    error: str = ""
    # What the stage spent, in model units. An action spends nothing; a turn
    # reports what the provider billed. Recorded on the step and charged to the
    # budgets the run answers to.
    units: int = 0


@dataclass(frozen=True)
class Move:
    """Where the run goes, and what to write down."""

    to: str
    why: str
    revisions: int = 0
    reason: str = ""             # the run's new reason: "", revision, rework
    last_refusal: str = ""
    skipped: bool = False
    held: bool = False           # waiting on a person

    @property
    def is_terminal_move(self) -> bool:
        return self.to in ("landed", "closed", "failed")


def _run_reason(run: dict) -> str:
    return str(run.get("reason") or "")


def should_skip(stage: Stage, run: dict) -> str:
    """Why this stage is being skipped, or "" to run it.

    Three different questions that look alike, which is why they are separate
    fields and not one `enabled` flag:
    """
    reason = _run_reason(run)
    if reason and reason in stage.skip_when:
        # A gate's complaint and a reviewer's comment are already briefs.
        return f"skipped on {reason}"

    if stage.opt_in and stage.name not in (run.get("opt_in") or ()):
        # Runs only when a run asks. Most work arrives as a spec somebody wrote.
        return "not opted in"

    if stage.optional and stage.name in (run.get("skip") or ()):
        # Runs unless a run turns it off — the opposite default, on purpose.
        return "turned off for this run"

    missing = [need for need in stage.requires
               if need not in (run.get("document") or {})]
    if missing:
        return f"missing {', '.join(missing)}"
    return ""


def _refusal_target(stage: Stage, run: dict, result: Result) -> Move | None:
    """Where a refusal sends the run, if anywhere."""
    if not stage.on_refusal:
        return None

    revisions = int(run.get("revisions") or 0)
    if revisions >= stage.max_revisions:
        return Move("failed", f"{stage.name} refused {revisions + 1} times", revisions=revisions,
                    last_refusal=result.reason)

    if stage.stop_when_identical and result.reason and result.reason == run.get("last_refusal"):
        return Move("failed",
                    f"{stage.name} repeated the same refusal — it is not about the diff",
                    revisions=revisions, last_refusal=result.reason)

    return Move(stage.on_refusal, f"{stage.name} refused",
                revisions=revisions + 1, reason="revision",
                last_refusal=result.reason)


def advance(run: dict, graph: Graph, result: Result) -> Move:
    """Where the run goes after `result` at its current stage.

    `run` carries: `stage`, `reason`, `revisions`, `last_refusal`, `document`
    (what has been produced), and optionally `skip` / `opt_in`.
    """
    here = str(run.get("stage") or graph.first)
    if graph.is_terminal(here):
        return Move(here, "already finished")

    stage = graph.stage(here)
    if stage is None:
        return Move("failed", f"{here!r} is not a stage in {graph.name!r}")

    revisions = int(run.get("revisions") or 0)
    carry = {"revisions": revisions, "reason": _run_reason(run),
             "last_refusal": str(run.get("last_refusal") or "")}

    if result.outcome == BLOCKED_ON_PERSON:
        return Move(here, f"{here} is waiting on a person", held=True, **carry)

    if result.outcome == REFUSED:
        moved = _refusal_target(stage, run, result)
        if moved is not None:
            return moved
        return Move("failed", f"{stage.name} refused and has no refusal path",
                    revisions=revisions, last_refusal=result.reason)

    if result.outcome == ERROR:
        if stage.on_error == "fail":
            return Move("failed", f"{stage.name} failed: {result.error or 'no detail'}",
                        **carry)
        # `continue` is for a stage whose absence is survivable — a plan turn
        # that fails hands over an empty plan rather than failing the run.
        return Move(_next_of(stage, graph), f"{stage.name} failed, continuing", **carry)

    # Success. A stage watching a pull request branches on what the human did.
    if stage.outcomes:
        for kind, dest in stage.outcomes:
            if kind == result.event:
                reason = "rework" if kind == "comment" else ""
                return Move(dest, f"pull request {kind}",
                            revisions=revisions, reason=reason,
                            last_refusal=carry["last_refusal"])
        return Move(here, f"{here} is still waiting", held=True, **carry)

    return Move(_next_of(stage, graph), f"{stage.name} finished",
                revisions=revisions, reason="", last_refusal=carry["last_refusal"])


def _next_of(stage: Stage, graph: Graph) -> str:
    return stage.next or "failed"


def plan_next(run: dict, graph: Graph) -> Move:
    """What to do *before* running the current stage: skip it, hold it for a
    person, or go ahead.

    Separate from `advance` because they answer different questions — this one
    is asked on arrival, that one on departure. Folding them together is how a
    skipped stage ends up also being approved.
    """
    here = str(run.get("stage") or graph.first)
    if graph.is_terminal(here):
        return Move(here, "already finished")

    stage = graph.stage(here)
    if stage is None:
        return Move("failed", f"{here!r} is not a stage in {graph.name!r}")

    carry = {"revisions": int(run.get("revisions") or 0),
             "reason": _run_reason(run),
             "last_refusal": str(run.get("last_refusal") or "")}

    why = should_skip(stage, run)
    if why:
        return Move(_next_of(stage, graph), f"{stage.name}: {why}", skipped=True, **carry)

    if stage.approve and not run.get("approved_at"):
        # Cheaper than gating the diff: a wrong approach is caught before the
        # next phase spends its turn cap.
        return Move(here, f"{stage.name} needs approval before it runs",
                    held=True, **carry)

    return Move(here, f"{stage.name} is ready", **carry)


def walk(graph: Graph, results: dict[str, Result] | None = None,
         *, limit: int = 100) -> list[str]:
    """The stages a run would visit, for `pipeline check` and the canvas.

    Bounded, because a pipeline with a cycle and no revision cap is exactly the
    thing this is meant to show you *before* you pay for a run.
    """
    results = results or {}
    run: dict = {"stage": graph.first, "document": {}, "revisions": 0}
    seen: list[str] = []

    for _ in range(limit):
        here = run["stage"]
        seen.append(here)
        if graph.is_terminal(here):
            break
        stage = graph.stage(here)
        produced = dict(run["document"])
        if stage is not None:
            produced.update({key: True for key in stage.produces})
        result = results.get(here, Result(outcome=OK))
        moved = advance({**run, "document": produced}, graph, result)
        if moved.held:
            break
        run = {"stage": moved.to, "document": produced,
               "revisions": moved.revisions, "reason": moved.reason,
               "last_refusal": moved.last_refusal}
    return seen
