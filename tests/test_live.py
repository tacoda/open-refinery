import asyncio

import pytest
from fastapi.testclient import TestClient

from open_refinery import connect, create_user
from open_refinery.live import HUB
from open_refinery.users import create_session
from open_refinery.web import create_app


def test_hub_publish_fans_out_to_subscribers():
    async def go():
        HUB.bind_loop(asyncio.get_running_loop())
        q = HUB.subscribe()
        try:
            HUB.publish({"type": "job", "status": "done"})
            got = await asyncio.wait_for(q.get(), timeout=1)
            assert got == {"type": "job", "status": "done"}
        finally:
            HUB.unsubscribe(q)
    asyncio.run(go())


def test_hub_publish_noop_without_loop():
    HUB._loop = None
    HUB.publish({"x": 1})  # must not raise


@pytest.fixture
def ctx():
    conn = connect("sqlite:///:memory:", check_same_thread=False)
    user, _ = create_user(conn, "dev@x.dev", "pw", "developer")
    client = TestClient(create_app(conn))
    return conn, client, user


def test_ws_rejects_missing_token(ctx):
    _, client, _ = ctx
    with pytest.raises(Exception):  # server closes with 1008 before accept
        with client.websocket_connect("/ws"):
            pass


def test_ws_accepts_valid_token(ctx):
    conn, client, user = ctx
    sess = create_session(conn, user.id)
    with client.websocket_connect(f"/ws?token={sess}"):
        pass  # connects + accepts without error (streaming covered by the hub test)
