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


def test_create_labels_by_account_and_stores_token_encrypted():
    conn, ian = setup()
    integ = create_integration(conn, "github", "gho_tok", ian.id)
    assert integ.kind == "github" and integ.account == "acme"
    assert not hasattr(integ, "token")  # no token on the dataclass
    secret = conn.execute("SELECT secret FROM integrations WHERE id=?", (integ.id,)).fetchone()["secret"]
    assert secret != "gho_tok" and decrypt(secret) == "gho_tok"


def test_list_scopes_by_owner():
    conn, ian = setup()
    mal, _ = create_user(conn, "mal@x.dev", "pw", "developer")
    create_integration(conn, "github", "t1", ian.id)
    create_integration(conn, "github", "t2", mal.id)
    assert len(list_integrations(conn)) == 2
    assert len(list_integrations(conn, owner_id=ian.id)) == 1


def test_unknown_kind_rejected():
    conn, ian = setup()
    with pytest.raises(ValueError):
        create_integration(conn, "bitbucket", "t", ian.id)


def test_verify_and_repos_use_decrypted_token(monkeypatch):
    conn, ian = setup()
    integ = create_integration(conn, "github", "gho_tok", ian.id)
    seen = {}
    def fake_verify(tok):
        seen["tok"] = tok
        return {"account": "acme"}
    monkeypatch.setitem(integrations.ADAPTERS["github"], "verify", fake_verify)
    monkeypatch.setitem(integrations.ADAPTERS["github"], "list_repos",
                        lambda tok: [{"name": "web", "full_name": "acme/web",
                                      "ssh_url": "git@x:acme/web.git", "private": False}])
    assert integrations.verify(conn, integ.id) == {"account": "acme"}
    assert seen["tok"] == "gho_tok"  # decrypted token handed to the adapter
    assert integrations.list_remote_repos(conn, integ.id)[0]["full_name"] == "acme/web"


def test_connect_state_is_one_time():
    conn, ian = setup()
    state = integrations.create_connect_state(conn, ian.id, "github")
    assert integrations.pop_connect_state(conn, state) == ian.id
    assert integrations.pop_connect_state(conn, state) is None  # consumed
