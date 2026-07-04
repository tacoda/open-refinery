import hashlib
import hmac
import json

import pytest

from open_refinery import (
    connect,
    create_webhook,
    delete_webhook,
    deliver,
    list_webhooks,
    sign,
)
from open_refinery.provenance import Record


@pytest.fixture(autouse=True)
def _secret(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "test-secret")


def setup():
    conn = connect("sqlite:///:memory:")
    from open_refinery import create_user
    plat, _ = create_user(conn, "plat@x.dev", "pw", "platform")
    return conn, plat


def rec(recipe="transition"):
    return Record.of(recipe=recipe, actor="a", owner="a", inputs={"x": 1}, output="ok", subject="w1")


def capturing_sender():
    calls = []

    def send(url, body, headers):
        calls.append({"url": url, "body": body, "headers": headers})
        return 200
    return calls, send


def test_signature_verifies():
    body = b'{"a":1}'
    sig = sign("s3cret", body)
    expected = "sha256=" + hmac.new(b"s3cret", body, hashlib.sha256).hexdigest()
    assert sig == expected


def test_deliver_signs_and_posts():
    conn, plat = setup()
    wh, secret = create_webhook(conn, "https://hook.example/x", [], plat.id)
    calls, send = capturing_sender()

    n = deliver(conn, rec(), sender=send)
    assert n == 1 and len(calls) == 1
    c = calls[0]
    assert c["url"] == "https://hook.example/x"
    assert c["headers"]["X-OpenRefinery-Signature"] == sign(secret, c["body"])
    payload = json.loads(c["body"])
    assert payload["recipe"] == "transition" and payload["subject"] == "w1"
    assert list_webhooks(conn)[0].last_status == 200  # recorded


def test_event_filter():
    conn, plat = setup()
    create_webhook(conn, "https://hook/only-approvals", ["approval"], plat.id)
    calls, send = capturing_sender()

    assert deliver(conn, rec("transition"), sender=send) == 0   # filtered out
    assert deliver(conn, rec("approval"), sender=send) == 1      # matches


def test_delivery_failure_is_swallowed():
    conn, plat = setup()
    create_webhook(conn, "https://hook/bad", [], plat.id)

    def boom(url, body, headers):
        raise RuntimeError("connection refused")

    assert deliver(conn, rec(), sender=boom) == 1        # attempted, no raise
    assert list_webhooks(conn)[0].last_status == 0        # failure recorded


def test_delete_webhook():
    conn, plat = setup()
    wh, _ = create_webhook(conn, "https://hook/x", [], plat.id)
    delete_webhook(conn, wh.id)
    assert list_webhooks(conn) == []
