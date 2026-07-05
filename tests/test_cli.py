from open_refinery import authenticate, connect
from open_refinery.cli import main


def test_create_admin_makes_usable_admin(tmp_path, monkeypatch, capsys):
    url = f"sqlite:///{tmp_path / 'or.db'}"
    monkeypatch.setenv("DATABASE_URL", url)

    rc = main(["create-admin", "--email", "boss@x.dev", "--password", "pw"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "token:" in out

    # the admin exists and authenticates
    conn = connect(url)
    user = authenticate(conn, "boss@x.dev", "pw")
    assert user is not None and user.role == "admin"


def test_create_admin_rejects_duplicate(tmp_path, monkeypatch, capsys):
    url = f"sqlite:///{tmp_path / 'or.db'}"
    monkeypatch.setenv("DATABASE_URL", url)

    assert main(["create-admin", "--email", "boss@x.dev", "--password", "pw"]) == 0
    assert main(["create-admin", "--email", "boss@x.dev", "--password", "pw"]) == 1
    assert "already exists" in capsys.readouterr().err


def test_migrate_initializes_then_up_to_date(tmp_path, monkeypatch, capsys):
    url = f"sqlite:///{tmp_path / 'or.db'}"
    monkeypatch.setenv("DATABASE_URL", url)

    assert main(["migrate"]) == 0
    assert "initialized database" in capsys.readouterr().out

    assert main(["migrate"]) == 0                       # idempotent
    assert "up to date" in capsys.readouterr().out
