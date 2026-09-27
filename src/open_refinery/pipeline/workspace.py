"""The worktree a run works in, and the claim that stops two runs racing.

A run gets its **own git worktree** off a branch, so several runs against one
repository do not trip over each other's files. The claim is a row, not a
lockfile: a crash leaves a stale claim that a later worker can see and take
over, where a lockfile just stays locked.

`git` here is a thin wrapper that **never uses a shell**. Passing
`git add -A && git commit -m x` as a command tries to spawn a program with that
literal name — which fails in a way that reads like a commit that worked, and
the first run through would push a branch with no commits on it.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

# Where worktrees live. Beside the checkout rather than in /tmp: a reviewer
# looking at a local request needs the branch to still be there.
WORKTREE_DIR = ".open-refinery/worktrees"


class WorkspaceError(RuntimeError):
    """Git refused, or the repository is not where we were told."""


@dataclass(frozen=True)
class Ran:
    """What a command did. A non-zero exit is a failure, not a result."""

    ok: bool
    out: str
    code: int = 0

    @property
    def failed(self) -> bool:
        return not self.ok


def git(cwd: str | Path, *args: str, check: bool = True, timeout: int = 120) -> Ran:
    """One git command. **Not a shell** — `args` are arguments, not a string."""
    return run(cwd, "git", *args, check=check, timeout=timeout)


def run(cwd: str | Path, program: str, *args: str, check: bool = True,
        timeout: int = 300, env: dict | None = None) -> Ran:
    """Spawn a program directly. No shell, so no quoting and no `&&`."""
    try:
        proc = subprocess.run(
            [program, *args], cwd=str(cwd), capture_output=True, text=True,
            timeout=timeout, env=env)
    except FileNotFoundError:
        raise WorkspaceError(f"{program} is not on PATH") from None
    except subprocess.TimeoutExpired:
        return Ran(False, f"{program} timed out after {timeout}s", 124)

    out = f"{proc.stdout}{proc.stderr}".strip()
    if proc.returncode != 0 and check:
        raise WorkspaceError(f"`{program} {' '.join(args)}` exited "
                             f"{proc.returncode}: {out[:400]}")
    return Ran(proc.returncode == 0, out, proc.returncode)


def shell(cwd: str | Path, command: str, timeout: int = 600) -> Ran:
    """A command a *repository* supplied — `prepare_cmd`, `test_cmd`.

    This one does go through a shell, because a repo says `pip install -e .` and
    means it. That is a deliberate exception to the rule above, and it is safe
    only because the string comes from the repository's own configuration rather
    than from a model.
    """
    if not command.strip():
        return Ran(True, "")
    try:
        proc = subprocess.run(command, cwd=str(cwd), shell=True, capture_output=True,
                              text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return Ran(False, f"timed out after {timeout}s", 124)
    return Ran(proc.returncode == 0, f"{proc.stdout}{proc.stderr}".strip(),
               proc.returncode)


def available() -> bool:
    return shutil.which("git") is not None


# A run id is a uuid hex; the first 12 characters are plenty to be unique here
# and short enough to read in a branch name. Defined once, because a caller
# slicing it themselves is a caller that eventually slices it differently.
def short(run_id: str) -> str:
    return str(run_id)[:12]


def branch_name(run_id: str) -> str:
    """One branch per run, so the id is recoverable from the branch later."""
    return f"open-refinery/{short(run_id)}"


def worktree_path(checkout: str | Path, run_id: str) -> Path:
    """Where this run's worktree lives. The one place that decides."""
    return Path(checkout) / WORKTREE_DIR / short(run_id)


def root_of(git_url: str, checkout: str | None = None) -> Path:
    """The local checkout a worktree comes off.

    A `local` repo's git URL *is* its path. A remote one has to have been cloned
    somewhere; `checkout` says where.
    """
    path = Path(checkout or git_url)
    if not (path / ".git").exists():
        raise WorkspaceError(
            f"{path} is not a git checkout — clone it first, or point the "
            "repository's git_url at a local path")
    return path


def create(checkout: str | Path, run_id: str, *, base: str = "main") -> Path:
    """A fresh worktree on a new branch off `base`.

    Idempotent: a worker retrying after a crash finds the worktree already
    there and uses it rather than failing.
    """
    checkout = Path(checkout)
    branch = branch_name(run_id)
    path = worktree_path(checkout, run_id)

    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)

    existing = git(checkout, "rev-parse", "--verify", branch, check=False)
    if existing.ok:
        git(checkout, "worktree", "add", str(path), branch)
    else:
        git(checkout, "worktree", "add", "-b", branch, str(path), base)
    return path


def release(checkout: str | Path, run_id: str, *, keep_branch: bool = True) -> None:
    """Give the worktree back. The **branch stays** by default — it is what a
    reviewer checks out, and removing it would delete the work."""
    checkout = Path(checkout)
    path = worktree_path(checkout, run_id)
    if path.exists():
        git(checkout, "worktree", "remove", "--force", str(path), check=False)
    if not keep_branch:
        git(checkout, "branch", "-D", branch_name(run_id), check=False)


def dirty(worktree: str | Path) -> bool:
    """Whether anything was changed. An empty diff means the run built nothing,
    and pushing a branch with no commits on it is the failure that looks most
    like success."""
    return bool(git(worktree, "status", "--porcelain", check=False).out.strip())


def diff(worktree: str | Path, *, base: str = "main") -> str:
    """The finished diff — what the delivery gate is handed."""
    return git(worktree, "diff", base, check=False).out


def snapshot(worktree: str | Path) -> None:
    """Stage everything, so the work so far is recoverable from the index.

    Taken before a check runs. Without it, reverting the check would throw away
    the work the run phase just did — a check that may not repair must not be
    able to destroy either.
    """
    git(worktree, "add", "-A", check=False)


def revert_changes(worktree: str | Path) -> None:
    """Undo whatever the check touched, and **only** that.

    `checkout -- .` restores the working tree from the index, so everything
    staged by `snapshot` survives and anything the check altered goes back.
    `clean -fd` removes files the check created, which are untracked; files the
    run phase created are staged, so they are tracked and stay.

    `prove` runs the software and may not repair it, and a shell can write
    whatever its command line says — so what a check touched is reverted rather
    than trusted.
    """
    git(worktree, "checkout", "--", ".", check=False)
    git(worktree, "clean", "-fd", check=False)


def commit(worktree: str | Path, message: str, *, author: str = "") -> Ran:
    """Stage everything and commit.

    **A non-zero exit is a failure.** The repository's own commit hook refusing
    is exactly the shape this takes, and reading it as success would silently
    disable the whole revision loop.
    """
    git(worktree, "add", "-A")
    args = ["commit", "-m", message]
    if author:
        args += ["--author", author]
    return git(worktree, *args, check=False)


def push(worktree: str | Path, branch: str, *, remote: str = "origin") -> Ran:
    """Publish the branch. A forge with no remote (`local`) needs no push."""
    if not remote:
        return Ran(True, "no remote — the branch is already in the checkout")
    return git(worktree, "push", "-u", remote, branch, check=False)
