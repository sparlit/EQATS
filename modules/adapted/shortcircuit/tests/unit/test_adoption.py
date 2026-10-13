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
Adopting a manually-entered position.

The operator enters a trade in Fyers while the bot is running. The bot should
protect it once, then get out of the way: if the operator moves the stop,
replaces it, or runs their own, the bot must not fight them for it.

Three defects from the 17–25 Aug sessions are pinned here.
"""

import pytest
from shortcircuit.state.reconciliation import (
    _LEARNED_TICKS,
    learn_tick_from_error,
    round_stop_away_from_entry,
)

# The exact rejection NSE:TIINDIA-EQ produced, twice, on 2026-08-18.
TIINDIA_REJECTION = (
    "Order placement failed: {'code': -50, 'message': "
    "'StopPrice not a multiple of tick size 0.1000', 's': 'error'}"
)


@pytest.fixture(autouse=True)
def _clear_learned():
    _LEARNED_TICKS.clear()
    yield
    _LEARNED_TICKS.clear()


# tick size learned from the broker's own rejection


def test_tick_is_learned_from_the_rejection_message():
    """
    The position payload carries no tick size and NSE revised its bands in 2025,
    so guessing is not viable. The rejection states the exact value.
    """
    assert learn_tick_from_error("NSE:TIINDIA-EQ", TIINDIA_REJECTION) == 0.1
    assert _LEARNED_TICKS["NSE:TIINDIA-EQ"] == 0.1


def test_the_learned_tick_makes_the_rejected_stop_valid():
    """₹2992.85 was rejected on a 0.10 tick. Re-rounding must produce a multiple."""
    tick = learn_tick_from_error("NSE:TIINDIA-EQ", TIINDIA_REJECTION)
    fixed = round_stop_away_from_entry(2992.85, tick, "SHORT")
    assert fixed == pytest.approx(2992.90)
    assert round(fixed / tick) == pytest.approx(fixed / tick, abs=1e-9)


@pytest.mark.parametrize(
    "msg",
    [
        "some unrelated broker error",
        "RED:Margin Shortfall:INR 500",
        "",
        None,
    ],
)
def test_unrelated_errors_teach_nothing(msg):
    assert learn_tick_from_error("NSE:X-EQ", msg) is None
    assert "NSE:X-EQ" not in _LEARNED_TICKS


# rounding never tightens the stop


@pytest.mark.parametrize(
    "side,raw,tick,expected",
    [
        ("SHORT", 2992.85, 0.10, 2992.90),  # away from a short entry = upward
        ("SHORT", 117.79, 0.05, 117.80),
        ("LONG", 2992.85, 0.10, 2992.80),  # away from a long entry = downward
        ("LONG", 117.79, 0.05, 117.75),
    ],
)
def test_stop_rounds_away_from_the_position(side, raw, tick, expected):
    """
    Rounding toward the entry would tighten the stop and could make it
    marketable on arrival. It must always round outward.
    """
    assert round_stop_away_from_entry(raw, tick, side) == pytest.approx(expected)


def test_a_nonsense_tick_falls_back_rather_than_dividing_by_zero():
    assert round_stop_away_from_entry(100.0, 0.0, "SHORT") > 0


# do not place a second stop over an existing one


class FakeOrderbookBroker:
    """Minimal stand-in exposing the orderbook the way the broker does."""

    def __init__(self, orders):
        self._orders = orders

    class _Client:
        def __init__(self, orders):
            self._orders = orders

        def orderbook(self):
            return {"orderBook": self._orders}

    @property
    def rest_client(self):
        return self._Client(self._orders)


def order(symbol="NSE:TIINDIA-EQ", status=6, side=1, otype=3, oid="ORD1"):
    return {"symbol": symbol, "status": status, "side": side, "type": otype, "id": oid}


def find(orders, symbol="NSE:TIINDIA-EQ", sl_side="BUY"):
    import asyncio
    import types

    from shortcircuit.state.reconciliation import ReconciliationEngine

    engine = types.SimpleNamespace(broker=FakeOrderbookBroker(orders))
    return asyncio.run(ReconciliationEngine._find_live_protective_order(engine, symbol, sl_side))


def test_an_existing_pending_stop_is_found():
    """The operator's own stop counts. Whose it is does not matter."""
    assert find([order(oid="USER_SL")]) == "USER_SL"


def test_a_transit_stop_also_counts_as_protection():
    assert find([order(status=4, oid="IN_TRANSIT")]) == "IN_TRANSIT"


@pytest.mark.parametrize(
    "bad,reason",
    [
        (order(status=2), "filled — protects nothing"),
        (order(status=1), "cancelled — protects nothing"),
        (order(otype=1), "plain limit order is a target, not a stop"),
        (order(side=-1), "SELL order does not protect a short"),
        (order(symbol="NSE:OTHER-EQ"), "different symbol"),
    ],
)
def test_orders_that_do_not_protect_are_ignored(bad, reason):
    assert find([bad]) is None, reason


def test_an_sl_limit_order_also_counts():
    """Fyers type 4 is SL-Limit; type 3 is SL-Market. Both are stops."""
    assert find([order(otype=4, oid="SL_LIMIT")]) == "SL_LIMIT"


def test_no_orders_means_no_protection():
    assert find([]) is None


def test_an_unreadable_orderbook_reports_no_protection():
    """
    Fail open deliberately. Not knowing is not evidence of protection: a
    duplicate stop is recoverable, a naked position is not.
    """
    import asyncio
    import types

    from shortcircuit.state.reconciliation import ReconciliationEngine

    class Boom:
        @property
        def rest_client(self):
            raise ConnectionError("broker down")

    engine = types.SimpleNamespace(broker=Boom())
    assert (
        asyncio.run(ReconciliationEngine._find_live_protective_order(engine, "NSE:X-EQ", "BUY"))
        is None
    )


# tick size looked up, not guessed


def test_broker_tick_lookup_caches_and_falls_back():
    """
    Verified against the live API on 2026-08-30:
        NSE:TIINDIA-EQ 0.1 · NSE:SBIN-EQ 0.1 · NSE:CAMLINFINE-EQ 0.01
    The old 0.05 default is wrong in both directions, and NSE revised its tick
    bands in 2025, so it cannot be inferred from price.
    """
    import asyncio
    import types

    from shortcircuit.broker.fyers_broker_interface import FyersBrokerInterface

    calls = []

    class Client:
        def depth(self, data=None):
            calls.append(data["symbol"])
            return {"d": {data["symbol"]: {"tick_Size": 0.1, "ltp": 2840}}}

    stub = types.SimpleNamespace(
        rest_client=Client(),
        _rate_limit_wait=lambda *a, **k: asyncio.sleep(0),
    )
    get_tick = FyersBrokerInterface.get_tick_size.__get__(stub, FyersBrokerInterface)

    assert asyncio.run(get_tick("NSE:TIINDIA-EQ")) == 0.1
    assert asyncio.run(get_tick("NSE:TIINDIA-EQ")) == 0.1
    assert calls == ["NSE:TIINDIA-EQ"], "second call should be served from cache"


def test_tick_lookup_returns_none_rather_than_a_wrong_guess():
    """
    None lets the caller fall back explicitly. Returning 0.05 here would
    reintroduce the exact defect: a plausible number that gets orders rejected.
    """
    import asyncio
    import types

    from shortcircuit.broker.fyers_broker_interface import FyersBrokerInterface

    class Broken:
        def depth(self, data=None):
            raise ConnectionError("depth unavailable")

    stub = types.SimpleNamespace(
        rest_client=Broken(),
        _rate_limit_wait=lambda *a, **k: asyncio.sleep(0),
    )
    get_tick = FyersBrokerInterface.get_tick_size.__get__(stub, FyersBrokerInterface)
    assert asyncio.run(get_tick("NSE:X-EQ")) is None


def test_a_missing_tick_field_is_not_treated_as_a_value():
    import asyncio
    import types

    from shortcircuit.broker.fyers_broker_interface import FyersBrokerInterface

    class NoTick:
        def depth(self, data=None):
            return {"d": {data["symbol"]: {"ltp": 100}}}

    stub = types.SimpleNamespace(
        rest_client=NoTick(),
        _rate_limit_wait=lambda *a, **k: asyncio.sleep(0),
    )
    get_tick = FyersBrokerInterface.get_tick_size.__get__(stub, FyersBrokerInterface)
    assert asyncio.run(get_tick("NSE:X-EQ")) is None
