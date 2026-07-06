import pytest

from open_refinery import (
    MemorySender,
    PolicyDenied,
    accept_invitation,
    authenticate,
    connect,
    create_invitation,
    create_user,
    invitation_email,
    list_invitations,
    revoke_invitation,
    set_sender,
)
from open_refinery import invitations as inv_mod


def setup():
    conn = connect("sqlite:///:memory:")
    admin, _ = create_user(conn, "admin@x.dev", "pw", "admin")
    platform, _ = create_user(conn, "plat@x.dev", "pw", "platform")
    dev, _ = create_user(conn, "dev@x.dev", "pw", "developer")
    return conn, admin, platform, dev


def test_role_gated_invites():
    conn, admin, platform, dev = setup()
    # you may invite your own level or lower, never higher
    inv, _ = create_invitation(conn, "new@x.dev", "developer", platform.id)
    assert inv.role == "developer" and inv.status == "pending"
    create_invitation(conn, "peer@x.dev", "platform", platform.id)   # equal level — allowed
    with pytest.raises(PolicyDenied):
        create_invitation(conn, "x@x.dev", "admin", platform.id)     # higher — denied
    create_invitation(conn, "p@x.dev", "platform", admin.id)         # admin → platform
    create_invitation(conn, "d@x.dev", "developer", dev.id)          # dev → dev (own level)


def test_accept_sets_password_and_registers():
    conn, admin, platform, dev = setup()
    inv, token = create_invitation(conn, "new@x.dev", "developer", admin.id)
    assert invitation_email(conn, token) == "new@x.dev"

    user, sess = accept_invitation(conn, token, "chosen-pw")
    assert user.email == "new@x.dev" and user.role == "developer"
    assert authenticate(conn, "new@x.dev", "chosen-pw") is not None  # password they set works
    assert sess  # a session token is returned


def test_token_single_use_and_revoke():
    conn, admin, *_ = setup()
    inv, token = create_invitation(conn, "a@x.dev", "developer", admin.id)
    accept_invitation(conn, token, "pw")
    with pytest.raises(ValueError):
        accept_invitation(conn, token, "pw2")  # already accepted

    inv2, tok2 = create_invitation(conn, "b@x.dev", "developer", admin.id)
    revoke_invitation(conn, inv2.id)
    with pytest.raises(ValueError):
        accept_invitation(conn, tok2, "pw")     # revoked
    assert invitation_email(conn, tok2) is None


def test_bad_token():
    conn, admin, *_ = setup()
    with pytest.raises(ValueError):
        accept_invitation(conn, "not-a-real-token", "pw")


def test_email_uses_the_configured_sender():
    mem = MemorySender()
    set_sender(mem)
    try:
        inv_mod.send_invitation_email("who@x.dev", "http://host/#invite=abc")
        assert mem.sent and mem.sent[0][0] == "who@x.dev" and "invite=abc" in mem.sent[0][2]
    finally:
        from open_refinery.email import LinuxMailSender
        set_sender(LinuxMailSender())  # restore default
