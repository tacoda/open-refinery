import pytest

from open_refinery import (
    DuplicateUser,
    authenticate,
    connect,
    create_user,
    rotate_token,
    user_by_token,
)


def db():
    return connect("sqlite:///:memory:")


def test_create_and_authenticate():
    conn = db()
    user, token = create_user(conn, "ian@tacoda.dev", "s3cret", "developer")
    assert user.role == "developer"
    assert token  # plaintext returned once
    assert authenticate(conn, "ian@tacoda.dev", "s3cret") == user


def test_authenticate_rejects_bad_password():
    conn = db()
    create_user(conn, "ian@tacoda.dev", "s3cret", "developer")
    assert authenticate(conn, "ian@tacoda.dev", "wrong") is None
    assert authenticate(conn, "nobody@tacoda.dev", "s3cret") is None


def test_token_resolves_to_user():
    conn = db()
    user, token = create_user(conn, "ian@tacoda.dev", "s3cret", "admin")
    assert user_by_token(conn, token) == user
    assert user_by_token(conn, "bogus") is None


def test_rotate_token_invalidates_old():
    conn = db()
    user, old = create_user(conn, "ian@tacoda.dev", "s3cret", "platform")
    new = rotate_token(conn, user.id)
    assert new != old
    assert user_by_token(conn, old) is None
    assert user_by_token(conn, new) == user


def test_duplicate_email_rejected():
    conn = db()
    create_user(conn, "ian@tacoda.dev", "s3cret", "developer")
    with pytest.raises(DuplicateUser):
        create_user(conn, "ian@tacoda.dev", "other", "developer")


def test_unknown_role_rejected():
    conn = db()
    with pytest.raises(ValueError):
        create_user(conn, "ian@tacoda.dev", "s3cret", "superuser")
