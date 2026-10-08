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
Tests for exit-reason classification.

A position can leave the book for four different reasons, and the bot only ever
observes one thing directly: the broker is now flat. Before 2026-08-12 it
guessed "manual close" every time and recorded no PnL at all, even when it had
watched its own stop order fill seconds earlier.

The scenario in `test_filled_stop_is_classified_as_sl_hit` is taken verbatim
from the 2026-08-12 session log:

    [ADOPT] Emergency SL placed: sl_id=26081200125796 | stop=₹326.40
    💹 TRADE | BUY 10 NSE:TARSONS-EQ @ ₹327.2 | order=26081200125796
    Order 26081200125796: FILLED ✅ | price=₹327.20

That was reported as "MANUAL CLOSE DETECTED — PnL for this trade not tracked".
"""

import types

import pytest
from freezegun import freeze_time
from shortcircuit.broker.fyers_broker_interface import FyersOrderStatus
from shortcircuit.state.reconciliation import ReconciliationEngine

IN_SESSION = "2026-08-12 05:32:21"  # 11:02 IST, well before the 15:10 deadline
AFTER_EOD = "2026-08-12 09:45:00"  # 15:15 IST


class StubBroker:
    def __init__(self, ltp=0.0, avg_price=0.0, sl_status=None):
        self.order_status_cache = {}
        self._avg = avg_price
        self._ltp = ltp
        if sl_status is not None:
            self.order_status_cache["26081200125796"] = types.SimpleNamespace(status=int(sl_status))

    async def get_order_avg_price(self, order_id):
        return self._avg

    async def get_ltp(self, symbol):
        return self._ltp


def make_engine(broker, sl_id="26081200125796"):
    """`_classify_exit` only touches broker + order_manager.hard_stops."""
    return types.SimpleNamespace(
        broker=broker,
        order_manager=types.SimpleNamespace(hard_stops={"NSE:TARSONS-EQ": sl_id} if sl_id else {}),
        EXIT_LABELS=ReconciliationEngine.EXIT_LABELS,
    )


def classify(engine, pos, symbol="NSE:TARSONS-EQ"):
    import asyncio

    return asyncio.run(ReconciliationEngine._classify_exit(engine, symbol, pos))


SHORT_POS = {"entry_price": 323.15, "qty": 10, "side": "SHORT"}


# the regression this exists for


@freeze_time(IN_SESSION)
def test_filled_stop_is_classified_as_sl_hit():
    """The exact TARSONS case: the stop filled and the bot knew it."""
    engine = make_engine(StubBroker(avg_price=327.20, sl_status=FyersOrderStatus.FILLED))
    reason, exit_px, pnl = classify(engine, SHORT_POS)

    assert reason == "SL_HIT", "a filled stop order is not a manual exit"
    assert exit_px == pytest.approx(327.20), "exit must come from the stop's fill, not LTP"
    assert pnl == pytest.approx((323.15 - 327.20) * 10), "short PnL is entry minus exit"
    assert pnl < 0


@freeze_time(IN_SESSION)
def test_pnl_is_always_computed_when_prices_are_known():
    """'PnL not tracked' is not an acceptable outcome when the inputs exist."""
    engine = make_engine(StubBroker(avg_price=327.20, sl_status=FyersOrderStatus.FILLED))
    _, _, pnl = classify(engine, SHORT_POS)
    assert pnl != 0.0


# the other three reasons


@freeze_time(AFTER_EOD)
def test_vanishing_after_the_deadline_is_the_square_off():
    engine = make_engine(StubBroker(ltp=320.0), sl_id=None)
    reason, _, _ = classify(engine, SHORT_POS)
    assert reason == "EOD_SQUAREOFF"


@freeze_time(IN_SESSION)
def test_favourable_operator_close_is_a_taken_profit():
    """Short closed below entry: the operator took profit."""
    engine = make_engine(StubBroker(ltp=318.00), sl_id=None)
    reason, exit_px, pnl = classify(engine, SHORT_POS)
    assert reason == "MANUAL_TP_EXIT"
    assert pnl > 0 and exit_px == pytest.approx(318.00)


@freeze_time(IN_SESSION)
def test_adverse_operator_close_is_a_plain_manual_exit():
    engine = make_engine(StubBroker(ltp=326.00), sl_id=None)
    reason, _, pnl = classify(engine, SHORT_POS)
    assert reason == "MANUAL_EXIT"
    assert pnl < 0


@freeze_time(IN_SESSION)
def test_long_pnl_uses_the_opposite_sign():
    engine = make_engine(StubBroker(ltp=330.0), sl_id=None)
    reason, _, pnl = classify(engine, {"entry_price": 323.15, "qty": 10, "side": "LONG"})
    assert pnl == pytest.approx((330.0 - 323.15) * 10)
    assert reason == "MANUAL_TP_EXIT"


# precedence and degradation


@freeze_time(AFTER_EOD)
def test_a_filled_stop_outranks_the_eod_window():
    """
    A stop can fill at 15:12 while the square-off is also running. The stop is
    what actually closed it, so it wins.
    """
    engine = make_engine(StubBroker(avg_price=327.20, sl_status=FyersOrderStatus.FILLED))
    reason, _, _ = classify(engine, SHORT_POS)
    assert reason == "SL_HIT"


@freeze_time(IN_SESSION)
def test_an_unfilled_stop_does_not_claim_the_exit():
    """A stop sitting in PENDING did not close anything."""
    engine = make_engine(StubBroker(ltp=318.0, avg_price=0.0, sl_status=FyersOrderStatus.PENDING))
    reason, exit_px, _ = classify(engine, SHORT_POS)
    assert reason == "MANUAL_TP_EXIT"
    assert exit_px == pytest.approx(318.0)


@freeze_time(IN_SESSION)
def test_unknown_entry_price_degrades_without_raising():
    """Adopted positions can lack an entry price; classification must still work."""
    engine = make_engine(StubBroker(ltp=318.0), sl_id=None)
    reason, exit_px, pnl = classify(engine, {"entry_price": 0.0, "qty": 10, "side": "SHORT"})
    assert reason in ReconciliationEngine.EXIT_LABELS
    assert pnl == 0.0 and exit_px == pytest.approx(318.0)


@freeze_time(IN_SESSION)
def test_a_broker_that_raises_does_not_break_classification():
    class Boom:
        order_status_cache = {"26081200125796": types.SimpleNamespace(status=2)}

        async def get_order_avg_price(self, order_id):
            raise ConnectionError("broker down")

        async def get_ltp(self, symbol):
            raise ConnectionError("broker down")

    reason, exit_px, pnl = classify(make_engine(Boom()), SHORT_POS)
    assert reason in ReconciliationEngine.EXIT_LABELS
    assert exit_px == 0.0 and pnl == 0.0


def test_every_reason_has_an_operator_facing_label():
    for reason in ("SL_HIT", "EOD_SQUAREOFF", "MANUAL_TP_EXIT", "MANUAL_EXIT"):
        assert reason in ReconciliationEngine.EXIT_LABELS
        assert ReconciliationEngine.EXIT_LABELS[reason].strip()
