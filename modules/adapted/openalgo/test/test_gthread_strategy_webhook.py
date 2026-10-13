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


"""The strategy webhook's cooling-off window under truly parallel threads.

``note_run_stopped`` writes the window from whichever thread stopped the run,
and the webhook reads it to refuse a start that arrives too soon after. The
read used to happen after ``_cache_lock`` was released, on a cachetools
``TTLCache``, which is not safe to read while another thread mutates it. Under
eventlet nothing yielded in between; under the gthread worker a refusal could
answer 500 instead of 409.
"""

import inspect
import sys
import threading

# restx_api first: see the note in test_strategy_module_order_dispatch.py.
import restx_api  # noqa: F401
from cachetools import TTLCache
from services.strategy_module import webhook


def test_the_refusal_reads_the_window_under_the_lock():
    """Source check: the handler never reads the window after releasing it."""
    source = inspect.getsource(webhook._handle)
    assert "_cooling_off_remaining(" not in source
    assert "_cooling_off_remaining_locked(" in source


def test_the_window_can_be_read_while_other_threads_write_it(monkeypatch):
    """Writers and readers on a tiny, constantly expiring window."""
    monkeypatch.setattr(
        webhook, "_cooling_off", TTLCache(maxsize=4, ttl=0.0005, timer=webhook._now)
    )
    errors = []
    start = threading.Barrier(8)

    def writer():
        try:
            start.wait()
            for i in range(3000):
                webhook.note_run_stopped(i % 16)
        except Exception as exc:  # noqa: BLE001 - reported below
            errors.append(repr(exc))

    def reader():
        try:
            start.wait()
            for i in range(3000):
                remaining = webhook._cooling_off_remaining(i % 16)
                assert remaining >= 0
        except Exception as exc:  # noqa: BLE001 - reported below
            errors.append(repr(exc))

    previous = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    try:
        threads = [threading.Thread(target=writer) for _ in range(4)]
        threads += [threading.Thread(target=reader) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(60)
    finally:
        sys.setswitchinterval(previous)

    assert errors == []


def test_a_fresh_window_still_reports_its_seconds(monkeypatch):
    monkeypatch.setattr(webhook, "_cooling_off", webhook._new_cooling_off_cache())
    webhook.note_run_stopped(41)

    remaining = webhook._cooling_off_remaining(41)

    assert 1 <= remaining <= webhook.COOLING_OFF_SECONDS
    assert webhook._cooling_off_remaining(42) == 0
