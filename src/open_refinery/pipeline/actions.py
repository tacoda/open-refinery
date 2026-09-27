"""What a stage does when it is not running a turn.

Each returns the same shape a phase does — `Result` — so `graph.advance` does
not care which kind of stage it just ran. That symmetry is what keeps the state
machine a pure function of two dicts.

The delivery gate lives here, in `commit_and_push`: **rung 4, over the finished
diff**, and the last thing between a run and a pull request.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import forge as forgelib
from . import workspace as ws
from .document import read as read_document
from .graph import ERROR, OK, REFUSED, Result


@dataclass
class Context:
    """Everything an action needs that is not the run itself.

    Passed in rather than looked up, so every action is testable against a
    temporary git repo with no database and no network.
    """

    checkout: str                # the local clone a worktree comes off
    repo_slug: str               # owner/name, how the forge addresses it
    base: str = "main"
    forge: forgelib.Forge | None = None
    credential: dict | None = None
    prepare_cmd: str = ""
    cleanup_cmd: str = ""
    author: str = ""             # "Name <email>", so the commit names a person
    pipeline_model: str = ""     # the workflow default a phase falls back to

    def driver(self) -> forgelib.Forge:
        return self.forge or forgelib.FORGES["local"]


def prepare_workspace(run: dict, ctx: Context) -> Result:
    """Claim a worktree and run whatever the repository needs to be usable.

    Idempotent, because `rework` comes back through here and a second run
    against the same id must find its worktree rather than fail.
    """
    try:
        path = ws.create(ctx.checkout, run["id"], base=ctx.base)
    except ws.WorkspaceError as exc:
        return Result(ERROR, error=str(exc))

    if ctx.prepare_cmd:
        # The repository's own setup. Without this, every repo gets identical
        # treatment and the first one whose tests need a step fails.
        ran = ws.shell(path, ctx.prepare_cmd)
        if ran.failed:
            return Result(ERROR, error=f"prepare_cmd failed: {ran.out[:400]}")

    return Result(OK, produced=("workspace",))


def commit_and_push(run: dict, ctx: Context) -> Result:
    """The delivery gate, the commit, and the branch.

    Three ways this comes back, and they mean different things:

    - **nothing changed** → an error. A run that built nothing is not a success
      with an empty diff, and pushing a branch with no commits on it is the
      failure that looks most like success.
    - **the repository's hook refused** → a *refusal*, which sends the run back
      to `run` with the hook's own words as the brief. Reading a non-zero exit
      as success would silently disable the whole revision loop.
    - **it committed** → OK, and the branch is pushed if the forge has a remote.
    """
    path = _worktree(ctx, run)
    if path is None:
        return Result(ERROR, error="no workspace — prepare_workspace has not run")

    if not ws.dirty(path):
        return Result(ERROR, error="nothing was changed — there is no diff to ship")

    title = _title(run)
    committed = ws.commit(path, title, author=ctx.author)
    if committed.failed:
        # Rung 4: the repository's own gate, in its own words.
        return Result(REFUSED, reason=committed.out[:600] or "the commit hook refused")

    branch = ws.branch_name(run["id"])
    pushed = ws.push(path, branch, remote=ctx.driver().remote)
    if pushed.failed:
        return Result(ERROR, error=f"push failed: {pushed.out[:400]}")

    return Result(OK, produced=("commit",))


def open_pull_request(run: dict, ctx: Context) -> Result:
    """Publish the work for a person to decide on.

    The body is **the run document** — each stage appended a section as it went,
    so the account of the work is already written. Nothing is summarised into
    existence here.
    """
    driver = ctx.driver()
    branch = ws.branch_name(run["id"])
    cred = dict(ctx.credential or {})
    cred.setdefault("workspace", str(_worktree(ctx, run) or ctx.checkout))
    cred.setdefault("base", ctx.base)
    cred.setdefault("branch", branch)

    try:
        pr = driver.open_pr(cred, ctx.repo_slug, branch=branch, base=ctx.base,
                            title=_title(run), body=_body(run))
    except forgelib.ForgeError as exc:
        return Result(ERROR, error=str(exc))

    return Result(OK, produced=("pull_request",),
                  reason=f"{pr.number}\t{pr.url}")   # the runner records these


def watch_pull_request(run: dict, ctx: Context) -> Result:
    """Poll the forge and report what the human did.

    Returns the event the graph branches on — `merge`, `close` or `comment` —
    or nothing, which keeps the run waiting. **A comment the factory wrote is
    not a comment**: it pushes with the operator's credentials and is the
    request's author, so telling them apart by author would find none.
    """
    number = str(run.get("pr_number") or "")
    if not number:
        return Result(ERROR, error="no pull request to watch")

    driver = ctx.driver()
    cred = dict(ctx.credential or {})
    cred.setdefault("workspace", str(_worktree(ctx, run) or ctx.checkout))
    cred.setdefault("base", ctx.base)
    cred.setdefault("branch", ws.branch_name(run["id"]))

    try:
        pr = driver.pr_state(cred, ctx.repo_slug, number)
        if pr.state == forgelib.MERGED:
            return Result(OK, event="merge")
        if pr.state == forgelib.CLOSED:
            return Result(OK, event="close")
        theirs = [c for c in driver.comments(cred, ctx.repo_slug, number) if not c.ours]
    except forgelib.ForgeError as exc:
        return Result(ERROR, error=str(exc))

    if theirs:
        # The newest comment becomes the brief for the rework.
        return Result(OK, event="comment", reason=theirs[-1].body[:2000])
    return Result(OK)          # still waiting — the graph keeps it here


def teardown(run: dict, ctx: Context) -> Result:
    """Release the worktree. The **branch stays** — it is what a reviewer
    checks out, and removing it would delete the work."""
    path = _worktree(ctx, run)
    if path is not None and ctx.cleanup_cmd:
        ws.shell(path, ctx.cleanup_cmd)
    ws.release(ctx.checkout, run["id"], keep_branch=True)
    return Result(OK)


ACTIONS = {
    "prepare_workspace": prepare_workspace,
    "commit_and_push": commit_and_push,
    "open_pull_request": open_pull_request,
    "watch_pull_request": watch_pull_request,
    "teardown": teardown,
}


def perform(name: str, run: dict, ctx: Context) -> Result:
    fn = ACTIONS.get(name)
    if fn is None:
        return Result(ERROR, error=f"unknown action: {name!r}")
    try:
        return fn(run, ctx)
    except ws.WorkspaceError as exc:
        return Result(ERROR, error=str(exc))


# --- what the pull request says --------------------------------------------

def _worktree(ctx: Context, run: dict):
    path = ws.worktree_path(ctx.checkout, run["id"])
    return path if path.exists() else None


def _title(run: dict) -> str:
    """The spec's first line, with its markdown heading marker stripped —
    `# Do the thing` is a heading in a file and a stray `#` in a title."""
    doc = read_document(str(run.get("document") or ""))
    first = (doc.get("spec") or str(run.get("title") or "")).strip().splitlines()
    text = (first[0] if first else "").lstrip("#").strip()
    return text[:70] or "open-refinery"


def _body(run: dict) -> str:
    """**The run document.** By the time a person reads this, the account of the
    work is already written — what was asked, planned, built, proved, and what
    review found. An empty body makes a reviewer reconstruct all of it from the
    diff."""
    document = str(run.get("document") or "").strip()
    parts = [forgelib.MARKER, ""]
    parts += [document] if document else ["(no run document)"]
    parts += ["", "---", "",
              f"open-refinery run `{run.get('id', '')[:12]}` · "
              f"{run.get('revisions', 0)} revision(s). Nothing merges itself."]
    return "\n".join(parts)
