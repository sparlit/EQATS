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


"""The stop must never be larger than the position it protects.

On 2026-09-01 NSE:ENGINERSIN-EQ was SHORT x10 behind a resting BUY x10 stop. TP-1
took 5, the breakeven move failed, and nothing else resized the stop. When it
triggered it bought 10 against a short of 5 and flipped the account LONG 5 —
reconciliation adopted that as a manual entry and the operator closed it by hand.

The defect was that the resize lived inside the breakeven feature, so an optional
feature failing broke a safety invariant. These tests pin the corrected behaviour.
"""

import pytest
from shortcircuit.execution import focus_engine as fe


class _Recorder:
    """Stands in for OrderManager, recording what the engine asked it to do."""

    def __init__(
        self, *, partial_ok=True, move_ok=True, resting_qty=None, move_raises=False, verify_qty=None
    ):
        self.partial_ok = partial_ok
        self.move_ok = move_ok
        self.move_raises = move_raises
        self.verify_qty = verify_qty
        self.move_calls: list[tuple] = []
        self.exits: list[str] = []
        self.partials: list[int] = []

    async def partial_exit(self, symbol, qty, reason):
        self.partials.append(qty)
        return self.partial_ok

    async def move_hard_stop(self, symbol, price, new_qty=None):
        self.move_calls.append((symbol, price, new_qty))
        if self.move_raises:
            raise RuntimeError("broker refused")
        return self.move_ok

    async def verify_stop_qty(self, symbol):
        return self.verify_qty

    async def safe_exit(self, symbol, reason):
        self.exits.append(reason)
        return True


class _Engine:
    """A FocusEngine with the real methods under test and nothing else."""

    _resize_stop_after_partial = fe.FocusEngine._resize_stop_after_partial
    _dispatch_alert = lambda self, msg: self.alerts.append(msg)  # noqa: E731

    def __init__(self, om):
        self.order_manager = om
        self.telegram_bot = None
        self.alerts: list[str] = []
        self.stopped: list[str] = []
        self._event_loop = None

    def stop_focus(self, reason="STOPPED"):
        self.stopped.append(reason)


@pytest.fixture
def trade():
    return {
        "symbol": "NSE:X-EQ",
        "entry": 100.0,
        "sl": 102.0,
        "tp_1": 99.0,
        "remaining_qty": 5,
        "be_moved": False,
    }


@pytest.fixture(autouse=True)
def _immediate(monkeypatch):
    """Run coroutines inline and skip the backoff sleeps."""
    import asyncio

    def run_now(coro, loop):
        class _F:
            def result(self, timeout=None):
                return asyncio.new_event_loop().run_until_complete(coro)

        return _F()

    monkeypatch.setattr(fe.asyncio, "run_coroutine_threadsafe", run_now)
    monkeypatch.setattr(fe.time, "sleep", lambda *_: None)


# ── the invariant ────────────────────────────────────────────────────────────


def test_stop_is_resized_to_the_remaining_quantity(trade, monkeypatch):
    monkeypatch.setattr(fe.config, "P52_BREAKEVEN_AFTER_TP1", True, raising=False)
    om = _Recorder(verify_qty=5)
    eng = _Engine(om)

    assert eng._resize_stop_after_partial("NSE:X-EQ", trade) is True
    assert om.move_calls == [("NSE:X-EQ", 100.0, 5)]  # breakeven price, halved qty


def test_resize_happens_even_when_breakeven_is_disabled(trade, monkeypatch):
    """The regression. Breakeven off must still shrink the stop — at its old price."""
    monkeypatch.setattr(fe.config, "P52_BREAKEVEN_AFTER_TP1", False, raising=False)
    om = _Recorder(verify_qty=5)
    eng = _Engine(om)

    assert eng._resize_stop_after_partial("NSE:X-EQ", trade) is True
    assert len(om.move_calls) == 1
    symbol, price, qty = om.move_calls[0]
    assert qty == 5, "quantity must be corrected regardless of the breakeven flag"
    assert price == 102.0, "with breakeven off the stop keeps its original price"
    assert trade["be_moved"] is False
    assert om.exits == []


def test_an_oversized_resting_stop_is_never_accepted(trade, monkeypatch):
    """s == 'ok' is not proof. If the book still shows 10 against 5, retry then flatten."""
    monkeypatch.setattr(fe.config, "P52_BREAKEVEN_AFTER_TP1", True, raising=False)
    om = _Recorder(move_ok=True, verify_qty=10)  # broker says ok, book disagrees
    eng = _Engine(om)

    assert eng._resize_stop_after_partial("NSE:X-EQ", trade) is False
    assert len(om.move_calls) == 3, "must exhaust its retries before giving up"
    assert om.exits == ["SL_RESIZE_FAILED"], "the remainder must be closed, not carried"
    assert eng.stopped == ["SL_RESIZE_FAILED"]


def test_remainder_is_flattened_when_the_resize_keeps_failing(trade, monkeypatch):
    monkeypatch.setattr(fe.config, "P52_BREAKEVEN_AFTER_TP1", True, raising=False)
    om = _Recorder(move_ok=False)
    eng = _Engine(om)

    assert eng._resize_stop_after_partial("NSE:X-EQ", trade) is False
    assert len(om.move_calls) == 3
    assert om.exits == ["SL_RESIZE_FAILED"]
    assert any("STOP RESIZE FAILED" in a for a in eng.alerts)


def test_a_raising_broker_is_retried_then_flattened(trade, monkeypatch):
    monkeypatch.setattr(fe.config, "P52_BREAKEVEN_AFTER_TP1", True, raising=False)
    om = _Recorder(move_raises=True)
    eng = _Engine(om)

    assert eng._resize_stop_after_partial("NSE:X-EQ", trade) is False
    assert om.exits == ["SL_RESIZE_FAILED"]


def test_unverifiable_book_still_counts_as_resized(trade, monkeypatch):
    """A missing verification is not evidence of failure — the modify already said ok.

    Flattening on an unreadable orderbook would close good trades every time the
    broker had a bad second.
    """
    monkeypatch.setattr(fe.config, "P52_BREAKEVEN_AFTER_TP1", True, raising=False)
    om = _Recorder(move_ok=True, verify_qty=None)
    eng = _Engine(om)

    assert eng._resize_stop_after_partial("NSE:X-EQ", trade) is True
    assert om.exits == []


def test_a_smaller_resting_stop_is_acceptable(trade, monkeypatch):
    """Smaller than the position is safe: it under-covers, it cannot flip the side."""
    monkeypatch.setattr(fe.config, "P52_BREAKEVEN_AFTER_TP1", True, raising=False)
    om = _Recorder(move_ok=True, verify_qty=3)
    eng = _Engine(om)

    assert eng._resize_stop_after_partial("NSE:X-EQ", trade) is True
    assert om.exits == []


def test_the_engineersin_scenario_cannot_recur(monkeypatch):
    """Short 10, take 5, breakeven rejected by the broker. The stop must not stay 10."""
    monkeypatch.setattr(fe.config, "P52_BREAKEVEN_AFTER_TP1", True, raising=False)
    t = {
        "symbol": "NSE:ENGINERSIN-EQ",
        "entry": 285.85,
        "sl": 287.90,
        "tp_1": 284.40,
        "remaining_qty": 5,
        "be_moved": False,
    }
    om = _Recorder(move_ok=False)  # exactly what happened on 1 Sep
    eng = _Engine(om)

    still_open = eng._resize_stop_after_partial("NSE:ENGINERSIN-EQ", t)

    assert still_open is False
    assert om.exits == ["SL_RESIZE_FAILED"], (
        "with the stop stuck at 10 against a short of 5, the only safe move is to "
        "close the remainder — carrying it is what flipped the account long"
    )
    assert all(qty == 5 for _, _, qty in om.move_calls)
