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


"""The health check does not fail a healthy gthread instance for its thread pool.

The thread thresholds (50 warn, 100 fail) were sized for eventlet, where the
work runs on green threads. Under gthread the request pool alone is 64
threads before a single browser connection, the event bus or a scheduler is
counted, so /health/status answered 503 and load balancers took a healthy
instance out. There the defaults now sit above the pool; explicit settings
win; under eventlet and the dev server nothing changes. The thread budget
(open streams and browser connections against the pool) is reported beside
it.
"""


import threading

import pytest
import utils.health_monitor as hm

from utils import runtime


@pytest.fixture
def parked_threads():
    release = threading.Event()
    threads = [threading.Thread(target=release.wait, args=(30,), daemon=True) for _ in range(120)]
    for thread in threads:
        thread.start()
    yield threads
    release.set()
    for thread in threads:
        thread.join(5)


@pytest.fixture
def no_alerts(monkeypatch):
    monkeypatch.setattr(hm.HealthAlert, "create_alert", staticmethod(lambda **kwargs: None))
    monkeypatch.setattr(
        hm.HealthAlert, "auto_resolve_alerts", staticmethod(lambda *args, **kwargs: None)
    )


def test_a_busy_gthread_instance_is_not_failed(parked_threads, no_alerts, monkeypatch):
    monkeypatch.delenv("HEALTH_THREAD_WARNING_THRESHOLD", raising=False)
    monkeypatch.delenv("HEALTH_THREAD_CRITICAL_THRESHOLD", raising=False)
    monkeypatch.setattr(runtime, "gthread_active", lambda: True)
    monkeypatch.setattr(runtime, "configured_threads", lambda: 64)

    metrics = hm.get_thread_metrics()

    # Before the fix: 120+ threads against a fixed 100 was "fail", a 503.
    assert metrics["status"] != "fail"
    assert metrics["budget"]["threads"] == 64
    assert hm._thread_thresholds() == (144, 224)


def test_an_unknown_gthread_pool_assumes_the_launchers_constant(monkeypatch):
    monkeypatch.delenv("HEALTH_THREAD_WARNING_THRESHOLD", raising=False)
    monkeypatch.delenv("HEALTH_THREAD_CRITICAL_THRESHOLD", raising=False)
    monkeypatch.setattr(runtime, "gthread_active", lambda: True)
    monkeypatch.setattr(runtime, "configured_threads", lambda: None)
    assert hm._thread_thresholds() == (144, 224)


def test_explicit_thresholds_still_win_under_gthread(monkeypatch):
    monkeypatch.setenv("HEALTH_THREAD_WARNING_THRESHOLD", "70")
    monkeypatch.setenv("HEALTH_THREAD_CRITICAL_THRESHOLD", "90")
    monkeypatch.setattr(hm, "THREAD_WARNING_THRESHOLD", 70)
    monkeypatch.setattr(hm, "THREAD_CRITICAL_THRESHOLD", 90)
    monkeypatch.setattr(runtime, "gthread_active", lambda: True)
    monkeypatch.setattr(runtime, "configured_threads", lambda: 64)
    assert hm._thread_thresholds() == (70, 90)


def test_eventlet_and_the_dev_server_are_unchanged(parked_threads, no_alerts, monkeypatch):
    monkeypatch.setattr(runtime, "gthread_active", lambda: False)
    assert hm._thread_thresholds() == (hm.THREAD_WARNING_THRESHOLD, hm.THREAD_CRITICAL_THRESHOLD)

    metrics = hm.get_thread_metrics()
    assert "budget" not in metrics
    if hm.THREAD_CRITICAL_THRESHOLD <= 120:
        assert metrics["status"] == "fail"
