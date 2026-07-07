import pytest
from fastapi.testclient import TestClient

from open_refinery import connect, create_user
from open_refinery.web import create_app


@pytest.fixture
def ctx(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    conn = connect("sqlite:///:memory:", check_same_thread=False)
    toks = {}
    for role in ("developer", "platform", "admin"):
        _, toks[role] = create_user(conn, f"{role}@x.dev", "pw", role)
    return conn, TestClient(create_app(conn)), toks


def h(t):
    return {"Authorization": f"Bearer {t}"}


def test_dev_operations_are_developer_only(ctx):
    _, client, toks = ctx
    body = {"name": "r", "git_url": "git@x:r.git"}
    assert client.post("/repositories", headers=h(toks["developer"]), json=body).status_code == 201
    # admin is oversight-only, platform handles platform concerns — neither operates the dev chain
    assert client.post("/repositories", headers=h(toks["admin"]), json=body).status_code == 403
    assert client.post("/repositories", headers=h(toks["platform"]), json=body).status_code == 403


def test_platform_config_is_platform_only(ctx):
    _, client, toks = ctx
    body = {"name": "opus", "kind": "model", "endpoint": "claude-opus-4-8"}
    assert client.post("/targets", headers=h(toks["platform"]), json=body).status_code == 201
    assert client.post("/targets", headers=h(toks["developer"]), json=body).status_code == 403
    assert client.post("/targets", headers=h(toks["admin"]), json=body).status_code == 403


def test_oversight_reads_exclude_developers(ctx):
    _, client, toks = ctx
    for role in ("platform", "admin"):
        assert client.get("/events", headers=h(toks[role])).status_code == 200
    assert client.get("/events", headers=h(toks["developer"])).status_code == 403  # dev has no org audit


def test_everyone_sees_metrics_and_overview_data(ctx):
    _, client, toks = ctx
    for role in ("developer", "platform", "admin"):
        assert client.get("/metrics", headers=h(toks[role])).status_code == 200


def test_auditor_grant_is_read_only(ctx):
    conn, client, toks = ctx
    # admin mints a time-boxed auditor token
    r = client.post("/auditor-grants", headers=h(toks["admin"]), json={"label": "EY", "ttl_days": 7})
    assert r.status_code == 201
    atok = r.json()["token"]
    ah = {"Authorization": f"Bearer {atok}"}
    # auditor can read evidence + verify the audit chain
    assert client.get("/evidence?framework=soc2", headers=ah).status_code == 200
    assert client.get("/audit/verify", headers=ah).status_code == 200
    # but cannot mutate anything, nor mint further grants
    assert client.post("/repositories", headers=ah, json={"name": "r", "git_url": "g"}).status_code == 403
    assert client.post("/auditor-grants", headers=ah, json={"label": "x"}).status_code == 403
