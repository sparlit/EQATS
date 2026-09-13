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


import asyncio
import os
import sys

from aiohttp import web

root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.append(root)

import contextlib

import ccxt.async_support as ccxt

# ----------------------------------------------------------------------------
# hand-written python-only test (not transpiled) - regression test for
# https://github.com/ccxt/ccxt/issues/27418
#
# When several requests are launched with asyncio.gather() and one sibling
# raises, asyncio.gather does NOT cancel the remaining siblings. Those orphans
# keep running after the user has awaited exchange.close(). As soon as an
# orphan reaches the lazy session creation in Exchange.open(), it silently
# builds a brand new aiohttp ClientSession + TCPConnector that nobody will ever
# close, which leaks the socket and emits "Unclosed client session" warnings.
# ----------------------------------------------------------------------------

RATE_LIMIT_MS = 250
ORPHAN_GRACE_S = 0.75


class SessionLeakExchange(ccxt.Exchange):
    def describe(self):
        return self.deep_extend(
            super().describe(),
            {
                "id": "sessionleaktest",
                "name": "Session Leak Test",
                "rateLimit": RATE_LIMIT_MS,
                "rateLimiterAlgorithm": "leakyBucket",
            },
        )

    def sign(self, path, api="public", method="GET", params=None, headers=None, body=None):
        if params is None:
            params = {}
        return {
            "url": self.urls["api"][api] + "/" + path,
            "method": method,
            "body": body,
            "headers": headers,
        }


async def session_leak_ok_handler(request):
    return web.json_response({"ok": True})


async def session_leak_slow_handler(request):
    await asyncio.sleep(5)
    return web.json_response({"ok": True})


async def start_session_leak_server():
    app = web.Application()
    app.router.add_get("/ok", session_leak_ok_handler)
    app.router.add_get("/slow", session_leak_slow_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = runner.addresses[0][1]
    return runner, "http://127.0.0.1:" + str(port)


def build_session_leak_exchange(base_url, enable_rate_limit):
    return SessionLeakExchange(
        {
            "enableRateLimit": enable_rate_limit,
            "timeout": 30000,
            "urls": {"api": {"public": base_url}},
        }
    )


async def session_leak_failing_sibling(delay):
    await asyncio.sleep(delay)
    msg = "sibling request failed"
    raise ValueError(msg)


async def drain_session_leak_tasks(tasks):
    # retrieve every result/exception so no orphan shows up later as an
    # "Task exception was never retrieved" warning polluting the test output
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


async def test_close_session_leak_queued_orphans():
    # An orphan still queued inside the throttler wakes up after close() and
    # reaches the lazy session creation in open().
    runner, base_url = await start_session_leak_server()
    exchange = build_session_leak_exchange(base_url, True)
    tasks = []
    try:
        for _i in range(6):
            tasks.append(asyncio.ensure_future(exchange.request("ok", "public", "GET")))
        tasks.append(asyncio.ensure_future(session_leak_failing_sibling(0.02)))
        with contextlib.suppress(ValueError):
            await asyncio.gather(*tasks)
        await exchange.close()
        await asyncio.sleep(ORPHAN_GRACE_S)
        assert exchange.session is None, "an orphaned request recreated the aiohttp session after close()"
        assert exchange.tcp_connector is None, "an orphaned request recreated the aiohttp tcp_connector after close()"
    finally:
        await drain_session_leak_tasks(tasks)
        await exchange.close()
        await runner.cleanup()


async def test_close_session_leak_unstarted_orphan():
    # The racy variant: close() is awaited before the orphan ever reached its
    # first await, so the orphan opens the session from inside close() itself.
    runner, base_url = await start_session_leak_server()
    exchange = build_session_leak_exchange(base_url, False)
    tasks = []
    try:
        tasks.append(asyncio.ensure_future(exchange.request("slow", "public", "GET")))
        await exchange.close()
        await asyncio.sleep(ORPHAN_GRACE_S)
        assert exchange.session is None, "an orphaned request recreated the aiohttp session after close()"
        assert exchange.tcp_connector is None, "an orphaned request recreated the aiohttp tcp_connector after close()"
    finally:
        await drain_session_leak_tasks(tasks)
        await exchange.close()
        await runner.cleanup()


async def test_close_session_leak():
    await test_close_session_leak_queued_orphans()
    await test_close_session_leak_unstarted_orphan()
    print("close() session leak tests passed")
