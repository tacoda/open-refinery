import pytest
from fastapi.testclient import TestClient

from open_refinery import connect, create_user
from open_refinery.web import create_app


@pytest.fixture
def ctx():
    conn = connect("sqlite:///:memory:", check_same_thread=False)
    admin, admin_token = create_user(conn, "admin@x.dev", "pw", "admin")
    client = TestClient(create_app(conn))
    return conn, client, admin, admin_token


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
    _, client, admin, token = ctx
    assert client.get("/me").status_code == 401
    assert client.get("/me", headers=auth("bogus")).status_code == 401
    assert client.get("/me", headers=auth(token)).json()["email"] == "admin@x.dev"


def test_me_and_users_never_leak_secret_fields(ctx):
    _, client, admin, token = ctx
    LEAKY = {"pw_hash", "pw_salt", "token_hash", "secret"}
    me = client.get("/me", headers=auth(token)).json()
    assert LEAKY.isdisjoint(me) and me["email"] == "admin@x.dev"
    users = client.get("/users", headers=auth(token)).json()
    assert users and all(LEAKY.isdisjoint(u) for u in users)


def test_onboarding_flag_lifecycle(ctx, monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "test-secret")  # completing onboarding writes an encrypted setting
    _, client, admin, token = ctx
    h = auth(token)
    assert client.get("/onboarding", headers=h).json()["onboarded"] is False
    assert client.post("/onboarding/complete", headers=h).json()["onboarded"] is True
    assert client.get("/onboarding", headers=h).json()["onboarded"] is True


def test_health_areas_scores_all_three(ctx):
    # regression: the /health route handler must not shadow the debt.health scorer
    _, client, admin, token = ctx
    r = client.get("/health/areas", headers=auth(token))
    assert r.status_code == 200
    assert {"factory", "harness", "charter"} <= set(r.json())


def test_only_admin_creates_users(ctx):
    _, client, _, admin_token = ctx
    # admin creates a developer, gets a show-once token back
    r = client.post("/users", headers=auth(admin_token),
                    json={"email": "dev@x.dev", "password": "pw", "role": "developer"})
    assert r.status_code == 201
    dev_token = r.json()["token"]

    # developer cannot create users
    r2 = client.post("/users", headers=auth(dev_token),
                     json={"email": "x@x.dev", "password": "pw", "role": "developer"})
    assert r2.status_code == 403


def test_roles_are_a_fixed_ladder(ctx):
    _, client, _, admin_token = ctx
    dev_token = client.post("/users", headers=auth(admin_token),
                            json={"email": "dev@x.dev", "password": "pw", "role": "developer"}
                            ).json()["token"]

    # fixed three-tier ladder, readable by any authed user
    names = [r["name"] for r in client.get("/roles", headers=auth(dev_token)).json()]
    assert names == ["developer", "platform", "admin"]

    # creating/deleting arbitrary roles is intentionally not exposed
    assert client.post("/roles", headers=auth(admin_token),
                       json={"name": "senior", "rank": 15}).status_code in (404, 405)
    assert client.delete("/roles/admin", headers=auth(admin_token)).status_code in (404, 405)


def test_ownership_scoping_on_repos(ctx):
    _, client, _, admin_token = ctx
    d1 = dev_auth(client, admin_token)
    d2 = dev_auth(client, admin_token)

    client.post("/repositories", headers=d1, json={"name": "a", "git_url": "git@x:a.git"})
    client.post("/repositories", headers=d2, json={"name": "b", "git_url": "git@x:b.git"})

    # each developer sees only their own; admin (oversight) sees all
    assert len(client.get("/repositories", headers=d1).json()) == 1
    assert len(client.get("/repositories", headers=auth(admin_token)).json()) == 2


def test_end_to_end_transition_and_audit(ctx):
    _, client, admin, admin_token = ctx
    h = dev_auth(client, admin_token)   # developers operate the dev chain
    repo = client.post("/repositories", headers=h,
                       json={"name": "or", "git_url": "git@x:or.git"}).json()
    proc = client.post("/processes", headers=h,
                       json={"name": "flow", "archetype": "doctrine",
                             "stages": ["todo", "doing", "done"]}).json()
    item = client.post("/work-items", headers=h,
                       json={"repo_id": repo["id"], "process_id": proc["id"],
                             "title": "T"}).json()
    assert item["current_stage"] == "todo"

    moved = client.post(f"/work-items/{item['id']}/transition", headers=h,
                        json={"to": "doing"})
    assert moved.status_code == 200 and moved.json()["current_stage"] == "doing"

    # illegal move rejected
    bad = client.post(f"/work-items/{item['id']}/transition", headers=h,
                      json={"to": "todo"})  # doing -> todo not allowed (doctrine)
    assert bad.status_code == 409

    # audit trail records the one valid transition — read by admin (oversight)
    events = client.get(f"/events?subject={item['id']}", headers=auth(admin_token)).json()
    assert len(events) == 1 and events[0]["recipe"] == "transition"


def test_authorize_gate_allows_and_denies(ctx):
    conn, client, admin, admin_token = ctx
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


def test_oversight_approval_flow(ctx):
    _, client, _, admin_token = ctx
    h = dev_auth(client, admin_token)
    repo = client.post("/repositories", headers=h,
                       json={"name": "or", "git_url": "git@x:or.git"}).json()
    proc = client.post("/processes", headers=h,
                       json={"name": "flow", "archetype": "board", "stages": ["todo", "doing"],
                             "oversight": "assisted", "min_approver_role": "developer"}).json()
    item = client.post("/work-items", headers=h,
                       json={"repo_id": repo["id"], "process_id": proc["id"],
                             "title": "T"}).json()

    # without approval → 409
    blocked = client.post(f"/work-items/{item['id']}/transition", headers=h,
                          json={"to": "doing"})
    assert blocked.status_code == 409

    # with approve=true → applies (min approver is developer, so self-approval works)
    ok = client.post(f"/work-items/{item['id']}/transition", headers=h,
                     json={"to": "doing", "approve": True})
    assert ok.status_code == 200 and ok.json()["current_stage"] == "doing"

    events = client.get(f"/events?subject={item['id']}", headers=auth(admin_token)).json()
    assert {e["recipe"] for e in events} == {"transition", "approval"}


def test_duplicate_repo_conflicts(ctx):
    _, client, _, admin_token = ctx
    h = dev_auth(client, admin_token)
    client.post("/repositories", headers=h, json={"name": "a", "git_url": "git@x:a.git"})
    dup = client.post("/repositories", headers=h, json={"name": "b", "git_url": "git@x:a.git"})
    assert dup.status_code == 409
