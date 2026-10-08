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


"""The shared httpx client is built once, and only gthread bounds its pool wait.

Two cold threads used to be able to build a client each, the loser's
connection pool discarded without being closed. And the 120 s timeout also
governed waiting for a free pooled connection, so under the gthread worker a
saturated pool showed up as a two-minute hang on one of a fixed number of
threads. The pool wait is bounded there only; under eventlet and the dev
server the client is configured exactly as before.
"""


import threading
import time

import httpx
import pytest
import utils.httpx_client as hc

from utils import runtime


@pytest.fixture
def fresh_client(monkeypatch):
    monkeypatch.setattr(hc, "_client", hc.LazyInit(hc._build_client, name="httpx-test"))
    yield hc
    hc.cleanup_httpx_client()


def test_simultaneous_first_callers_share_one_client(fresh_client, monkeypatch):
    built = []
    real = hc._create_http_client

    def slow_create():
        built.append(1)
        time.sleep(0.05)
        return real()

    monkeypatch.setattr(hc, "_create_http_client", slow_create)
    barrier = threading.Barrier(16)
    clients = []

    def caller():
        barrier.wait()
        clients.append(hc.get_httpx_client())

    threads = [threading.Thread(target=caller) for _ in range(16)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)

    assert len(built) == 1
    assert len({id(c) for c in clients}) == 1


def test_cleanup_closes_and_the_next_call_builds_a_new_client(fresh_client):
    first = hc.get_httpx_client()
    hc.cleanup_httpx_client()
    assert first.is_closed
    second = hc.get_httpx_client()
    assert second is not first and not second.is_closed


def test_eventlet_and_the_dev_server_keep_the_single_timeout(fresh_client, monkeypatch):
    monkeypatch.setattr(runtime, "gthread_active", lambda: False)
    client = hc.get_httpx_client()
    assert client.timeout == httpx.Timeout(120.0)


def test_gthread_bounds_only_the_pool_wait(fresh_client, monkeypatch):
    monkeypatch.setattr(runtime, "gthread_active", lambda: True)
    client = hc.get_httpx_client()
    assert client.timeout.pool == hc.GTHREAD_POOL_TIMEOUT_SECONDS
    assert client.timeout.read == 120.0
    assert client.timeout.connect == 120.0


def test_pool_stats_are_best_effort(fresh_client):
    assert hc.get_pool_stats() is None
    hc.get_httpx_client()
    stats = hc.get_pool_stats()
    assert stats["max_connections"] == 100
