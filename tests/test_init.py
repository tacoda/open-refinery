"""`open-refinery init` — the first command a new install runs."""

import os
import stat

from open_refinery.cli import main


def _run(tmp_path, *args):
    """Run a CLI command with tmp_path as cwd, restoring the environment after.

    `init` deliberately exports SECRET_KEY/DATABASE_URL into the process so the
    store it then creates can write encrypted rows; a test that let that leak
    would quietly change every test after it.
    """
    before_cwd, before_env = os.getcwd(), dict(os.environ)
    os.chdir(tmp_path)
    try:
        return main(list(args))
    finally:
        os.chdir(before_cwd)
        os.environ.clear()
        os.environ.update(before_env)


def test_init_writes_an_env_file_and_creates_the_database(tmp_path):
    db = tmp_path / "test.db"
    assert _run(tmp_path, "init", "--database-url", f"sqlite:///{db}") == 0

    env = tmp_path / ".env"
    assert env.exists()
    assert db.exists()
    assert "SECRET_KEY=" in env.read_text()


def test_init_generates_a_high_entropy_secret(tmp_path):
    _run(tmp_path, "init", "--database-url", f"sqlite:///{tmp_path / 'a.db'}")
    line = next(ln for ln in (tmp_path / ".env").read_text().splitlines()
                if ln.startswith("SECRET_KEY="))
    assert len(line.removeprefix("SECRET_KEY=")) >= 32


def test_two_inits_generate_different_secrets(tmp_path):
    """A fixed key shipped in a release is every install sharing one."""
    def secret_from(sub):
        sub.mkdir()
        _run(sub, "init", "--database-url", f"sqlite:///{sub / 'a.db'}")
        return next(ln for ln in (sub / ".env").read_text().splitlines()
                    if ln.startswith("SECRET_KEY="))

    assert secret_from(tmp_path / "one") != secret_from(tmp_path / "two")


def test_env_file_is_not_world_readable(tmp_path):
    """It holds the key every stored secret is encrypted with."""
    _run(tmp_path, "init", "--database-url", f"sqlite:///{tmp_path / 'a.db'}")
    mode = (tmp_path / ".env").stat().st_mode
    assert not mode & stat.S_IRGRP
    assert not mode & stat.S_IROTH


def test_init_refuses_to_clobber_an_existing_env(tmp_path):
    """Overwriting it rotates SECRET_KEY, which makes every stored secret —
    every service token in the database — permanently unreadable."""
    env = tmp_path / ".env"
    env.write_text("SECRET_KEY=mine\n")
    assert _run(tmp_path, "init", "--database-url", f"sqlite:///{tmp_path / 'a.db'}") == 1
    assert env.read_text() == "SECRET_KEY=mine\n"


def test_force_overwrites_when_asked(tmp_path):
    env = tmp_path / ".env"
    env.write_text("SECRET_KEY=mine\n")
    assert _run(tmp_path, "init", "--force",
                "--database-url", f"sqlite:///{tmp_path / 'a.db'}") == 0
    assert env.read_text() != "SECRET_KEY=mine\n"


def test_init_leaves_a_database_doctor_is_happy_with(tmp_path):
    """The two commands have to agree, or `init` says done and `doctor` says broken."""
    from open_refinery.doctor import FAIL
    from open_refinery.store import connect

    db = tmp_path / "test.db"
    _run(tmp_path, "init", "--database-url", f"sqlite:///{db}")

    secret = next(ln for ln in (tmp_path / ".env").read_text().splitlines()
                  if ln.startswith("SECRET_KEY=")).removeprefix("SECRET_KEY=")

    from open_refinery.doctor import doctor
    report = doctor(connect(f"sqlite:///{db}"), environ={"SECRET_KEY": secret},
                    database_url=f"sqlite:///{db}")
    assert [c.name for c in report.checks if c.status == FAIL] == []
