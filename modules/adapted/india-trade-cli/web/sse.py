from __future__ import annotations

import datetime

import pytz


def is_ist_market_session_active(dt: datetime.datetime | None = None) -> bool:
    """Checks whether current or provided time falls within NSE/BSE IST market session (09:15 to 15:30 IST Mon-Fri)."""
    ist = pytz.timezone("Asia/Kolkata")
    now = dt.astimezone(ist) if dt else datetime.datetime.now(ist)
    if now.weekday() >= 5:
        return False
    market_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
    market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return market_open <= now <= market_close


def round_to_ist_tick(price: float, tick_size: float = 0.05) -> float:
    """Rounds price to nearest NSE/BSE valid price tick (default 0.05 INR)."""
    if price <= 0:
        return 0.0
    return round(round(price / tick_size) * tick_size, 2)


"""
web/sse.py
──────────
Server-Sent Events bus for real-time price and alert streaming.

Usage:
    from web.sse import event_bus

    event_bus.publish("price", {"symbol": "NIFTY", "ltp": 24500.0})
    event_bus.publish("alert", {"symbol": "INFY", "message": "RSI > 70"})

    # In FastAPI endpoint:
    async for chunk in event_bus.subscribe("price"):
        yield chunk
"""


import asyncio
import contextlib
import json
from collections import defaultdict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator


class SSEEventBus:
    """
    Simple pub/sub bus for SSE streams.

    Each channel (e.g. "price", "alert") has a list of subscriber queues.
    Publishers push events; subscribers receive them via async generators.

    Max queue size: 100 events per subscriber (oldest dropped if full).
    Heartbeat: sends ": heartbeat\\n\\n" every 15s to keep connections alive.
    """

    HEARTBEAT_INTERVAL = 15  # seconds
    MAX_QUEUE_SIZE = 100

    def __init__(self) -> None:
        self._channels: dict[str, list[asyncio.Queue]] = defaultdict(list)
        self._lock: asyncio.Lock | None = None

    def _get_lock(self) -> asyncio.Lock:
        """Lazily create lock so it's always on the running event loop."""
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    async def publish(self, channel: str, data: dict) -> int:
        """Publish to all subscribers on channel. Returns subscriber count."""
        async with self._get_lock():
            queues = list(self._channels[channel])

        count = 0
        for q in queues:
            try:
                q.put_nowait(data)
                count += 1
            except asyncio.QueueFull:
                # Drop oldest event to make room
                try:
                    q.get_nowait()
                    q.put_nowait(data)
                    count += 1
                except Exception:
                    pass
        return count

    async def subscribe(self, channel: str) -> AsyncGenerator[str]:
        """Yield SSE-formatted strings: 'data: {...}\\n\\n'"""
        q: asyncio.Queue = asyncio.Queue(maxsize=self.MAX_QUEUE_SIZE)

        async with self._get_lock():
            self._channels[channel].append(q)

        try:
            while True:
                try:
                    # Wait for next event with heartbeat timeout
                    data = await asyncio.wait_for(q.get(), timeout=self.HEARTBEAT_INTERVAL)
                    yield f"data: {json.dumps(data)}\n\n"
                except TimeoutError:
                    # Send heartbeat to keep connection alive
                    yield ": heartbeat\n\n"
        finally:
            async with self._get_lock():
                with contextlib.suppress(ValueError):
                    self._channels[channel].remove(q)

    def publish_sync(self, channel: str, data: dict) -> None:
        """Thread-safe publish from sync code (e.g. polling threads)."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.run_coroutine_threadsafe(self.publish(channel, data), loop)
            else:
                loop.run_until_complete(self.publish(channel, data))
        except RuntimeError:
            # No event loop available — best-effort: push directly to queues
            for q in self._channels.get(channel, []):
                with contextlib.suppress(asyncio.QueueFull, Exception):
                    q.put_nowait(data)


event_bus = SSEEventBus()  # module-level singleton
