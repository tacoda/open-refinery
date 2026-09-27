"""What one turn is allowed to be.

A phase is the harness's configuration: which model, how much thinking, how many
turns, **which tools**, and the prompt it is actually asked. Nothing here calls
a model — this is the config the agent is built from, so the grants and defaults
are testable without spending anything.

The tool grant is **rung 1** of the ladder: a phase is not told not to edit, it
is never handed an editor. A rule at rung 1 leaves nothing to refuse and nothing
to argue past, which is why `prove` and `review` need no predicate to be
prevented from repairing what they find.

Defaults are code; a team overrides a row. That is the same shape as the
pipeline templates — ship something that works, and let it be changed.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# --- tool grants ------------------------------------------------------------
# deepagents' filesystem middleware ships these. `read_file` is mandatory in any
# allowlist, so a grant that omits it is a grant of nothing.

READ_ONLY = ("read_file", "ls", "glob", "grep")
EDITING = ("write_file", "edit_file")
RUNNING = ("execute",)
PLANNING = ("write_todos",)

ALL_TOOLS = READ_ONLY + EDITING + RUNNING + PLANNING

THINKING = ("low", "medium", "high", "xhigh")


@dataclass(frozen=True)
class Phase:
    """One turn's constraints."""

    name: str
    prompt: str = ""
    model: str = ""                      # "" = the pipeline's default
    thinking: str = "medium"
    max_turns: int = 50
    tools: tuple[str, ...] = READ_ONLY
    subagents: bool = False              # in-turn delegation
    about: str = ""

    @property
    def may_edit(self) -> bool:
        return any(t in self.tools for t in EDITING)

    @property
    def may_run(self) -> bool:
        return any(t in self.tools for t in RUNNING)

    def granted(self, withheld: tuple[str, ...] = ()) -> tuple[str, ...]:
        """The effective grant: what this phase may call, minus what the ladder
        withholds. `read_file` always survives — a phase given tools and no way
        to read them has been given nothing."""
        kept = tuple(t for t in self.tools if t not in withheld)
        return kept if "read_file" in kept else ("read_file",) + kept


# The six that ship. A team that agrees with these writes nothing.
BUILTIN: dict[str, Phase] = {
    "refine": Phase(
        "refine", model="claude-opus-5", thinking="high", max_turns=40,
        tools=READ_ONLY + PLANNING,
        about="A rough idea becomes a spec work can begin from.",
        prompt=(
            "Turn the request below into a specification somebody could build from.\n\n"
            "Read the repository first, so the spec names real files rather than "
            "plausible ones. Say what done looks like, as criteria somebody could "
            "check. You are deciding what to ask for, not what to change — you "
            "have no editor, and you do not need one.\n"),
    ),
    "plan": Phase(
        "plan", model="claude-opus-5", thinking="high", max_turns=50,
        tools=READ_ONLY + PLANNING,
        about="Decide what to build, before building it.",
        prompt=(
            "Read the repository, then write the plan for the work below.\n\n"
            "Name the files you would change and what each change is for. Deciding "
            "and building are separate turns on purpose: this one is on the "
            "expensive model because it is the decision with the largest blast "
            "radius, and it happens after reading so the plan names real files.\n\n"
            "You are read-only. Do not attempt to make the change.\n"),
    ),
    "run": Phase(
        "run", thinking="xhigh", max_turns=80,
        tools=ALL_TOOLS, subagents=True,
        about="Where the tokens actually go.",
        prompt=(
            "Make the change described below.\n\n"
            "Follow the repository's own conventions — they are in your memory, "
            "and they beat your habits. Run the tests you touch. Keep the change "
            "as small as the work allows: a two-line fix arriving as a refactor of "
            "the module around it is a worse change, not a better one.\n"),
    ),
    "prove": Phase(
        "prove", max_turns=80, tools=READ_ONLY + RUNNING,
        about="Runs the software and reports what it saw.",
        prompt=(
            "Run the software against the criteria below and report what you saw.\n\n"
            "Finish with a line reading exactly:\n\n"
            "    PROVEN: yes | no | partial\n\n"
            "A `yes` with no command under it is downgraded to `unproven` — put "
            "the commands you actually ran in the output, each on a line starting "
            "with `$`. You may run things and you may not repair them; you have no "
            "editor, and anything you change is reverted before the diff ships.\n"),
    ),
    "review": Phase(
        "review", thinking="high", max_turns=50, tools=READ_ONLY,
        subagents=True,
        about="Reads the diff and stamps a verdict.",
        prompt=(
            "Review the diff below against what was asked.\n\n"
            "You have been given the spec and the diff, and deliberately not the "
            "implementer's account of its own work — a check fed the work's story "
            "is grading a story.\n\n"
            "Finish with a line reading exactly:\n\n"
            "    VERDICT: pass | concerns | blocker\n\n"
            "Every objection must name a place, as `path/file.py:12`. An objecting "
            "review that names nothing is downgraded to `unreadable`, because it is "
            "a mood. You may read around the change to learn the conventions; you "
            "may not quietly fix what you find.\n"),
    ),
    "security": Phase(
        "security", model="claude-opus-5", thinking="high", max_turns=40,
        tools=READ_ONLY,
        about="One question: what does this diff let somebody do that they could not before?",
        prompt=(
            "Read the diff below and answer one question: what does it let somebody "
            "do that they could not do before?\n\n"
            "A general reviewer asked to check everything checks the thing it read "
            "most recently. You have one question, so ask it of the whole diff.\n\n"
            "Finish with:\n\n"
            "    VERDICT: pass | concerns | blocker\n\n"
            "Name a place for every objection.\n"),
    ),
    "improve": Phase(
        "improve", model="claude-opus-5", thinking="high", max_turns=50,
        tools=READ_ONLY,
        about="Reads what went wrong and proposes what would have prevented it.",
        prompt=(
            "Read the record below and say what would have prevented what went "
            "wrong.\n\n"
            "Every proposal must cite the runs it came from. One that cannot be "
            "traced to evidence should be dropped rather than repaired — a lane "
            "that always finds three things is one nobody believes by the third "
            "time.\n\n"
            "You are read-only, deliberately: the lane proposing changes to the "
            "rules does not get to be the one thing escaping the gate everything "
            "else goes through.\n"),
    ),
}

DEFAULT = Phase("default", tools=READ_ONLY)


def builtin(name: str) -> Phase:
    """The shipped phase, or a read-only default for one a team invented."""
    return BUILTIN.get(name, Phase(name, tools=READ_ONLY))


def resolve(session, name: str) -> Phase:
    """The effective phase: the built-in, with a team's row layered over it.

    Only fields the row actually sets are overridden, so a team changing a turn
    cap does not silently clear the prompt.
    """
    from ..models import PhaseConfig

    base = builtin(name)
    row = session.get(PhaseConfig, name) if session is not None else None
    if row is None:
        return base
    return Phase(
        name=name,
        prompt=row.prompt or base.prompt,
        model=row.model or base.model,
        thinking=row.thinking or base.thinking,
        max_turns=row.max_turns or base.max_turns,
        tools=tuple(row.tools) if row.tools else base.tools,
        subagents=row.subagents if row.subagents is not None else base.subagents,
        about=base.about,
    )


def catalog(session=None) -> list[dict]:
    """Every phase and what it may do — for the canvas and the phase editor."""
    names = set(BUILTIN)
    if session is not None:
        from sqlmodel import select

        from ..models import PhaseConfig
        names |= {r.name for r in session.exec(select(PhaseConfig))}
    out = []
    for name in sorted(names):
        phase = resolve(session, name)
        out.append({"name": name, "about": phase.about, "model": phase.model,
                    "thinking": phase.thinking, "max_turns": phase.max_turns,
                    "tools": list(phase.tools), "subagents": phase.subagents,
                    "may_edit": phase.may_edit, "may_run": phase.may_run,
                    "builtin": name in BUILTIN})
    return out
