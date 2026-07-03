from open_refinery import connect, create_user, import_or_get, list_repositories


def test_import_is_idempotent():
    conn = connect("sqlite:///:memory:")
    ian, _ = create_user(conn, "ian@x.dev", "pw", "developer")
    a = import_or_get(conn, "web", "git@x:acme/web.git", ian.id)
    b = import_or_get(conn, "web", "git@x:acme/web.git", ian.id)  # same URL again
    assert a == b  # returns the existing repo, no duplicate, no error
    assert len(list_repositories(conn)) == 1
