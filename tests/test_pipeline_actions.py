"""The actions, against a real git repository.

No mocks for git: a worktree either exists or it does not, and the failure this
suite is built around — a branch pushed with no commits on it — is invisible to
a fake.
"""

import subprocess
from pathlib import Path

import pytest

from open_refinery.pipeline import forge as forgelib
from open_refinery.pipeline import workspace as ws
from open_refinery.pipeline.actions import Context, perform
from open_refinery.pipeline.graph import ERROR, OK, REFUSED


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=str(cwd), check=True,
                   capture_output=True, text=True)


@pytest.fixture
def repo(tmp_path):
    """A real checkout with one commit on `main`."""
    root = tmp_path / "app"
    root.mkdir()
    _git(root, "init", "-b", "main")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Test")
    (root / "README.md").write_text("# app\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "first")
    return root


@pytest.fixture
def ctx(repo):
    return Context(checkout=str(repo), repo_slug=str(repo), base="main",
                   forge=forgelib.FORGES["local"], credential={"workspace": str(repo)})


def _run(rid="run0001abcd99", **kw):
    return {"id": rid, "document": "## What was asked\n\nAdd a login page\n",
            "revisions": 0, **kw}


# --- the worktree -----------------------------------------------------------

def test_prepare_creates_a_worktree_on_its_own_branch(repo, ctx):
    result = perform("prepare_workspace", _run(), ctx)
    assert result.outcome == OK

    path = ws.worktree_path(repo, "run0001abcd99")
    assert path.exists()
    branch = ws.git(path, "rev-parse", "--abbrev-ref", "HEAD").out
    assert branch == ws.branch_name("run0001abcd99")


def test_preparing_twice_is_the_same_worktree(repo, ctx):
    """`rework` comes back through here, and a retry after a crash must find
    its worktree rather than fail."""
    perform("prepare_workspace", _run(), ctx)
    assert perform("prepare_workspace", _run(), ctx).outcome == OK


def test_two_runs_get_separate_worktrees(repo, ctx):
    perform("prepare_workspace", _run("aaaa1111bbbb"), ctx)
    perform("prepare_workspace", _run("cccc2222dddd"), ctx)
    assert len({p.name for p in (repo / ws.WORKTREE_DIR).iterdir()}) == 2


def test_a_failing_prepare_command_is_an_error(repo):
    c = Context(checkout=str(repo), repo_slug=str(repo),
                prepare_cmd="exit 3", forge=forgelib.FORGES["local"])
    result = perform("prepare_workspace", _run(), c)
    assert result.outcome == ERROR and "prepare_cmd" in result.error


def test_the_repos_prepare_command_runs_in_the_worktree(repo):
    c = Context(checkout=str(repo), repo_slug=str(repo),
                prepare_cmd="echo ready > .prepared", forge=forgelib.FORGES["local"])
    perform("prepare_workspace", _run(), c)
    assert (ws.worktree_path(repo, "run0001abcd99") / ".prepared").exists()


# --- the delivery gate ------------------------------------------------------

def test_a_run_that_built_nothing_is_an_error(repo, ctx):
    """Not a success with an empty diff. Pushing a branch with no commits on it
    is the failure that looks most like success."""
    perform("prepare_workspace", _run(), ctx)
    result = perform("commit_and_push", _run(), ctx)
    assert result.outcome == ERROR and "nothing was changed" in result.error


def test_work_is_committed(repo, ctx):
    perform("prepare_workspace", _run(), ctx)
    (ws.worktree_path(repo, "run0001abcd99") / "login.py").write_text("print('hi')\n")

    result = perform("commit_and_push", _run(), ctx)
    assert result.outcome == OK

    log = ws.git(ws.worktree_path(repo, "run0001abcd99"), "log", "--oneline").out
    assert "Add a login page" in log


def test_a_refusing_commit_hook_is_a_refusal_not_an_error(repo, ctx):
    """It sends the run back to `run` with the hook's own words as the brief.
    Reading a non-zero exit as success would silently disable the revision
    loop."""
    perform("prepare_workspace", _run(), ctx)
    worktree = ws.worktree_path(repo, "run0001abcd99")
    (worktree / "login.py").write_text("console.log('debug')\n")

    hooks = Path(ws.git(worktree, "rev-parse", "--git-path", "hooks").out)
    if not hooks.is_absolute():
        hooks = worktree / hooks
    hooks.mkdir(parents=True, exist_ok=True)
    hook = hooks / "pre-commit"
    hook.write_text("#!/bin/sh\necho 'no console.log in source' >&2\nexit 1\n")
    hook.chmod(0o755)

    result = perform("commit_and_push", _run(), ctx)
    assert result.outcome == REFUSED
    assert "no console.log" in result.reason


# --- the pull request -------------------------------------------------------

def test_a_local_request_is_a_file_in_the_repository(repo, ctx):
    """No account, no token, no network — the shortest path to seeing this
    work, and the proof the forge seam is real."""
    perform("prepare_workspace", _run(), ctx)
    (ws.worktree_path(repo, "run0001abcd99") / "login.py").write_text("x = 1\n")
    perform("commit_and_push", _run(), ctx)

    result = perform("open_pull_request", _run(), ctx)
    assert result.outcome == OK

    number, url = result.reason.split("\t")
    assert Path(url).exists()
    assert "Add a login page" in Path(url).read_text()


def test_the_request_body_is_the_run_document(repo, ctx):
    """By the time a person reads it, the account of the work is written."""
    perform("prepare_workspace", _run(), ctx)
    (ws.worktree_path(repo, "run0001abcd99") / "a.py").write_text("x = 1\n")
    perform("commit_and_push", _run(), ctx)

    run = _run(document="## What was asked\n\nAdd login\n\n## What was built\n\nTwo files\n")
    result = perform("open_pull_request", run, ctx)
    body = Path(result.reason.split("\t")[1]).read_text()

    assert "What was asked" in body and "Two files" in body
    assert "Nothing merges itself" in body


def test_the_request_body_is_filtered_on_the_way_out(repo, ctx):
    """This is the egress point: the body is a document a model wrote from
    whatever it read in the checkout. Personal data is filtered *here* rather
    than at the tool-call seam — writing an address into a CODEOWNERS file is
    the file working; publishing it on a forge is not."""
    perform("prepare_workspace", _run(), ctx)
    (ws.worktree_path(repo, "run0001abcd99") / "a.py").write_text("x = 1\n")
    perform("commit_and_push", _run(), ctx)

    run = _run(document=("## What was built\n\nEmailed ian@example.com and set "
                         "AKIAIOSFODNN7EXAMPLE as the key.\n"))
    result = perform("open_pull_request", run, ctx)
    body = Path(result.reason.split("\t")[1]).read_text()

    assert "ian@example.com" not in body and "AKIAIOSFODNN7EXAMPLE" not in body
    assert "[redacted:email]" in body and "[redacted:aws-key]" in body
    assert sorted(result.redactions) == ["aws-key", "email"]


def test_a_clean_body_reports_no_redactions(repo, ctx):
    perform("prepare_workspace", _run(), ctx)
    (ws.worktree_path(repo, "run0001abcd99") / "a.py").write_text("x = 1\n")
    perform("commit_and_push", _run(), ctx)

    result = perform("open_pull_request", _run(document="## Built\n\nTwo files.\n"), ctx)
    assert result.redactions == ()


# --- watching ---------------------------------------------------------------

def test_an_open_request_keeps_the_run_waiting(repo, ctx):
    perform("prepare_workspace", _run(), ctx)
    (ws.worktree_path(repo, "run0001abcd99") / "a.py").write_text("x = 1\n")
    perform("commit_and_push", _run(), ctx)
    number = perform("open_pull_request", _run(), ctx).reason.split("\t")[0]

    result = perform("watch_pull_request", _run(pr_number=number), ctx)
    assert result.outcome == OK and result.event == ""


def test_a_merged_branch_reports_merge(repo, ctx):
    """Merged means git says the branch is an ancestor of the base — not that
    a file was ticked."""
    perform("prepare_workspace", _run(), ctx)
    (ws.worktree_path(repo, "run0001abcd99") / "a.py").write_text("x = 1\n")
    perform("commit_and_push", _run(), ctx)
    number = perform("open_pull_request", _run(), ctx).reason.split("\t")[0]

    _git(repo, "merge", "--no-ff", "-m", "merge", ws.branch_name("run0001abcd99"))

    c = Context(checkout=str(repo), repo_slug=str(repo), base="main",
                forge=forgelib.FORGES["local"],
                credential={"workspace": str(repo), "base": "main",
                            "branch": ws.branch_name("run0001abcd99")})
    result = perform("watch_pull_request", _run(pr_number=number), c)
    assert result.event == "merge"


def test_our_own_comment_is_not_a_reviewers(repo, ctx):
    """The factory pushes with the operator's credentials and IS the request's
    author, so telling them apart by author would find none."""
    perform("prepare_workspace", _run(), ctx)
    (ws.worktree_path(repo, "run0001abcd99") / "a.py").write_text("x = 1\n")
    perform("commit_and_push", _run(), ctx)
    number = perform("open_pull_request", _run(), ctx).reason.split("\t")[0]

    driver = forgelib.FORGES["local"]
    cred = {"workspace": str(repo)}
    driver.say(cred, str(repo), number, "started work")

    result = perform("watch_pull_request", _run(pr_number=number), ctx)
    assert result.event == ""          # ours does not trigger a rework


def test_a_reviewers_comment_becomes_the_brief(repo, ctx):
    perform("prepare_workspace", _run(), ctx)
    (ws.worktree_path(repo, "run0001abcd99") / "a.py").write_text("x = 1\n")
    perform("commit_and_push", _run(), ctx)
    number = perform("open_pull_request", _run(), ctx).reason.split("\t")[0]

    path = repo / forgelib.Local.DIR / f"{number}.md"
    path.write_text(path.read_text() + "\n\n## Comments\n---\nplease add a test\n")

    result = perform("watch_pull_request", _run(pr_number=number), ctx)
    assert result.event == "comment" and "add a test" in result.reason


def test_watching_without_a_request_is_an_error(repo, ctx):
    assert perform("watch_pull_request", _run(), ctx).outcome == ERROR


# --- teardown ---------------------------------------------------------------

def test_teardown_releases_the_worktree_but_keeps_the_branch(repo, ctx):
    """The branch is what a reviewer checks out — removing it deletes the work."""
    perform("prepare_workspace", _run(), ctx)
    (ws.worktree_path(repo, "run0001abcd99") / "a.py").write_text("x = 1\n")
    perform("commit_and_push", _run(), ctx)

    assert perform("teardown", _run(), ctx).outcome == OK
    assert not (ws.worktree_path(repo, "run0001abcd99")).exists()
    assert ws.git(repo, "rev-parse", "--verify",
                  ws.branch_name("run0001abcd99"), check=False).ok


def test_an_unknown_action_is_an_error(ctx):
    assert perform("make_coffee", _run(), ctx).outcome == ERROR


# --- a checkout that is not a checkout ---------------------------------------

def test_prepare_refuses_a_git_url_that_is_not_a_local_checkout(tmp_path, monkeypatch):
    """A repo's `git_url` is a string somebody typed. `prepare` used to `mkdir
    -p` it before asking whether it was a checkout at all, so a repo pointing at
    `git@github.com:acme/web.git` created a directory by that name — relative to
    wherever the server happened to be running.

    `root_of` existed to catch exactly this and nothing called it.
    """
    from open_refinery.pipeline import workspace as ws

    monkeypatch.chdir(tmp_path)
    with pytest.raises(ws.WorkspaceError, match="not a git checkout"):
        ws.create("git@github.com:acme/web-app.git", "run-1")

    assert not (tmp_path / "git@github.com:acme").exists(), \
        "refusing must not leave a directory behind"
