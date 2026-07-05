"""Live updates — an in-process pub/sub hub for the WebSocket channel.

Producers (the job runner, the audit sink) call `HUB.publish(event)` from any
thread; the hub fans each event out to every connected WebSocket via the server's
event loop (`call_soon_threadsafe`, so cross-thread publishing is safe). The
`/ws` endpoint subscribes a queue and streams events to the browser.

In-process only — same ethos as the job runner/scheduler. With no loop bound
(e.g. under tests, or before startup), `publish` is a no-op.
"""

from __future__ import annotations

import asyncio


class Hub:
    def __init__(self) -> None:
        self._queues: set[asyncio.Queue] = set()
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._queues.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._queues.discard(q)

    def publish(self, event: dict) -> None:
        """Fan an event out to all subscribers. Safe to call from any thread."""
        loop = self._loop
        if loop is None:
            return
        for q in list(self._queues):
            loop.call_soon_threadsafe(self._offer, q, event)

    @staticmethod
    def _offer(q: asyncio.Queue, event: dict) -> None:
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:  # a slow client shouldn't block the rest
            pass


HUB = Hub()
