"""The harness: one turn, constrained.

**This is the only module that imports deepagents.** That is deliberate — it is
a pre-1.0 library carrying pillar 2, so an upstream API change has a one-file
blast radius and swapping it later is a rewrite of this file rather than of the
factory. Everything else in `pipeline/` works without it installed.

What a turn is handed, and where each part comes from:

| | from |
|---|---|
| model, turn cap, thinking | the phase (`phases.py`), on the actor's credential |
| tool grant | the phase, minus what the ladder withholds — rung 1 |
| the repository's own rules | `ingest.charter()` as `memory=` |
| the filesystem | rooted at the run's worktree, so it cannot write outside |
| governance on every call | `GovernanceMiddleware` — rungs 2 and 3 |
| a hold for a person | `interrupt_on`, from the process's oversight level |
"""

from __future__ import annotations

from dataclasses import dataclass

from ..models import Repository, Run
from ..oversight import LEVELS
from .graph import BLOCKED_ON_PERSON, ERROR, OK, Result
from .middleware import Governed
from .phases import Phase, resolve
from .workspace import worktree_path


class HarnessError(RuntimeError):
    """The turn could not be built or could not run."""


# Which tools a person is asked about, per oversight level. `ask` NEVER becomes
# `allow`: at `autonomous` and `dark` it degrades to the ladder refusing, which
# is what "an unattended factory reading ask as yes has answered a question
# nobody put" means in code.
INTERRUPTS: dict[str, dict] = {
    "manual":     {"read_file": True, "write_file": True, "edit_file": True, "execute": True},
    "assisted":   {"write_file": True, "edit_file": True, "execute": True},
    "supervised": {"execute": True},
    "autonomous": {},
    "dark":       {},
}


def interrupts_for(level: str) -> dict:
    return INTERRUPTS.get(level, INTERRUPTS["supervised"])


@dataclass
class Turn:
    """What one turn produced."""

    text: str = ""
    units: int = 0
    interrupted: bool = False
    error: str = ""


def governance_middleware(governed: Governed):
    """Adapt `Governed` to the harness's tool-call hook.

    Lives here rather than in `middleware.py` because it is the only part that
    knows the framework exists, and keeping framework contact in one file is
    what makes replacing that framework a one-file job.
    """
    from langchain.agents.middleware import wrap_tool_call

    @wrap_tool_call
    def governed_call(request, handler):
        tool = getattr(request, "name", "") or str(request)
        args = getattr(request, "args", {}) or {}

        refused = governed.check(tool, args)
        if refused:
            governed.record(tool, refused)
            # Handed back as a result, not raised: an exception ends the turn,
            # and a refusal the model can read is one it can work around.
            return refused

        result = handler(request)
        governed.record(tool, "", str(result))
        return result

    return governed_call


def build(phase: Phase, *, model, workspace: str, governed: Governed,
          memory: list[str] | None = None, oversight: str = "supervised",
          checkpointer=None, withheld: tuple[str, ...] = ()):
    """Assemble the agent for one phase. Nothing is called yet.

    `withheld` is **rung 1** of the ladder: a tool the phase never gets cannot
    be called, so there is nothing for rung 3 to refuse and nothing to argue
    past. It is the cheapest rung that can see a tool at all.
    """
    from deepagents import create_deep_agent
    from deepagents.backends import CompositeBackend, FilesystemBackend, StateBackend
    from deepagents.middleware import FilesystemMiddleware

    grant = phase.granted(withheld)
    backend = CompositeBackend(
        default=StateBackend(),
        # Rooted at the worktree, so the turn cannot write outside the run's own
        # checkout however it is asked to.
        routes={"/workspace/": FilesystemBackend(root_dir=workspace)},
    )
    return create_deep_agent(
        model=model,
        system_prompt=phase.prompt,
        backend=backend,
        middleware=[
            FilesystemMiddleware(backend=backend, tools=list(grant)),
            governance_middleware(governed),
        ],
        memory=list(memory or ()),
        interrupt_on=interrupts_for(oversight) or None,
        checkpointer=checkpointer,
    )


def charter_of(session, repo: Repository) -> list[str]:
    """The repository's own rules, for the turn to be handed.

    `ingest` already reads exactly these surfaces. Until 2.15.0 it turned them
    into coverage scores nobody acted on; this is what they were for.
    """
    from ..ingest import charter

    try:
        surfaces = charter(session, repo.id)
    except Exception:          # best-effort: a repo with no rules is normal
        return []
    lines = list(surfaces.get("harness", [])) + list(surfaces.get("charter", []))
    return [f"- {line}" for line in lines[:60]]


def model_for(session, run: Run, phase: Phase, pipeline_model: str = ""):
    """The model this phase runs on.

    Routed through the **actor's own credential**, so cost attributes to the
    person who started the run and a run cannot quietly spend somebody else's
    budget. Which provider that is comes from `models_port` — the one list of
    providers, so a model name resolves the same way everywhere.
    """
    from .. import credentials as creds
    from ..models_port import UnknownModel, provider_of

    wanted = phase.model or pipeline_model
    if not wanted:
        raise HarnessError("no model set for this phase or pipeline")

    provider = provider_of(wanted)
    if provider is None:
        raise HarnessError(f"no provider claims the model {wanted!r}")

    try:
        credential = creds.for_actor(session, run.actor_id, provider.key)
    except creds.NoCredential as exc:
        raise HarnessError(str(exc)) from None

    from ..models_port import chat
    try:
        return chat(wanted, credential)
    except UnknownModel as exc:
        raise HarnessError(str(exc)) from None
    except ImportError as exc:
        raise HarnessError(
            f"{provider.label} needs a package that is not installed: {exc}") from None


def run_phase(session, run: Run, stage, ctx, *, audit, session_factory,
              oversight: str = "supervised") -> Result:
    """Run one phase of one run. The thing `stub_phase` stood in for.

    Returns the same `Result` an action does, so the state machine still does
    not care which kind of stage it just ran.
    """
    phase = resolve(session, stage.phase)
    repo = session.get(Repository, run.repo_id)
    workspace = worktree_path(ctx.checkout, run.id)
    if not workspace.exists():
        return Result(ERROR, error="no workspace — prepare_workspace has not run")

    governed = Governed(session_factory=session_factory, actor_id=run.actor_id,
                        run_id=run.id, audit=audit)

    try:
        model = model_for(session, run, phase, ctx.pipeline_model)
        from ..ladder import withheld as ladder_withholds
        agent = build(phase, model=model, workspace=str(workspace),
                      governed=governed, memory=charter_of(session, repo),
                      oversight=oversight,
                      withheld=ladder_withholds(session, phase=stage.phase))
    except HarnessError as exc:
        return Result(ERROR, error=str(exc))
    except ModuleNotFoundError as exc:
        return Result(ERROR, error=f"the harness needs {exc.name}")

    brief = _brief(run, stage)
    try:
        answer = agent.invoke(
            {"messages": [{"role": "user", "content": brief}]},
            config={"recursion_limit": phase.max_turns})
    except Exception as exc:               # noqa: BLE001 — a turn failing is data
        return Result(ERROR, error=f"{type(exc).__name__}: {exc}")

    if getattr(answer, "interrupts", None) or answer.get("__interrupt__"):
        # A person has been asked something. The run holds; the approvals queue
        # is where they answer.
        return Result(BLOCKED_ON_PERSON, reason="a tool call is waiting on a person")

    text = _last_text(answer)
    return Result(OK, reason=text, produced=tuple(stage.produces))


def _brief(run: Run, stage) -> str:
    """What the turn is actually asked.

    The document is the interface between stages, so a phase is handed exactly
    what it `requires` and not the rest — `review` gets the spec and the diff,
    and never the run phase's account of its own work.
    """
    from .document import read

    doc = read(run.document or "")
    wanted = stage.requires or ("spec",)
    parts = [f"## {name}\n\n{doc.get(name)}" for name in wanted if doc.has(name)]
    return "\n\n".join(parts) or (run.document or "")


def _last_text(answer) -> str:
    messages = answer.get("messages") if isinstance(answer, dict) else None
    if not messages:
        return ""
    content = getattr(messages[-1], "content", "")
    if isinstance(content, list):
        return "".join(b.get("text", "") for b in content if isinstance(b, dict))
    return str(content or "")
