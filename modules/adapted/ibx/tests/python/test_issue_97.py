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


"""Python callback error resilience tests (issue #97).

Verifies that user exceptions in EWrapper callbacks do not crash the bridge
or abort the dispatch loop. Subsequent callbacks must still fire.
"""

import pytest
from ibx import EClient, EWrapper


class RaisingTickPriceWrapper(EWrapper):
    """tick_price raises, all other callbacks record normally."""

    def __init__(self):
        super().__init__()
        self.events = []

    def tick_price(self, req_id, tick_type, price, attrib):
        msg = "simulated user error in tick_price"
        raise RuntimeError(msg)

    def tick_size(self, req_id, tick_type, size):
        self.events.append(("tick_size", req_id, tick_type, size))

    def error(self, req_id, error_code, error_string, advanced_order_reject_json=""):
        self.events.append(("error", req_id, error_code, error_string))

    def connect_ack(self):
        self.events.append(("connect_ack",))

    def next_valid_id(self, order_id):
        self.events.append(("next_valid_id", order_id))

    def managed_accounts(self, accounts_list):
        self.events.append(("managed_accounts", accounts_list))


def make_client(wrapper):
    c = EClient(wrapper)
    c._test_connect("TEST")
    return c


def test_tick_price_exception_does_not_crash_dispatch():
    """dispatch_once continues after tick_price raises — tick_size still fires."""
    w = RaisingTickPriceWrapper()
    c = make_client(w)
    c._test_set_instrument_count(1)
    c._test_map_instrument(1, 0)
    c._test_push_quote(0, bid=150.0, ask=151.0, bid_size=100, ask_size=200)

    # Should NOT raise — exceptions in callbacks are caught and logged
    c._test_dispatch_once()

    # tick_size should still fire despite tick_price raising
    size_events = [e for e in w.events if e[0] == "tick_size"]
    assert len(size_events) > 0, f"tick_size should fire even when tick_price raises. Events: {w.events}"


def test_subsequent_dispatches_work_after_exception():
    """Multiple dispatch rounds work even when callbacks raise every time."""
    w = RaisingTickPriceWrapper()
    c = make_client(w)
    c._test_set_instrument_count(1)
    c._test_map_instrument(1, 0)

    # Round 1
    c._test_push_quote(0, bid=150.0, bid_size=100)
    c._test_dispatch_once()

    # Round 2 — bridge is not poisoned
    c._test_push_quote(0, bid=151.0, bid_size=200)
    c._test_dispatch_once()

    size_events = [e for e in w.events if e[0] == "tick_size"]
    assert len(size_events) >= 2, f"Multiple dispatch rounds should work. Events: {w.events}"


def test_engine_state_intact_after_callback_exception():
    """Engine state (SharedState, instrument mapping) is unaffected by callback exceptions."""
    w = RaisingTickPriceWrapper()
    c = make_client(w)
    c._test_set_instrument_count(1)
    c._test_map_instrument(1, 0)
    c._test_push_quote(0, bid=150.0, bid_size=100)
    c._test_dispatch_once()

    assert c.is_connected(), "Connection should remain active after callback exception"


class RaisingAllWrapper(EWrapper):
    """Every callback raises — stress test for dispatch resilience."""

    def __init__(self):
        super().__init__()
        self.call_count = 0

    def tick_price(self, req_id, tick_type, price, attrib):
        self.call_count += 1
        msg = "tick_price boom"
        raise ValueError(msg)

    def tick_size(self, req_id, tick_type, size):
        self.call_count += 1
        msg = "tick_size boom"
        raise ValueError(msg)

    def error(self, req_id, error_code, error_string, advanced_order_reject_json=""):
        self.call_count += 1
        msg = "error boom"
        raise ValueError(msg)

    def connect_ack(self):
        self.call_count += 1
        msg = "connect_ack boom"
        raise ValueError(msg)

    def next_valid_id(self, order_id):
        self.call_count += 1
        msg = "next_valid_id boom"
        raise ValueError(msg)

    def managed_accounts(self, accounts_list):
        self.call_count += 1
        msg = "managed_accounts boom"
        raise ValueError(msg)


def test_all_callbacks_raising_does_not_crash():
    """Dispatch survives even when every single callback raises."""
    w = RaisingAllWrapper()
    c = EClient(w)
    c._test_connect("TEST")
    c._test_set_instrument_count(1)
    c._test_map_instrument(1, 0)
    c._test_push_quote(0, bid=150.0, ask=151.0, bid_size=100, ask_size=200)

    # Should not raise
    c._test_dispatch_once()

    # Callbacks were attempted despite raising
    assert w.call_count > 0, "Callbacks should still be called even if they all raise"
