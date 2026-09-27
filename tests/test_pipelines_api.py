"""Pipelines and runs over HTTP — defining the factory and putting work in."""

import pytest
from fastapi.testclient import TestClient

from open_refinery.models import Repository
from open_refinery.pipeline import default_pipeline
from open_refinery.processes import create_process
from open_refinery.store import connect
from open_refinery.users import create_session, create_user, ensure_presets
from open_refinery.web import create_app
from open_refinery.work_items import create_work_item


@pytest.fixture
def ctx():
    session = connect("sqlite:///:memory:", check_same_thread=False)
    ensure_presets(session)
    people = {p: create_user(session, f"{p}@x.io", "pw", p)[0]
              for p in ("developer", "lead", "platform", "admin")}
    dev = people["developer"]
    other, _ = create_user(session, "other@x.io", "pw", "developer")

    repo = Repository(name="app", git_url="git@x:app.git", owner_id=dev.id)
    session.add(repo)
    session.commit()
    session.refresh(repo)
    process = create_process(session, "flow", "board", ["todo", "done"], dev.id)
    item = create_work_item(session, repo.id, process.id, "Add login", dev.id)

    client = TestClient(create_app(session))

    def hdr(who):
        user = people[who] if who in people else other
        return {"Authorization": f"Bearer {create_session(session, user.id)}"}

    return session, client, hdr, item


# --- defining a pipeline ----------------------------------------------------

def test_the_default_template_is_available_to_start_from(ctx):
    _, client, hdr, _ = ctx
    body = client.get("/pipelines/templates/default", headers=hdr("developer")).json()
    assert body["name"] == "ship-a-ticket" and "run" in body["stages"]


def test_the_action_palette_is_listed_for_the_canvas(ctx):
    _, client, hdr, _ = ctx
    actions = client.get("/pipelines/actions", headers=hdr("developer")).json()
    names = {a["action"] for a in actions}
    assert "open_pull_request" in names and all(a["does"] for a in actions)


def test_platform_saves_a_pipeline(ctx):
    _, client, hdr, _ = ctx
    r = client.post("/pipelines", headers=hdr("platform"), json=default_pipeline())
    assert r.status_code == 201 and r.json()["version"] == 1


def test_a_developer_cannot_change_the_factory(ctx):
    """The stage graph is the factory, and the factory is platform's."""
    _, client, hdr, _ = ctx
    r = client.post("/pipelines", headers=hdr("developer"), json=default_pipeline())
    assert r.status_code == 403
    assert "platform@x.io" in r.json()["detail"]


def test_anyone_can_read_the_pipeline_they_work_inside(ctx):
    _, client, hdr, _ = ctx
    client.post("/pipelines", headers=hdr("platform"), json=default_pipeline())
    assert len(client.get("/pipelines", headers=hdr("developer")).json()) == 1


def test_saving_again_makes_a_new_version(ctx):
    _, client, hdr, _ = ctx
    client.post("/pipelines", headers=hdr("platform"), json=default_pipeline())
    second = client.post("/pipelines", headers=hdr("platform"),
                         json=default_pipeline()).json()

    assert second["version"] == 2
    assert len(client.get("/pipelines", headers=hdr("developer")).json()) == 1
    assert len(client.get("/pipelines?all_versions=true",
                          headers=hdr("developer")).json()) == 2


def test_an_invalid_pipeline_is_rejected_with_the_offending_stage(ctx):
    """An error naming a JSON path is an error somebody ignores."""
    _, client, hdr, _ = ctx
    r = client.post("/pipelines", headers=hdr("platform"),
                    json={"name": "broken", "first": "a",
                          "stages": {"a": {"action": "teardown", "next": "atlantis"}}})
    assert r.status_code == 400 and "'a'" in r.json()["detail"]


def test_validate_checks_without_saving(ctx):
    """What the canvas calls on every edit."""
    session, client, hdr, _ = ctx
    good = client.post("/pipelines/validate", headers=hdr("developer"),
                       json=default_pipeline()).json()
    assert good["ok"] is True and good["path"][0] == "prepare"

    bad = client.post("/pipelines/validate", headers=hdr("developer"),
                      json={"stages": {"a": {"action": "teardown"}}}).json()
    assert bad["ok"] is False and "no way out" in bad["error"]
    assert client.get("/pipelines", headers=hdr("developer")).json() == []


def test_a_pipeline_round_trips_through_export(ctx):
    _, client, hdr, _ = ctx
    saved = client.post("/pipelines", headers=hdr("platform"),
                        json=default_pipeline()).json()
    exported = client.get(f"/pipelines/{saved['id']}/export",
                          headers=hdr("developer")).json()

    again = client.post("/pipelines", headers=hdr("platform"), json=exported)
    assert again.status_code == 201


def test_saving_a_pipeline_is_audited(ctx):
    _, client, hdr, _ = ctx
    client.post("/pipelines", headers=hdr("platform"), json=default_pipeline())
    events = client.get("/events", headers=hdr("admin")).json()
    assert any(e["recipe"] == "pipeline-saved" for e in events)


# --- running work through it ------------------------------------------------

def test_a_run_starts_at_the_first_stage(ctx):
    _, client, hdr, item = ctx
    client.post("/pipelines", headers=hdr("platform"), json=default_pipeline())

    r = client.post("/runs", headers=hdr("developer"),
                    json={"work_item_id": item.id})
    assert r.status_code == 201
    assert r.json()["stage"] == "prepare"
    assert "Add login" in r.json()["document"]


def test_starting_a_run_needs_run_factory(ctx):
    _, client, hdr, item = ctx
    client.post("/pipelines", headers=hdr("platform"), json=default_pipeline())
    r = client.post("/runs", headers=hdr("admin"), json={"work_item_id": item.id})
    assert r.status_code == 403


def test_a_run_pins_its_pipeline_version(ctx):
    _, client, hdr, item = ctx
    client.post("/pipelines", headers=hdr("platform"), json=default_pipeline())
    run = client.post("/runs", headers=hdr("developer"),
                      json={"work_item_id": item.id}).json()
    client.post("/pipelines", headers=hdr("platform"), json=default_pipeline())

    assert client.get(f"/runs/{run['id']}", headers=hdr("developer")
                      ).json()["pipeline_version"] == 1


def test_an_unknown_work_item_is_a_404(ctx):
    _, client, hdr, _ = ctx
    client.post("/pipelines", headers=hdr("platform"), json=default_pipeline())
    assert client.post("/runs", headers=hdr("developer"),
                       json={"work_item_id": "nope"}).status_code == 404


def test_an_unknown_pipeline_is_a_404(ctx):
    _, client, hdr, item = ctx
    r = client.post("/runs", headers=hdr("developer"),
                    json={"work_item_id": item.id, "pipeline": "not-a-pipeline"})
    assert r.status_code == 404


def test_what_happens_next_answers_without_touching_anything(ctx):
    """Pure, so the canvas can ask freely."""
    _, client, hdr, item = ctx
    client.post("/pipelines", headers=hdr("platform"), json=default_pipeline())
    run = client.post("/runs", headers=hdr("developer"),
                      json={"work_item_id": item.id}).json()

    nxt = client.get(f"/runs/{run['id']}/next", headers=hdr("developer")).json()
    assert nxt["to"] == "prepare" and nxt["held"] is False


def test_you_see_your_own_runs_and_platform_sees_them_all(ctx):
    _, client, hdr, item = ctx
    client.post("/pipelines", headers=hdr("platform"), json=default_pipeline())
    client.post("/runs", headers=hdr("developer"), json={"work_item_id": item.id})

    assert len(client.get("/runs", headers=hdr("developer")).json()) == 1
    assert len(client.get("/runs", headers=hdr("platform")).json()) == 1
    assert client.get("/runs", headers=hdr("other")).json() == []


def test_a_run_you_do_not_own_is_a_404(ctx):
    _, client, hdr, item = ctx
    client.post("/pipelines", headers=hdr("platform"), json=default_pipeline())
    run = client.post("/runs", headers=hdr("developer"),
                      json={"work_item_id": item.id}).json()
    assert client.get(f"/runs/{run['id']}", headers=hdr("other")).status_code == 404


# --- approving a held stage -------------------------------------------------

def test_approving_needs_approve_code(ctx):
    _, client, hdr, item = ctx
    client.post("/pipelines", headers=hdr("platform"), json=default_pipeline())
    run = client.post("/runs", headers=hdr("developer"),
                      json={"work_item_id": item.id}).json()

    r = client.post(f"/runs/{run['id']}/approve", headers=hdr("platform"))
    assert r.status_code == 403 and "approve:code" in r.json()["detail"]


def test_you_cannot_approve_your_own_run(ctx):
    """The gate is a second pair of eyes or it is nothing."""
    _, client, hdr, item = ctx
    client.post("/pipelines", headers=hdr("platform"), json=default_pipeline())
    run = client.post("/runs", headers=hdr("developer"),
                      json={"work_item_id": item.id}).json()

    r = client.post(f"/runs/{run['id']}/approve", headers=hdr("developer"))
    assert r.status_code == 403 and "your own" in r.json()["detail"]


def test_another_developer_can_approve_and_it_is_audited(ctx):
    _, client, hdr, item = ctx
    client.post("/pipelines", headers=hdr("platform"), json=default_pipeline())
    run = client.post("/runs", headers=hdr("developer"),
                      json={"work_item_id": item.id}).json()

    r = client.post(f"/runs/{run['id']}/approve", headers=hdr("other"))
    assert r.status_code == 200 and r.json()["held"] is False

    events = client.get("/events", headers=hdr("admin")).json()
    assert any(e["recipe"] == "run-approved" for e in events)


# --- connecting a key is the only thing that has to change ------------------

def test_a_run_uses_the_stub_until_a_model_is_connected(ctx):
    """A fresh install walks the whole graph offline. That is what makes the
    factory inspectable before anybody has paid for anything."""
    from open_refinery.pipeline.runner import stub_phase
    from open_refinery.routers.pipelines import _phase_runner
    from open_refinery.pipeline import store as ps

    session, client, hdr, item = ctx
    client.post("/pipelines", headers=hdr("platform"), json=default_pipeline())
    run_id = client.post("/runs", headers=hdr("developer"),
                         json={"work_item_id": item.id}).json()["id"]

    run = ps.get_run(session, run_id)
    assert _phase_runner(session, run) is stub_phase


def test_connecting_a_model_key_switches_the_run_to_the_harness(ctx, monkeypatch):
    """The one change between a dry run and a real one."""
    from open_refinery import credentials as creds
    from open_refinery.pipeline.runner import stub_phase
    from open_refinery.routers.pipelines import _phase_runner
    from open_refinery.pipeline import store as ps

    session, client, hdr, item = ctx
    client.post("/pipelines", headers=hdr("platform"), json=default_pipeline())
    run_id = client.post("/runs", headers=hdr("developer"),
                         json={"work_item_id": item.id}).json()["id"]

    monkeypatch.setattr(creds, "verify_credential",
                        lambda key, cred: {"account": "anthropic"})
    client.post("/credentials", headers=hdr("developer"),
                json={"provider": "anthropic", "credential": {"api_key": "sk-test"}})

    run = ps.get_run(session, run_id)
    assert _phase_runner(session, run) is not stub_phase


def test_the_key_belongs_to_the_person_who_started_the_run(ctx, monkeypatch):
    """Somebody else's key does not make your run real — cost attributes to the
    person accountable for the work."""
    from open_refinery import credentials as creds
    from open_refinery.pipeline.runner import stub_phase
    from open_refinery.routers.pipelines import _phase_runner
    from open_refinery.pipeline import store as ps

    session, client, hdr, item = ctx
    client.post("/pipelines", headers=hdr("platform"), json=default_pipeline())
    run_id = client.post("/runs", headers=hdr("developer"),
                         json={"work_item_id": item.id}).json()["id"]

    monkeypatch.setattr(creds, "verify_credential",
                        lambda key, cred: {"account": "anthropic"})
    client.post("/credentials", headers=hdr("lead"),      # a different person
                json={"provider": "anthropic", "credential": {"api_key": "sk-test"}})

    run = ps.get_run(session, run_id)
    assert _phase_runner(session, run) is stub_phase
