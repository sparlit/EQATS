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
A declined exit must keep the position under watch.

`safe_exit` can now refuse to act — it will not cancel a stop on a position the
broker would not confirm. The focus loop previously called `stop_focus()`
unconditionally after every exit attempt, so a refusal would have ended the watch
on a live position whose exit level had already been breached, leaving only the
broker stop until EOD. That is worse than the fail-open it replaces, so the
retire-or-retry decision is pinned here.

Retries are throttled because the loop runs at 5Hz and the failure being handled
is a rate limit: retrying 300 times a minute is how the budget was exhausted in
the first place.
"""

import pytest
from shortcircuit.execution import focus_engine as fe


class _Engine:
    """A FocusEngine with only the method under test and the state it touches."""

    _retire_or_retry = fe.FocusEngine._retire_or_retry

    def __init__(self):
        self._exit_retry_at: dict[str, float] = {}
        self._exit_retry_count: dict[str, int] = {}
        self.stopped: list[str] = []
        self.alerts: list[str] = []

    def stop_focus(self, reason="STOPPED"):
        self.stopped.append(reason)

    def _dispatch_alert(self, message):
        self.alerts.append(message)


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(fe.time, "sleep", lambda *_: None)


@pytest.fixture
def clock(monkeypatch):
    now = {"t": 1000.0}
    monkeypatch.setattr(fe.time, "time", lambda: now["t"])
    return now


def test_a_completed_exit_ends_the_watch(clock):
    eng = _Engine()

    assert eng._retire_or_retry("NSE:X-EQ", True, "TP_HIT") is True
    assert eng.stopped == ["TP_HIT"]


def test_a_declined_exit_keeps_the_watch_alive(clock):
    """The regression. Stopping here strands a live position."""
    eng = _Engine()

    assert eng._retire_or_retry("NSE:X-EQ", False, "TP_HIT") is False
    assert eng.stopped == [], "the loop must keep running so it can retry"


def test_retries_are_throttled(clock):
    """At 5Hz an unthrottled retry is 300 attempts a minute against a 429."""
    eng = _Engine()

    eng._retire_or_retry("NSE:X-EQ", False, "TP_HIT")
    for _ in range(20):
        clock["t"] += 0.2
        eng._retire_or_retry("NSE:X-EQ", False, "TP_HIT")

    assert eng._exit_retry_count["NSE:X-EQ"] == 1, (
        "four seconds of ticks must not count as 21 attempts"
    )


def test_a_retry_happens_once_the_backoff_elapses(clock):
    eng = _Engine()

    eng._retire_or_retry("NSE:X-EQ", False, "TP_HIT")
    clock["t"] += 11.0
    eng._retire_or_retry("NSE:X-EQ", False, "TP_HIT")

    assert eng._exit_retry_count["NSE:X-EQ"] == 2


def test_the_operator_is_told_when_it_keeps_failing(clock):
    eng = _Engine()

    for _ in range(3):
        eng._retire_or_retry("NSE:X-EQ", False, "TP_HIT")
        clock["t"] += 11.0

    assert len(eng.alerts) == 1
    assert "EXIT STILL PENDING" in eng.alerts[0]


def test_the_alert_does_not_repeat_every_attempt(clock):
    eng = _Engine()

    for _ in range(10):
        eng._retire_or_retry("NSE:X-EQ", False, "TP_HIT")
        clock["t"] += 11.0

    assert len(eng.alerts) == 1, "one warning, not one per retry"


def test_a_later_success_still_ends_the_watch(clock):
    eng = _Engine()

    eng._retire_or_retry("NSE:X-EQ", False, "TP_HIT")
    clock["t"] += 11.0
    assert eng._retire_or_retry("NSE:X-EQ", True, "TP_HIT") is True
    assert eng.stopped == ["TP_HIT"]


def test_stop_focus_clears_the_retry_state():
    """Otherwise the next trade on the same symbol inherits a stale backoff."""
    eng = fe.FocusEngine.__new__(fe.FocusEngine)
    eng._exit_retry_at = {"NSE:X-EQ": 1.0}
    eng._exit_retry_count = {"NSE:X-EQ": 3}
    eng.active_trade = {"symbol": "NSE:X-EQ"}
    eng.is_running = True

    fe.FocusEngine.stop_focus(eng, "TP_HIT")

    assert eng._exit_retry_at == {}
    assert eng._exit_retry_count == {}
