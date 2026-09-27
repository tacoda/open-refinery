"""Effective config and its provenance — the source tag is the whole point."""

from open_refinery.config import DB, ENV, KEYS, Key, Value, effective, get, resolve
from open_refinery.settings import set_setting
from open_refinery.store import connect
from open_refinery.users import create_user, ensure_default_roles


def _session():
    s = connect("sqlite:///:memory:")
    ensure_default_roles(s)
    return s


def test_unset_env_key_reports_its_default():
    key = Key("PORT", ENV, "8000", help="")
    assert resolve(key, {}, None) == Value("PORT", "8000", "default", False, "")


def test_env_value_wins_and_is_tagged_env():
    key = Key("PORT", ENV, "8000", help="")
    assert resolve(key, {"PORT": "9000"}, None).value == "9000"
    assert resolve(key, {"PORT": "9000"}, None).source == "env"


def test_blank_env_value_does_not_count_as_set():
    """An exported-but-empty SECRET_KEY is the same problem as an unset one;
    reporting it as configured is how that hour gets lost."""
    key = Key("SECRET_KEY", ENV, "", help="", secret=True)
    assert resolve(key, {"SECRET_KEY": ""}, None).source == "default"


def test_secret_value_is_masked_never_printed():
    key = Key("SECRET_KEY", ENV, "", help="", secret=True)
    got = resolve(key, {"SECRET_KEY": "hunter2-hunter2-hunter2"}, None)
    assert "hunter2" not in got.value
    assert got.value == "(set)"
    assert got.source == "env"


def test_db_value_wins_and_is_tagged_database():
    key = Key("policy.enforcement", DB, "audit", help="")
    assert resolve(key, {}, "strict") == Value("policy.enforcement", "strict", "database", False, "")


def test_effective_reads_db_keys_through_the_session():
    session = _session()
    admin, _ = create_user(session, "a@example.com", "pw", "admin")
    set_setting(session, "policy.enforcement", "strict", admin.id)

    by_key = {v.key: v for v in effective(session, environ={})}
    assert by_key["policy.enforcement"].value == "strict"
    assert by_key["policy.enforcement"].source == "database"


def test_effective_without_a_session_falls_back_to_defaults():
    """`config` has to work before the database exists — that is when it is
    most likely to be run."""
    by_key = {v.key: v for v in effective(None, environ={})}
    assert by_key["policy.enforcement"].value == "audit"
    assert by_key["policy.enforcement"].source == "default"


def test_effective_covers_every_declared_key():
    assert [v.key for v in effective(None, environ={})] == [k.name for k in KEYS]


def test_get_returns_the_real_value_not_the_mask():
    assert get("SECRET_KEY", environ={"SECRET_KEY": "real-secret"}) == "real-secret"


def test_get_falls_back_to_the_default():
    assert get("PORT", environ={}) == "8000"


def test_get_rejects_an_undeclared_key():
    """A key read somewhere but absent from the catalog is one nobody can
    discover — the failure this module exists to prevent."""
    try:
        get("NOT_A_SETTING", environ={})
    except KeyError as exc:
        assert "NOT_A_SETTING" in str(exc)
    else:
        raise AssertionError("expected KeyError for an undeclared key")


def test_catalog_has_no_duplicate_keys():
    names = [k.name for k in KEYS]
    assert len(names) == len(set(names))
