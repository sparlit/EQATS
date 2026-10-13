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
A position closed by the 15:10 square-off is booked exactly once.

`close_all_positions` squared off and recorded the outcome itself, but never told
the order manager the position was gone. Three seconds later the reconciler saw
"flat at broker, open in the registry", logged a CRITICAL "POSITION VANISHED",
and ran the full close path, which recorded the outcome again and wrote the DB
exit as MANUAL_CLOSE_DETECTED. On 23 Sep NSE:JAYKAY-EQ made ₹35.50 and session
PnL read ₹71.45.

It hardly mattered while trades rarely lived to 15:10. EOD_HOLD sends every
surviving top-coil trade there, so it now happens on every winning day.
"""

import ast
import pathlib

import pytest
from shortcircuit.execution import trade_manager as tm_mod
from shortcircuit.execution.trade_manager import TradeManager

SRC = pathlib.Path(__file__).resolve().parents[2] / "src" / "shortcircuit"


class _Fyers:
    """Just enough of fyersModel for a square-off of one short."""

    def __init__(self, symbol="NSE:JAYKAY-EQ"):
        self.orders = []
        self._pos = {
            "symbol": symbol,
            "netQty": -9,
            "productType": "INTRADAY",
            "realized_profit": 0.0,
            "unrealized_profit": 35.95,
        }

    def positions(self):
        return {"netPositions": [self._pos]}

    def orderbook(self):
        return {"orderBook": []}

    def place_order(self, data):
        self.orders.append(data)
        return {"s": "ok", "id": "X1"}


class _OrderManager:
    def __init__(self, tracked):
        self.active_positions = {s: {"status": "OPEN"} for s in tracked}


@pytest.fixture
def tm(monkeypatch):
    monkeypatch.setattr(tm_mod.rest_limiter, "acquire", lambda *a, **k: None)
    t = TradeManager(_Fyers(), capital_manager=None)
    t.booked = []
    monkeypatch.setattr(t, "record_trade_outcome", lambda sym, pnl: t.booked.append((sym, pnl)))
    return t


def test_a_tracked_position_is_left_to_its_close_path(tm):
    tm.order_manager = _OrderManager(["NSE:JAYKAY-EQ"])
    tm.close_all_positions()
    assert tm.fyers.orders, "the square-off order must still be sent"
    assert tm.booked == [], (
        "the close path books this one; booking it here as well is the double count"
    )


def test_an_untracked_position_is_still_booked_here(tm):
    """A position the bot is not tracking has no close path to book it, so the
    square-off remains the only place its outcome can be recorded."""
    tm.order_manager = _OrderManager([])
    tm.close_all_positions()
    assert tm.booked == [("NSE:JAYKAY-EQ", pytest.approx(35.95))]


def test_without_an_order_manager_the_old_behaviour_holds(tm):
    tm.order_manager = None
    tm.close_all_positions()
    assert len(tm.booked) == 1


def test_the_supervisor_wires_the_order_manager_into_the_trade_manager():
    """The last missing wire of this kind (reconciliation_engine) stayed None for
    weeks because every call site tolerated it. This one is checked."""
    tree = ast.parse((SRC / "runtime" / "supervisor.py").read_text())
    wired = any(
        isinstance(n, ast.Assign)
        and any(
            isinstance(t, ast.Attribute)
            and t.attr == "order_manager"
            and isinstance(t.value, ast.Name)
            and t.value.id == "trade_manager"
            for t in n.targets
        )
        for n in ast.walk(tree)
    )
    assert wired


def test_a_close_after_the_square_off_is_not_labelled_manual():
    """Flat-at-broker after 15:10 is the scheduler's own doing: it must not raise a
    CRITICAL or be written to the DB as MANUAL_CLOSE_DETECTED."""
    src = (SRC / "state" / "reconciliation.py").read_text()
    assert "reason='EOD_SQUAREOFF' if _eod_close else 'MANUAL_CLOSE_DETECTED'" in src
    assert "if _eod_close:" in src
