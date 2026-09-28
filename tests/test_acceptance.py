"""The 3.0 acceptance test — PLAN-3.0 §7, as a test rather than a checklist.

One scripted path over the real API, against a real git repository, with the
`local` forge: **no accounts, no network, no keys.** That constraint is the
point. An acceptance test that needs somebody's API key is one nobody runs, and
a claim that the product works end to end has to be checkable by anybody who
clones the repo.

What it does not prove: that a model produces good code. It proves the factory
around the model is wired — that a ticket arriving at the front door reaches a
pull request without a person doing anything the product did not ask for, and
that the things which must not happen (merging itself, an unsigned webhook
getting in, an unverifiable audit trail) do not.

The one substitution is the phase runner: a stand-in that writes a file where
the harness would write one. Everything else — intake, the graph, the worktree,
the branch, the delivery gate, the forge, the audit chain — is the real thing.
"""

import json
import subprocess

import pytest
from fastapi.testclient import TestClient

from open_refinery import connect
from open_refinery.pipeline.graph import OK, Result
from open_refinery.web import create_app


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=str(cwd), check=True,
                   capture_output=True, text=True)


@pytest.fixture
def checkout(tmp_path):
    """A real repository with one commit on `main`."""
    root = tmp_path / "web-app"
    root.mkdir()
    _git(root, "init", "-b", "main")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Test")
    (root / "README.md").write_text("# web-app\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "first")
    return root


@pytest.fixture
def api(tmp_path):
    session = connect(f"sqlite:///{tmp_path / 'acceptance.db'}", check_same_thread=False)
    return TestClient(create_app(session)), session


# What a phase has to say for the contract to let it through. These are the
# *shapes* the contracts demand, not decoration: `PROVEN: yes` with no command
# under it is downgraded to `unproven`, because a model saying it ran something
# is not a transcript containing it.
ANSWERS = {
    "prove": "PROVEN: yes\n\n$ pytest -q\n2 passed\n",
    "review": "VERDICT: pass\n\nNothing blocking.\n",
    "security": "VERDICT: pass\n\nNo new surface.\n",
}


def writes_a_file(run, stage, ctx) -> Result:
    """Stand in for the harness. Writes where a real turn would write.

    The default stub writes nothing, which is correct for testing the graph and
    wrong for testing delivery: a run that produces no diff is refused by the
    gate — which is the gate working, not the loop completing.

    It answers each contract in the form that contract requires, so what is
    exercised here is the real parser and the real downgrade rules.
    """
    from pathlib import Path

    from open_refinery.pipeline import workspace as ws

    if stage.phase == "run":
        tree = ws.worktree_path(ctx.checkout, run.id)
        (Path(tree) / "login.py").write_text("def login():\n    return True\n")
    return Result(OK, produced=tuple(stage.produces),
                  reason=ANSWERS.get(stage.phase, f"[acceptance] {stage.phase}"))


def test_a_ticket_becomes_a_pull_request_and_nothing_merges_itself(api, checkout):
    client, session = api

    # 1. install and sign up. The first account is the admin, and signing up is
    #    what seeds a workflow to run.
    boss = client.post("/setup", json={"email": "boss@acme.dev", "password": "pw"}).json()
    admin = {"Authorization": f"Bearer {boss['token']}"}

    pipelines = client.get("/pipelines", headers=admin).json()
    assert [p["name"] for p in pipelines] == ["ship-a-ticket"], \
        "a fresh install has the default to build from"

    # 2. a person to do the work, with permissions rather than a role
    dev = client.post("/users", headers=admin, json={
        "email": "dev@acme.dev", "password": "pw", "role": "developer"}).json()
    hers = {"Authorization": f"Bearer {dev['token']}"}
    assert "run:factory" in dev["user"]["permissions"]

    # somebody else to sign: a run's own author may not clear its gate
    reviewer = client.post("/users", headers=admin, json={
        "email": "lead@acme.dev", "password": "pw", "role": "developer"}).json()
    theirs = {"Authorization": f"Bearer {reviewer['token']}"}

    # 3. a repository, pointed at a checkout that exists. The `local` forge
    #    writes the pull request as a file, so this needs no accounts.
    repo = client.post("/repositories", headers=hers, json={
        "name": "web-app", "git_url": str(checkout)}).json()
    client.put(f"/repositories/{repo['id']}", headers=admin,
               json={"forge": "local", "base_branch": "main"})
    # 4. a ticket arrives at the front door, signed, and starts a run by itself
    integ = _tracker(session, dev["user"]["id"], repo["id"])
    body = json.dumps({"action": "opened", "issue": {
        "number": 1, "title": "Add a login page", "body": "People need to sign in.",
        "state": "open"}}).encode()

    refused = client.post(f"/intake/{integ.id}", content=body,
                          headers={"X-Hub-Signature-256": "sha256=wrong"})
    assert refused.status_code == 401, "an unsigned delivery is not work"

    from open_refinery.intake import sign
    accepted = client.post(f"/intake/{integ.id}", content=body,
                           headers={"X-Hub-Signature-256":
                                    f"sha256={sign(integ.webhook_secret, body)}"}).json()
    assert accepted["accepted"] and accepted["run"], "autostart started a run"

    # 5. the factory does the work: workers advance the run one stage at a time,
    #    and stops at the plan gate, which is the gate doing its job
    _work(session, str(checkout))
    held = client.get(f"/runs/{accepted['run']}", headers=hers).json()
    assert held["held"] and held["stage"] == "plan", \
        "the default workflow shows a person the plan before building"

    # the author may not clear their own gate
    mine = client.post(f"/runs/{accepted['run']}/approve", headers=hers, json={})
    assert mine.status_code == 403 and "your own run" in mine.json()["detail"]

    # somebody else does, and only then does the rest happen
    client.post(f"/runs/{accepted['run']}/approve", headers=theirs, json={})
    _work(session, str(checkout))

    run = client.get(f"/runs/{accepted['run']}", headers=hers).json()

    # 6. a pull request, with the run document as its body
    assert run["pr_url"], (
        f"the run stopped at {run['stage']!r} without a pull request: "
        f"{[(s['stage'], s['outcome'], s['why'][:60]) for s in run['steps']]}")
    pr = (checkout / ".open-refinery" / "requests" /
          f"{run['pr_url'].split('/')[-1]}")
    text = pr.read_text() if pr.exists() else open(run["pr_url"]).read()
    assert "Add a login page" in text, "the ticket is the request's subject"

    # 7. nothing merged itself
    assert run["outcome"] != "landed", "the factory does not merge its own work"
    merged = _git_out(checkout, "branch", "--merged", "main")
    assert "open-refinery/" not in merged, "the work is on a branch a person reviews"

    # 8. and the trail holds
    verified = client.get("/audit/verify", headers=admin).json()
    assert verified["ok"], verified


def test_the_same_loop_leaves_a_verifiable_trail(api, checkout):
    """Auditability is not a feature you check separately — it is whether the
    run that just happened can be proven to have happened that way."""
    client, session = api
    boss = client.post("/setup", json={"email": "boss@acme.dev", "password": "pw"}).json()
    admin = {"Authorization": f"Bearer {boss['token']}"}

    repo = client.post("/repositories", headers=admin, json={
        "name": "web-app", "git_url": str(checkout)}).json()
    client.put(f"/repositories/{repo['id']}", headers=admin,
               json={"forge": "local", "base_branch": "main"})
    item = client.post("/work-items", headers=admin, json={
        "repo_id": repo["id"], "title": "Add a login page"}).json()
    started = client.post("/runs", headers=admin, json={"work_item_id": item["id"]}).json()

    signer = client.post("/users", headers=admin, json={
        "email": "lead@acme.dev", "password": "pw", "role": "developer"}).json()
    _work(session, str(checkout))
    client.post(f"/runs/{started['id']}/approve",
                headers={"Authorization": f"Bearer {signer['token']}"}, json={})
    _work(session, str(checkout))

    export = client.get("/audit/export", headers=admin).json()
    assert export["signature"], "an export a reader cannot check is a text file"
    assert any(e["subject"] == started["id"] for e in export["events"]), \
        "the run is in the trail by id"


# --- helpers ----------------------------------------------------------------

def _tracker(session, owner_id, repo_id):
    """A tracker integration wired for intake, without calling GitHub."""
    import json as _json

    from open_refinery.crypto import encrypt
    from open_refinery.intake import configure
    from open_refinery.models import Integration

    integ = Integration(kind="github-issues", account="acme", owner_id=owner_id,
                        secret=encrypt(_json.dumps({"token": "t"})))
    session.add(integ)
    session.commit()
    session.refresh(integ)
    integ, _ = configure(session, integ.id, repo_id=repo_id, autostart=True, rotate_secret=True)
    return integ


def _work(session, checkout):
    """Run the factory until it stops, with the file-writing stand-in."""
    from open_refinery.pipeline import workers
    from open_refinery.store import SqliteSink

    workers.drain(session, "acceptance", SqliteSink(session),
                  phase_runner=writes_a_file, limit=40)


def _git_out(cwd, *args):
    return subprocess.run(["git", *args], cwd=str(cwd), check=True,
                          capture_output=True, text=True).stdout
