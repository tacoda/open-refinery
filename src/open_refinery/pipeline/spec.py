"""The stage graph: what happens, in what order, and what decides.

A pipeline is a set of stages. Each names a **phase** to run (a turn of the
harness) or an **action** to take (something the factory does itself), and says
where to go next. Teams edit this on the canvas or import it as YAML; it lives
in SQLite either way.

Everything here is pure. `parse` turns a dict into a `Graph` or explains why it
cannot, and **explains it in terms of the stage that is wrong** — a validation
error naming a JSON path is a validation error somebody ignores.

Job states are derived from the graph rather than an enum, so a team that adds a
`threat-model` stage gets a `threat-model` state for free, and one that deletes
`prove` leaves no dead state behind.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

# What a stage can do when it is not running a phase. Each is implemented by the
# runner; a name that is neither here nor a known phase is a configuration
# error rather than a silent no-op.
ACTIONS: dict[str, str] = {
    "prepare_workspace": "claim a worktree and run the repo's prepare command",
    "commit_and_push": "the delivery gate, the commit, and the branch",
    "open_pull_request": "publish the work for a human to decide on",
    "watch_pull_request": "poll the forge and react to what the human did",
    "teardown": "release the worktree and run the repo's cleanup command",
}

# States a run can be in that are not stages.
TERMINAL_DEFAULT = ("landed", "closed", "failed")
BLOCKED = "blocked"          # a turn waiting on a person

# What a stage does when the thing it ran refused.
ON_ERROR = ("fail", "continue")

# Reasons a run carries, which a stage may skip on.
REASONS = ("", "revision", "rework")


class GraphError(ValueError):
    """A pipeline that cannot be run as written."""


@dataclass(frozen=True)
class Stage:
    """One step, as declared."""

    name: str
    phase: str = ""
    action: str = ""
    next: str = ""
    model: str = ""              # overrides the pipeline default for this stage

    # Entry and exit criteria against the run document. The interface between
    # stages is a document that accumulates, so what a stage needs and what it
    # owes are both sections of it.
    requires: tuple[str, ...] = ()
    produces: tuple[str, ...] = ()

    # Skip when the run carries one of these reasons. A gate's complaint and a
    # reviewer's comment are already briefs; re-planning would only blur them.
    skip_when: tuple[str, ...] = ()

    # `optional` is opt-OUT: it runs unless a run turns it off. `prove` and
    # `review` are this, because a factory that quietly stopped checking would
    # be worse than one that never checked.
    optional: bool = False
    # `opt_in` is the other half: it runs only when a run asks. `refine` is
    # this, because most work arrives as a spec somebody wrote, and rewriting it
    # would be rewriting their words. Conflating the two makes every optional
    # stage default-on.
    opt_in: bool = False

    # Hold here for a person before going on. Cheaper than gating the diff: a
    # wrong approach is caught before the next phase spends its turn cap.
    approve: bool = False

    # What a refusal does: where to go, how many times, and when to stop.
    on_refusal: str = ""
    max_revisions: int = 2
    # A gate that repeats itself word for word has already shown its complaint
    # is not about the diff, so a second attempt costs a turn and learns nothing.
    stop_when_identical: bool = True
    on_error: str = "fail"

    contract: str = ""           # `proven` / `verdict` — see contracts.py
    revert_changes: bool = False  # a check may run; it may not repair

    # What the human did, for a stage that watches a pull request. These are
    # edges too: `rework` is reachable only through one, and a walk that follows
    # `next` alone reports it unreachable.
    outcomes: tuple[tuple[str, str], ...] = ()

    @property
    def runs_a_turn(self) -> bool:
        return bool(self.phase)

    def destinations(self) -> tuple[str, ...]:
        """Every stage this one can lead to, by any edge."""
        out = [self.next] if self.next else []
        out += [to for _, to in self.outcomes]
        if self.on_refusal:
            out.append(self.on_refusal)
        return tuple(dict.fromkeys(d for d in out if d))


@dataclass(frozen=True)
class Graph:
    """A whole pipeline."""

    name: str
    first: str
    stages: dict[str, Stage]
    terminal: tuple[str, ...] = TERMINAL_DEFAULT
    model: str = ""

    def stage(self, name: str) -> Stage | None:
        return self.stages.get(name)

    def is_terminal(self, name: str) -> bool:
        return name in self.terminal

    def model_for(self, stage: Stage) -> str:
        """The stage's model, else the pipeline's default."""
        return stage.model or self.model

    def states(self) -> tuple[str, ...]:
        """Every state a run of this pipeline can occupy."""
        return tuple(self.stages) + self.terminal + (BLOCKED,)


# --- parsing ---------------------------------------------------------------

def _seq(value, field_name: str, stage: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, (list, tuple)):
        return tuple(str(v) for v in value)
    raise GraphError(f"stage {stage!r}: {field_name} must be a list, got {type(value).__name__}")


def _stage(name: str, raw: dict) -> Stage:
    if not isinstance(raw, dict):
        raise GraphError(f"stage {name!r} must be a mapping, got {type(raw).__name__}")

    phase = str(raw.get("phase") or "")
    action = str(raw.get("action") or "")
    if phase and action:
        raise GraphError(
            f"stage {name!r} names both a phase ({phase!r}) and an action ({action!r}) "
            "— it is one or the other")
    if not phase and not action:
        raise GraphError(f"stage {name!r} names neither a phase nor an action")
    if action and action not in ACTIONS:
        raise GraphError(
            f"stage {name!r}: unknown action {action!r}. Known: {', '.join(sorted(ACTIONS))}")

    on_error = str(raw.get("on_error") or "fail")
    if on_error not in ON_ERROR:
        raise GraphError(f"stage {name!r}: on_error must be one of {ON_ERROR}, got {on_error!r}")

    refusal = raw.get("on_refusal") or {}
    if isinstance(refusal, str):
        refusal = {"goto": refusal}
    if not isinstance(refusal, dict):
        raise GraphError(f"stage {name!r}: on_refusal must be a mapping or a stage name")

    outcomes = tuple((key.removeprefix("on_"), str(raw[key]))
                     for key in ("on_merge", "on_close", "on_comment") if raw.get(key))

    if raw.get("optional") and raw.get("opt_in"):
        raise GraphError(
            f"stage {name!r} is both optional and opt_in. `optional` runs unless a run "
            "turns it off; `opt_in` runs only when a run asks — pick one")

    return Stage(
        name=name, phase=phase, action=action,
        next=str(raw.get("next") or ""), model=str(raw.get("model") or ""),
        requires=_seq(raw.get("requires"), "requires", name),
        produces=_seq(raw.get("produces"), "produces", name),
        skip_when=_seq(raw.get("skip_when"), "skip_when", name),
        optional=bool(raw.get("optional")), opt_in=bool(raw.get("opt_in")),
        approve=bool(raw.get("approve")),
        on_refusal=str(refusal.get("goto") or ""),
        max_revisions=int(refusal.get("max", 2)),
        stop_when_identical=bool(refusal.get("stop_when_identical", True)),
        on_error=on_error,
        contract=str(raw.get("contract") or ""),
        revert_changes=bool(raw.get("revert_worktree_changes")
                            or raw.get("revert_changes")),
        outcomes=outcomes,
    )


def parse(raw: dict) -> Graph:
    """Build a `Graph`, or explain what is wrong with this one.

    Validation is deliberately strict about *reachability* and *exits*, because
    the two ways to write a pipeline that looks fine and hangs are a stage
    nothing reaches and a stage with no way out.
    """
    if not isinstance(raw, dict):
        raise GraphError(f"a pipeline must be a mapping, got {type(raw).__name__}")

    raw_stages = raw.get("stages") or {}
    if not raw_stages:
        raise GraphError("a pipeline needs at least one stage")

    stages = {name: _stage(name, body) for name, body in raw_stages.items()}
    terminal = _seq(raw.get("terminal"), "terminal", "<pipeline>") or TERMINAL_DEFAULT
    first = str(raw.get("first") or next(iter(stages)))

    if first not in stages:
        raise GraphError(f"first stage {first!r} is not a stage "
                         f"({', '.join(sorted(stages))})")

    known = set(stages) | set(terminal)
    for stage in stages.values():
        for dest in stage.destinations():
            if dest not in known:
                raise GraphError(
                    f"stage {stage.name!r} leads to {dest!r}, which is neither a "
                    f"stage nor terminal")
        if not stage.destinations():
            raise GraphError(
                f"stage {stage.name!r} has no way out — give it `next`, an outcome, "
                "or make it terminal")
        if stage.contract and not stage.runs_a_turn:
            raise GraphError(
                f"stage {stage.name!r} has a contract but runs no phase — a contract "
                "grades an answer, and an action does not give one")

    reachable = _reachable(first, stages, set(terminal))
    orphans = sorted(set(stages) - reachable)
    if orphans:
        raise GraphError(
            f"unreachable from {first!r}: {', '.join(orphans)}. "
            "Check the outcome edges — `rework` is usually reached by `on_comment`")

    return Graph(name=str(raw.get("name") or "pipeline"), first=first,
                 stages=stages, terminal=tuple(terminal),
                 model=str(raw.get("model") or ""))


def _reachable(first: str, stages: dict[str, Stage], terminal: set[str]) -> set[str]:
    """Every stage reachable from `first` by **any** edge — `next`, an outcome,
    or a refusal. Following `next` alone reports `rework` unreachable."""
    seen, queue = set(), [first]
    while queue:
        name = queue.pop()
        if name in seen or name in terminal:
            continue
        seen.add(name)
        stage = stages.get(name)
        if stage is not None:
            queue += [d for d in stage.destinations() if d not in seen]
    return seen


def to_dict(graph: Graph) -> dict:
    """The graph as the document it was parsed from — for export and storage."""
    out: dict = {"name": graph.name, "first": graph.first,
                 "terminal": list(graph.terminal), "stages": {}}
    if graph.model:
        out["model"] = graph.model
    for name, s in graph.stages.items():
        body: dict = {}
        for key, value, default in (
                ("phase", s.phase, ""), ("action", s.action, ""),
                ("next", s.next, ""), ("model", s.model, ""),
                ("requires", list(s.requires), []), ("produces", list(s.produces), []),
                ("skip_when", list(s.skip_when), []),
                ("optional", s.optional, False), ("opt_in", s.opt_in, False),
                ("approve", s.approve, False),
                ("contract", s.contract, ""),
                ("revert_worktree_changes", s.revert_changes, False)):
            if value != default:
                body[key] = value
        if s.on_error != "fail":
            body["on_error"] = s.on_error
        if s.on_refusal:
            body["on_refusal"] = {"goto": s.on_refusal, "max": s.max_revisions,
                                  "stop_when_identical": s.stop_when_identical}
        for kind, dest in s.outcomes:
            body[f"on_{kind}"] = dest
        out["stages"][name] = body
    return out


# --- the shipped default ---------------------------------------------------

def default_pipeline() -> dict:
    """`ship-a-ticket` — the pipeline a team gets before configuring anything.

    Its shape carries three decisions worth knowing: **deciding and building are
    separate turns on different models**, so the thinking model is spent once on
    the largest blast radius and spent *after* reading the repository; **a check
    may run and may not repair**, so `prove` reverts what it touched; and
    **nothing merges itself**.
    """
    return {
        "name": "ship-a-ticket",
        "first": "prepare",
        "terminal": ["landed", "closed", "failed"],
        "model": "claude-sonnet-5",
        "stages": {
            "prepare": {"action": "prepare_workspace", "next": "plan"},
            "plan": {
                "phase": "plan", "model": "claude-opus-5",
                "requires": ["spec"], "produces": ["plan"],
                "skip_when": ["revision", "rework"],
                # A plan turn that fails hands over an empty plan rather than
                # failing the run.
                "on_error": "continue",
                "approve": True,
                "next": "run",
            },
            "run": {
                "phase": "run",
                # Not `plan`: planning is skipped for a revision, and requiring
                # it would make every revision unable to start.
                "requires": ["spec"], "produces": ["work"],
                "on_refusal": {"goto": "run", "max": 2, "stop_when_identical": True},
                "next": "prove",
            },
            "prove": {
                "phase": "prove", "requires": ["work"], "produces": ["proof"],
                "contract": "proven", "optional": True,
                "revert_worktree_changes": True,
                "next": "review",
            },
            "review": {
                # Handed the spec and the diff, and nothing else — never the
                # run phase's summary of its own work. A check fed the work's
                # own account of itself is grading a story.
                "phase": "review", "requires": ["work"], "produces": ["review"],
                "contract": "verdict", "optional": True,
                "next": "commit",
            },
            "commit": {
                "action": "commit_and_push",
                "on_refusal": {"goto": "run", "max": 2, "stop_when_identical": True},
                "next": "publish",
            },
            "publish": {"action": "open_pull_request", "next": "waiting"},
            "waiting": {
                "action": "watch_pull_request",
                "on_merge": "landed", "on_close": "closed", "on_comment": "rework",
            },
            "rework": {"action": "prepare_workspace", "next": "run"},
        },
    }


def quick_fix() -> dict:
    """One turn to a pull request. For a scratch repo, a spike, or a mechanical
    migration where the diff *is* the review.

    What you give up, stated so it is a decision rather than a discovery: no
    plan, so the turn picks the first approach that works; no proof, so "it
    compiles" is the strongest claim anyone can make about the diff; no review;
    and no revision loop, so a repository with a strict commit hook fails most
    of these outright.
    """
    return {
        "name": "quick-fix",
        "first": "prepare",
        "terminal": ["landed", "closed", "failed"],
        "model": "claude-sonnet-5",
        "stages": {
            "prepare": {"action": "prepare_workspace", "next": "run"},
            "run": {"phase": "run", "requires": ["spec"], "produces": ["work"],
                    "next": "commit"},
            # Rung 4 stays. Skipping it would ship things the repository itself
            # refuses.
            "commit": {"action": "commit_and_push", "next": "publish"},
            "publish": {"action": "open_pull_request", "next": "waiting"},
            "waiting": {"action": "watch_pull_request", "on_merge": "landed",
                        "on_close": "closed", "on_comment": "rework"},
            "rework": {"action": "prepare_workspace", "next": "run"},
        },
    }


def strict() -> dict:
    """Every check on, and one more.

    For a repository with users on it. A job reaching a pull request has had its
    plan read by a person, its software run, its diff reviewed, and its security
    surface looked at by something shown neither the plan nor the implementer's
    account of what it built.
    """
    graph = default_pipeline()
    graph["name"] = "strict"
    stages = graph["stages"]
    # A plan that failed is not an empty plan to build from.
    stages["plan"]["on_error"] = "fail"
    stages["plan"]["max_revisions"] = 3
    # Not optional here: "it compiles" was the strongest claim anybody could
    # make about a diff before this stage existed.
    stages["prove"]["optional"] = False
    stages["review"]["optional"] = False
    stages["review"]["next"] = "security"
    # A second reader with a single question — what does this diff let somebody
    # do that they could not do before — because a general reviewer asked to
    # check everything checks the thing it read most recently.
    stages["security"] = {
        "phase": "security", "model": "claude-opus-5",
        "requires": ["work"], "produces": ["review"],
        "contract": "verdict", "optional": True, "next": "commit",
    }
    stages["run"]["on_refusal"] = {"goto": "run", "max": 3,
                                   "stop_when_identical": True}
    return graph


def docs_only() -> dict:
    """Prose, reviewed by a person and nothing else. No proof stage, because
    there is nothing to run."""
    return {
        "name": "docs-only",
        "first": "prepare",
        "terminal": ["landed", "closed", "failed"],
        "model": "claude-sonnet-5",
        "stages": {
            "prepare": {"action": "prepare_workspace", "next": "run"},
            "run": {"phase": "run", "requires": ["spec"], "produces": ["work"],
                    "next": "review"},
            "review": {"phase": "review", "requires": ["work"],
                       "produces": ["review"], "contract": "verdict",
                       "next": "commit"},
            "commit": {"action": "commit_and_push", "next": "publish"},
            "publish": {"action": "open_pull_request", "next": "waiting"},
            "waiting": {"action": "watch_pull_request", "on_merge": "landed",
                        "on_close": "closed", "on_comment": "rework"},
            "rework": {"action": "prepare_workspace", "next": "run"},
        },
    }


# The defaults to build from. Each says what it gives up, because a template
# chosen without knowing that is a decision nobody made.
TEMPLATES: dict[str, dict] = {
    "ship-a-ticket": {
        "build": default_pipeline,
        "about": "The full loop: plan, build, prove, review, then a person merges.",
        "gives_up": "",
    },
    "quick-fix": {
        "build": quick_fix,
        "about": "One turn to a pull request.",
        "gives_up": "No plan, no proof, no review, no revision loop — the diff is the review.",
    },
    "strict": {
        "build": strict,
        "about": "Every check on, plus a second reader for the security surface.",
        "gives_up": "Four turns per job, two on a thinking model. It costs more.",
    },
    "docs-only": {
        "build": docs_only,
        "about": "Prose, reviewed by a person.",
        "gives_up": "No proof stage — there is nothing to run.",
    },
}


def templates() -> list[dict]:
    """The catalog, for the canvas gallery."""
    return [{"name": name, "about": meta["about"], "gives_up": meta["gives_up"],
             "stages": len(meta["build"]()["stages"])}
            for name, meta in TEMPLATES.items()]


def template(name: str) -> dict:
    meta = TEMPLATES.get(name)
    if meta is None:
        raise GraphError(f"unknown template: {name!r} "
                         f"(have {', '.join(TEMPLATES)})")
    return meta["build"]()
