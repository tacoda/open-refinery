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


# --- runs on the canvas -----------------------------------------------------

def test_a_run_announces_every_stage_it_moves_to():
    """Live mode draws the same graph as design mode, so a run event carries
    stage names and nothing about layout — the browser already has the nodes."""
    from open_refinery.live import HUB
    from open_refinery.pipeline import store as ps
    from open_refinery.pipeline.graph import Move

    seen = []
    HUB.publish = lambda e: seen.append(e)  # no loop is bound under tests
    try:
        conn, run = _a_run()
        ps.apply_move(conn, run, Move(to="build", why="the prepare phase passed"))
    finally:
        del HUB.publish

    starts = [e for e in seen if e["type"] == "run"]
    assert starts, "starting a run should put it on the canvas"
    assert starts[-1]["from"] != starts[-1]["stage"], "a move names where it came from"
    assert starts[-1]["stage"] == "build"


def _a_run():
    from open_refinery import (connect, create_repository, create_user,
                               create_work_item)
    from open_refinery.pipeline import store as ps

    conn = connect("sqlite:///:memory:")
    dev, _ = create_user(conn, "dev@x.dev", "pw", "developer")
    repo = create_repository(conn, "or", "git@x:or.git", dev.id)
    item = create_work_item(conn, repo.id, "T", dev.id)
    pipeline = ps.ensure_default(conn, dev.id)
    return conn, ps.start_run(conn, item.id, pipeline, repo.id, dev.id, spec="do it")
