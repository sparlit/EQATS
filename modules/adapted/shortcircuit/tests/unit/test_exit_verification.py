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
An exit must never be finalised on a position nobody confirmed was closed.

On 7 and 9 Sep 2026 the same failure ran four times. `safe_exit` cancelled the
protective stop, asked the broker whether the position was still open, got a
rate-limited response, and read the resulting empty list as "already flat" — so
it never placed the cover order, reported `success=True`, released the capital
slot, and left a naked short behind. NSE:GRAPHITE-EQ, NSE:AEROENTER-EQ,
NSE:SMSPHARMA-EQ and NSE:PNGSREVA-EQ all reached the operator as
`Exit Price: ₹0.00`, and all four were closed by hand at a loss.

`get_all_positions` returning `[]` for both "verified flat" and "could not ask"
is the whole defect. These tests pin the distinction and the ordering that
depends on it: nothing protective is cancelled until the position's state is
known.
"""

import asyncio

import pytest
from shortcircuit.broker.fyers_broker_interface import PositionFetchError
from shortcircuit.execution.order_manager import OrderManager

# Captured before any test patches asyncio.sleep, so the patch can still yield.
_REAL_SLEEP = asyncio.sleep

RATE_LIMITED = {"s": "error", "code": 429, "message": "Bad request"}


class _Broker:
    """Records what the exit path asked of the broker."""

    def __init__(self, *, positions=None, raises=0):
        # `positions` is what a successful fetch returns; `raises` is how many
        # leading attempts fail before that.
        self._positions = positions if positions is not None else []
        self._raises = raises
        self.fetches = 0
        self.cancelled: list[str] = []
        self.orders: list[tuple] = []
        self.bot_order_ids: set[str] = set()

    async def get_all_positions(self, force_rest=False):
        self.fetches += 1
        if self.fetches <= self._raises:
            raise PositionFetchError(f"broker returned {RATE_LIMITED}")
        return list(self._positions)

    async def cancel_order(self, order_id):
        self.cancelled.append(str(order_id))
        return True

    async def place_order(self, symbol, side, qty, order_type="MARKET", **kw):
        self.orders.append((symbol, side, qty, order_type))
        return "EXIT-1"

    async def wait_for_fill(self, order_id, timeout=15.0):
        return True

    async def get_order_avg_price(self, order_id):
        return 100.0

    rest_client = None


class _Telegram:
    def __init__(self):
        self.alerts: list[str] = []

    async def send_alert(self, msg):
        self.alerts.append(msg)


def _manager(broker):
    om = OrderManager(broker=broker, telegram_bot=_Telegram())
    om.active_positions["NSE:X-EQ"] = {
        "symbol": "NSE:X-EQ",
        "qty": 5,
        "side": "SHORT",
        "status": "OPEN",
        "entry_id": "E1",
        "sl_id": "SL-1",
        "entry_price": 100.0,
        "stop_loss": 102.0,
    }
    om.hard_stops["NSE:X-EQ"] = "SL-1"
    return om


def _run(coro):
    return asyncio.run(coro)


# ── the broker must distinguish "flat" from "don't know" ─────────────────────


def test_an_empty_list_still_means_verified_flat():
    """The success path must keep returning [] — that is real evidence."""
    broker = _Broker(positions=[])
    assert _run(broker.get_all_positions()) == []


def test_a_rate_limited_fetch_raises_instead_of_reading_as_flat():
    broker = _Broker(raises=1)
    with pytest.raises(PositionFetchError):
        _run(broker.get_all_positions())


# ── verification retries, because the failure is transient ───────────────────


def test_verification_retries_a_transient_failure(monkeypatch):
    monkeypatch.setattr(asyncio, "sleep", lambda *_a, **_k: _REAL_SLEEP(0))
    broker = _Broker(positions=[{"symbol": "NSE:X-EQ", "qty": 5}], raises=2)
    om = _manager(broker)

    got = _run(om.verify_position_at_broker("NSE:X-EQ"))

    assert got == {"symbol": "NSE:X-EQ", "qty": 5}
    assert broker.fetches == 3, "must have retried rather than given up on the first 429"


def test_verification_gives_up_as_unknown_not_as_flat(monkeypatch):
    monkeypatch.setattr(asyncio, "sleep", lambda *_a, **_k: _REAL_SLEEP(0))
    broker = _Broker(raises=99)
    om = _manager(broker)

    with pytest.raises(PositionFetchError):
        _run(om.verify_position_at_broker("NSE:X-EQ"))


def test_a_confirmed_absence_is_reported_as_flat():
    broker = _Broker(positions=[{"symbol": "NSE:OTHER-EQ", "qty": 3}])
    om = _manager(broker)
    assert _run(om.verify_position_at_broker("NSE:X-EQ")) is None


# ── the exit path itself ─────────────────────────────────────────────────────


def test_the_stop_survives_an_unverifiable_position(monkeypatch):
    """The regression. Unknown must abort while the position is still covered."""
    monkeypatch.setattr(asyncio, "sleep", lambda *_a, **_k: _REAL_SLEEP(0))
    broker = _Broker(raises=99)
    om = _manager(broker)

    assert _run(om.safe_exit("NSE:X-EQ", "TP_HIT")) is False
    assert broker.cancelled == [], "the stop must NOT be cancelled on an unknown position"
    assert broker.orders == [], "and no exit order may be placed blind"
    assert om.active_positions["NSE:X-EQ"]["status"] == "OPEN", "position stays tracked"
    assert "NSE:X-EQ" in om.hard_stops, "the stop reference must survive for the retry"
    assert any("EXIT DEFERRED" in a for a in om.telegram.alerts)


def test_a_confirmed_open_position_is_actually_exited():
    broker = _Broker(positions=[{"symbol": "NSE:X-EQ", "qty": 5}])
    om = _manager(broker)

    assert _run(om.safe_exit("NSE:X-EQ", "TP_HIT")) is True
    assert ("NSE:X-EQ", "BUY", 5, "MARKET") in broker.orders
    assert "SL-1" in broker.cancelled


def test_the_exit_is_sized_from_the_broker_not_from_our_own_count():
    """After a partial our count can be stale, and an oversized exit reverses."""
    broker = _Broker(positions=[{"symbol": "NSE:X-EQ", "qty": 2}])
    om = _manager(broker)
    om.active_positions["NSE:X-EQ"]["qty"] = 5  # stale

    _run(om.safe_exit("NSE:X-EQ", "TP_HIT"))

    assert ("NSE:X-EQ", "BUY", 2, "MARKET") in broker.orders, (
        "exiting 5 against an open 2 does not close the position, it flips it long"
    )


def test_a_genuinely_flat_position_is_finalised_without_an_order():
    broker = _Broker(positions=[])
    om = _manager(broker)

    assert _run(om.safe_exit("NSE:X-EQ", "SL_HIT")) is True
    assert broker.orders == [], "nothing to close — placing an order here opens a reverse"


def test_the_graphite_scenario_cannot_recur(monkeypatch):
    """
    9 Sep 2026, 04:49 UTC: TP hit on a live SHORT ×2, every broker call 429ing.

    The old path cancelled the stop, read the 429 as flat, placed nothing, and
    returned success. The only acceptable outcome now is that it refuses to act.
    """
    monkeypatch.setattr(asyncio, "sleep", lambda *_a, **_k: _REAL_SLEEP(0))
    broker = _Broker(raises=99)
    om = _manager(broker)
    om.active_positions["NSE:X-EQ"].update(qty=2, entry_price=858.05)

    result = _run(om.safe_exit("NSE:X-EQ", "TP_HIT"))

    assert result is False, "success must not be reported for an exit that did not happen"
    assert broker.cancelled == []
    assert broker.orders == []
    assert "NSE:X-EQ" in om.active_positions, (
        "dropping it here is what released the capital slot and let the reconciler "
        "re-adopt a live position as a manual entry"
    )
