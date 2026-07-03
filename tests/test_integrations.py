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
def secret(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "test-secret-key")


def test_crypto_round_trip():
    assert decrypt(encrypt("gho_secret")) == "gho_secret"


def test_encrypt_is_not_plaintext():
    assert encrypt("gho_secret") != "gho_secret"


def setup():
    conn = connect("sqlite:///:memory:")
    ian, _ = create_user(conn, "ian@x.dev", "pw", "developer")
    return conn, ian


def test_create_stores_token_encrypted_and_hidden():
    conn, ian = setup()
    integ = create_integration(conn, "github", "acme-gh", "gho_tok", ian.id)
    assert integ.kind == "github"
    # dataclass carries no token; the stored secret is ciphertext
    assert not hasattr(integ, "token")
    secret = conn.execute("SELECT secret FROM integrations WHERE id=?", (integ.id,)).fetchone()["secret"]
    assert secret != "gho_tok" and decrypt(secret) == "gho_tok"


def test_list_scopes_by_owner_and_omits_token():
    conn, ian = setup()
    mal, _ = create_user(conn, "mal@x.dev", "pw", "developer")
    create_integration(conn, "github", "a", "t1", ian.id)
    create_integration(conn, "github", "b", "t2", mal.id)
    assert len(list_integrations(conn)) == 2
    mine = list_integrations(conn, owner_id=ian.id)
    assert len(mine) == 1 and not hasattr(mine[0], "token")


def test_unknown_kind_rejected():
    conn, ian = setup()
    with pytest.raises(ValueError):
        create_integration(conn, "bitbucket", "x", "t", ian.id)


def test_verify_and_list_repos_use_adapter(monkeypatch):
    conn, ian = setup()
    integ = create_integration(conn, "github", "acme", "gho_tok", ian.id)
    seen = {}
    def fake_verify(tok):
        seen["verify"] = tok
        return {"account": "acme"}
    monkeypatch.setitem(integrations.ADAPTERS["github"], "verify", fake_verify)
    monkeypatch.setitem(integrations.ADAPTERS["github"], "list_repos",
                        lambda tok: [{"name": "web", "full_name": "acme/web", "ssh_url": "git@x:acme/web.git", "private": False}])
    assert integrations.verify(conn, integ.id) == {"account": "acme"}
    assert seen["verify"] == "gho_tok"  # decrypted token handed to the adapter
    repos = integrations.list_remote_repos(conn, integ.id)
    assert repos[0]["full_name"] == "acme/web"
