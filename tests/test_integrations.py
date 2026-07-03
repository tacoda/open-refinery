import pytest

from open_refinery import (
    connect,
    create_integration,
    create_user,
    list_integrations,
)
from open_refinery import integrations
from open_refinery.crypto import decrypt, encrypt


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "test-secret-key")
    # stub the GitHub adapter so create/verify need no network
    monkeypatch.setitem(integrations.ADAPTERS["github"], "verify",
                        lambda tok: {"account": "acme"})


def test_crypto_round_trip():
    assert decrypt(encrypt("gho_secret")) == "gho_secret"
    assert encrypt("gho_secret") != "gho_secret"


def setup():
    conn = connect("sqlite:///:memory:")
    ian, _ = create_user(conn, "ian@x.dev", "pw", "developer")
    return conn, ian


def test_create_labels_by_account_and_stores_credential_encrypted():
    conn, ian = setup()
    integ = create_integration(conn, "github", {"token": "gho_tok"}, ian.id)
    assert integ.kind == "github" and integ.account == "acme"
    assert not hasattr(integ, "token")  # no credential on the dataclass
    secret = conn.execute("SELECT secret FROM integrations WHERE id=?", (integ.id,)).fetchone()["secret"]
    assert "gho_tok" not in secret  # encrypted at rest
    assert decrypt(secret) == '{"token": "gho_tok"}'


def test_list_scopes_by_owner():
    conn, ian = setup()
    mal, _ = create_user(conn, "mal@x.dev", "pw", "developer")
    create_integration(conn, "github", {"token": "t1"}, ian.id)
    create_integration(conn, "github", {"token": "t2"}, mal.id)
    assert len(list_integrations(conn)) == 2
    assert len(list_integrations(conn, owner_id=ian.id)) == 1


def test_unknown_kind_rejected():
    conn, ian = setup()
    with pytest.raises(ValueError):
        create_integration(conn, "bitbucket", {"token": "t"}, ian.id)


def test_verify_and_repos_use_decrypted_credential(monkeypatch):
    conn, ian = setup()
    integ = create_integration(conn, "github", {"token": "gho_tok"}, ian.id)
    seen = {}
    def fake_verify(cred):
        seen["cred"] = cred
        return {"account": "acme"}
    monkeypatch.setitem(integrations.ADAPTERS["github"], "verify", fake_verify)
    monkeypatch.setitem(integrations.ADAPTERS["github"], "list_repos",
                        lambda cred: [{"name": "web", "full_name": "acme/web",
                                       "ssh_url": "git@x:acme/web.git", "private": False}])
    assert integrations.verify(conn, integ.id) == {"account": "acme"}
    assert seen["cred"] == {"token": "gho_tok"}  # decrypted credential handed to the adapter
    assert integrations.list_remote_repos(conn, integ.id)[0]["full_name"] == "acme/web"


def test_delete_integration():
    conn, ian = setup()
    integ = create_integration(conn, "github", {"token": "gho_tok"}, ian.id)
    assert len(list_integrations(conn)) == 1
    integrations.delete_integration(conn, integ.id)
    assert list_integrations(conn) == []


def test_jira_credential_is_multi_field(monkeypatch):
    conn, ian = setup()
    seen = {}
    def fake(cred):
        seen["cred"] = cred
        return {"account": "Jira User"}
    monkeypatch.setitem(integrations.ADAPTERS["jira"], "verify", fake)
    integ = create_integration(conn, "jira",
                               {"site": "acme.atlassian.net", "email": "a@x.dev", "token": "jtok"}, ian.id)
    assert integ.kind == "jira" and integ.account == "Jira User"
    assert seen["cred"]["site"] == "acme.atlassian.net"


def test_connect_state_is_one_time():
    conn, ian = setup()
    state = integrations.create_connect_state(conn, ian.id, "github")
    assert integrations.pop_connect_state(conn, state) == ian.id
    assert integrations.pop_connect_state(conn, state) is None  # consumed
