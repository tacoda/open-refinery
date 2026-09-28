import pytest
from fastapi.testclient import TestClient

from open_refinery import connect, create_user
from open_refinery.web import create_app


@pytest.fixture
def ctx():
    conn = connect("sqlite:///:memory:", check_same_thread=False)
    admin, admin_token = create_user(conn, "admin@x.dev", "pw", "admin")
    _, ops_token = create_user(conn, "ops@x.dev", "pw", "platform")
    client = TestClient(create_app(conn))
    return conn, client, admin, admin_token, ops_token


def auth(token):
    return {"Authorization": f"Bearer {token}"}


_dev_n = 0
def dev_auth(client, admin_token):
    """Create a developer (dev ops are developer-scoped) and return its auth header."""
    global _dev_n
    _dev_n += 1
    tok = client.post("/users", headers=auth(admin_token),
                      json={"email": f"dev{_dev_n}@x.dev", "password": "pw", "role": "developer"}
                      ).json()["token"]
    return auth(tok)


def test_health_needs_no_auth(ctx):
    _, client, *_ = ctx
    assert client.get("/health").json() == {"status": "ok"}


def test_me_requires_valid_token(ctx):
    _, client, admin, token, _ops = ctx
    assert client.get("/me").status_code == 401
    assert client.get("/me", headers=auth("bogus")).status_code == 401
    assert client.get("/me", headers=auth(token)).json()["email"] == "admin@x.dev"


def test_me_and_users_never_leak_secret_fields(ctx):
    _, client, admin, token, _ops = ctx
    LEAKY = {"pw_hash", "pw_salt", "token_hash", "secret", "totp_secret"}
    me = client.get("/me", headers=auth(token)).json()
    assert LEAKY.isdisjoint(me) and me["email"] == "admin@x.dev"
    users = client.get("/users", headers=auth(token)).json()
    assert users and all(LEAKY.isdisjoint(u) for u in users)
    login = client.post("/auth/login", json={"email": "admin@x.dev", "password": "pw"}).json()
    assert LEAKY.isdisjoint(login["user"]) and login["user"]["email"] == "admin@x.dev"


def test_onboarding_flag_lifecycle(ctx, monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "test-secret")  # completing onboarding writes an encrypted setting
    _, client, admin, token, ops_token = ctx
    h, ops = auth(token), auth(ops_token)
    assert client.get("/onboarding", headers=h).json()["onboarded"] is False
    # Finishing setup is an operations act, so it is platform's — admin manages
    # users and reads audit.
    assert client.post("/onboarding/complete", headers=h).status_code == 403
    assert client.post("/onboarding/complete", headers=ops).json()["onboarded"] is True
    assert client.get("/onboarding", headers=h).json()["onboarded"] is True


def test_improve_reports_a_score_and_traced_findings(ctx):
    """The three per-area debt scores became one lane (2.15.0): a team could
    celebrate a good `charter` score while the factory refused every run."""
    _, client, admin, token, _ops = ctx
    r = client.get("/improve", headers=auth(token))
    assert r.status_code == 200
    body = r.json()
    assert body["score"] == 100 and body["findings"] == []
    assert all(f["evidence"] for f in body["findings"])


def test_only_admin_creates_users(ctx):
    _, client, _, admin_token, ops_token = ctx
    # admin creates a developer, gets a show-once token back
    r = client.post("/users", headers=auth(admin_token),
                    json={"email": "dev@x.dev", "password": "pw", "role": "developer"})
    assert r.status_code == 201
    dev_token = r.json()["token"]

    # developer cannot create users
    r2 = client.post("/users", headers=auth(dev_token),
                     json={"email": "x@x.dev", "password": "pw", "role": "developer"})
    assert r2.status_code == 403


def test_roles_list_the_standard_configuration(ctx):
    _, client, _, admin_token, ops_token = ctx
    dev_token = client.post("/users", headers=auth(admin_token),
                            json={"email": "dev@x.dev", "password": "pw", "role": "developer"}
                            ).json()["token"]

    # the standard configuration, readable by any authed user
    names = [r["name"] for r in client.get("/roles", headers=auth(dev_token)).json()]
    assert names == ["auditor", "developer", "lead", "platform", "admin"]

    # These are PRESETS — starting points, not roles (2.16.0). Defining your
    # own lives at /presets; the shipped ones cannot be changed.
    assert client.put("/presets/admin", headers=auth(admin_token),
                      json={"rank": 15, "permissions": []}).status_code == 403
    assert client.delete("/presets/lead", headers=auth(admin_token)).status_code == 403


def test_ownership_scoping_on_repos(ctx):
    _, client, _, admin_token, ops_token = ctx
    d1 = dev_auth(client, admin_token)
    d2 = dev_auth(client, admin_token)

    client.post("/repositories", headers=d1, json={"name": "a", "git_url": "git@x:a.git"})
    client.post("/repositories", headers=d2, json={"name": "b", "git_url": "git@x:b.git"})

    # Each developer sees only their own; **platform** sees everyone's, because
    # operational visibility is platform's. Admin manages users and reads the
    # audit trail — it deliberately does not see the work.
    assert len(client.get("/repositories", headers=d1).json()) == 1
    assert len(client.get("/repositories", headers=auth(ops_token)).json()) == 2
    assert len(client.get("/repositories", headers=auth(admin_token)).json()) == 0


def test_a_work_item_needs_no_process_and_reads_its_stage_from_its_runs(ctx):
    """Until 3.0 creating work meant picking a `Process` first — a second stage
    graph the run ignored. A ticket is now just a ticket."""
    _, client, admin, admin_token, ops_token = ctx
    h = dev_auth(client, admin_token)   # a developer does the work
    repo = client.post("/repositories", headers=h,
                       json={"name": "or", "git_url": "git@x:or.git"}).json()
    item = client.post("/work-items", headers=h,
                       json={"repo_id": repo["id"], "title": "T"})
    assert item.status_code == 201, item.json()
    item = item.json()
    assert item["stage"] == "open"          # nothing has run yet
    assert "process_id" not in item

    listed = client.get("/work-items", headers=h).json()
    assert [(w["id"], w["stage"]) for w in listed] == [(item["id"], "open")]


def test_authorize_gate_allows_and_denies(ctx):
    conn, client, admin, admin_token, ops_token = ctx
    from open_refinery import create_policy, query_events
    h = auth(admin_token)
    # audit mode (default): an unlisted egress is allowed
    ok = client.post("/authorize", headers=h,
                     json={"action": "egress", "resource": "api.example.com", "intent": "fetch"})
    assert ok.status_code == 200 and ok.json()["allowed"] is True

    # deny egress in the payments namespace → 403, and the refusal is audited with intent
    create_policy(conn, "deny", admin.id, action="egress", resource="*", namespace="payments")
    blocked = client.post("/authorize", headers=h,
                          json={"action": "egress", "resource": "api.stripe.com",
                                "namespace": "payments", "intent": "exfiltrate"})
    assert blocked.status_code == 403
    denied = [e for e in query_events(conn) if e.recipe == "denied"]
    assert len(denied) == 1
    # a different namespace is not gated
    other = client.post("/authorize", headers=h,
                        json={"action": "egress", "resource": "api.stripe.com", "namespace": "research"})
    assert other.status_code == 200


def test_approvals_lists_the_runs_waiting_on_a_person(ctx):
    """`/approvals` used to be a queue of kanban-transition requests signed by
    role rank. It is now what actually waits: a held run, cleared by somebody
    holding `approve:code`."""
    from open_refinery import create_repository, create_work_item
    from open_refinery.pipeline import store as ps

    conn, client, _, admin_token, ops_token = ctx
    h = dev_auth(client, admin_token)
    me = client.get("/me", headers=h).json()

    repo = create_repository(conn, "or", "git@x:or.git", me["id"])
    item = create_work_item(conn, repo.id, "T", me["id"])
    pipeline = ps.ensure_default(conn, me["id"])
    run = ps.start_run(conn, item.id, pipeline, repo.id, me["id"], spec="do it")

    assert client.get("/approvals", headers=h).json() == []   # running, not held

    run.held = True
    conn.add(run); conn.commit()
    waiting = client.get("/approvals", headers=h).json()
    assert len(waiting) == 1
    assert waiting[0]["run_id"] == run.id
    assert waiting[0]["approve_with"] == f"POST /runs/{run.id}/approve"
def test_duplicate_repo_conflicts(ctx):
    _, client, _, admin_token, ops_token = ctx
    h = dev_auth(client, admin_token)
    client.post("/repositories", headers=h, json={"name": "a", "git_url": "git@x:a.git"})
    dup = client.post("/repositories", headers=h, json={"name": "b", "git_url": "git@x:a.git"})
    assert dup.status_code == 409


def test_oversight_is_set_on_the_repository(ctx):
    """The dial moved off the process in 3.0. An unknown level is refused at the
    boundary rather than stored."""
    _, client, _, admin_token, ops_token = ctx
    h = dev_auth(client, admin_token)
    repo = client.post("/repositories", headers=h,
                       json={"name": "or", "git_url": "git@x:or.git"}).json()
    assert repo["oversight"] == "supervised"

    ok = client.put(f"/repositories/{repo['id']}", headers=h, json={"oversight": "dark"})
    assert ok.status_code == 200 and ok.json()["oversight"] == "dark"

    bad = client.put(f"/repositories/{repo['id']}", headers=h, json={"oversight": "loose"})
    assert bad.status_code == 400
    assert "unknown oversight level" in bad.json()["detail"]
