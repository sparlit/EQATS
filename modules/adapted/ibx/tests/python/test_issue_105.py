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


"""IBX Test #105: Combo/spread order encoding (SPY vertical call spread).

Tests multi-leg BAG contract construction and order placement.
Note: ComboLeg population from Python is not yet implemented — this test
verifies individual option leg market data as a fallback.

Run: pytest tests/python/test_issue_105.py -v -s
"""

import os
import threading
import time

import pytest
from ibx import Contract, EClient, EWrapper

pytestmark = pytest.mark.skipif(
    not (os.environ.get("IB_USERNAME") and os.environ.get("IB_PASSWORD")),
    reason="IB_USERNAME and IB_PASSWORD not set",
)

SPY_CON_ID = 756733


class SpreadWrapper(EWrapper):
    def __init__(self):
        super().__init__()
        self.connected = threading.Event()
        self.lock = threading.Lock()
        self.ticks = {}  # req_id -> {bid, ask, last}
        self.got_tick = {}  # req_id -> Event
        self.underlying_price = 0.0
        self.got_underlying = threading.Event()
        self.errors = []

    def next_valid_id(self, order_id):
        self.next_order_id = order_id
        self.connected.set()

    def managed_accounts(self, accounts_list):
        pass

    def connect_ack(self):
        pass

    def tick_price(self, req_id, tick_type, price, attrib):
        if price > 0:
            with self.lock:
                if req_id == 1000:
                    if tick_type in (1, 2, 4):
                        self.underlying_price = price
                        self.got_underlying.set()
                else:
                    self.ticks.setdefault(req_id, {})
                    if tick_type == 1:
                        self.ticks[req_id]["bid"] = price
                    elif tick_type == 2:
                        self.ticks[req_id]["ask"] = price
                    elif tick_type == 4:
                        self.ticks[req_id]["last"] = price
                    ev = self.got_tick.get(req_id)
                    if ev:
                        ev.set()

    def tick_size(self, req_id, tick_type, size):
        pass

    def error(self, req_id, error_code, error_string, advanced_order_reject_json=""):
        self.errors.append((req_id, error_code, error_string))
        if error_code not in (2104, 2106, 2119, 2158, 460, 202):
            print(f"  [error] reqId={req_id} code={error_code}: {error_string}")


class TestComboSpread:
    """Issue #105: Option spread leg market data."""

    @pytest.fixture(autouse=True)
    def setup_connection(self):
        self.wrapper = SpreadWrapper()
        self.client = EClient(self.wrapper)
        self.client.connect(
            username=os.environ["IB_USERNAME"],
            password=os.environ["IB_PASSWORD"],
            host=os.environ.get("IB_HOST", "cdc1.ibllc.com"),
            paper=True,
        )
        self.thread = threading.Thread(target=self.client.run, daemon=True)
        self.thread.start()
        assert self.wrapper.connected.wait(timeout=15), "Connection failed"
        yield
        self.client.disconnect()
        self.thread.join(timeout=5)

    def test_vertical_spread_legs(self):
        """Get market data for two option legs of a bull call spread."""
        # Get SPY underlying price
        spy = Contract()
        spy.con_id = SPY_CON_ID
        spy.symbol = "SPY"
        spy.sec_type = "STK"
        spy.exchange = "SMART"
        spy.currency = "USD"

        self.client.req_mkt_data(1000, spy, "", False)
        got = self.wrapper.got_underlying.wait(timeout=30)
        self.client.cancel_mkt_data(1000)
        if not got:
            pytest.skip("No SPY price — market may be closed")

        price = self.wrapper.underlying_price
        # ATM and OTM strikes (round to nearest integer)
        atm_strike = round(price)
        otm_strike = atm_strike + 3
        print(f"  SPY: {price}, buy leg strike: {atm_strike}, sell leg strike: {otm_strike}")

        # Build option contracts for both legs
        buy_leg = Contract()
        buy_leg.symbol = "SPY"
        buy_leg.sec_type = "OPT"
        buy_leg.exchange = "SMART"
        buy_leg.currency = "USD"
        buy_leg.right = "C"
        buy_leg.strike = float(atm_strike)
        buy_leg.last_trade_date_or_contract_month = "20260424"
        buy_leg.multiplier = "100"

        sell_leg = Contract()
        sell_leg.symbol = "SPY"
        sell_leg.sec_type = "OPT"
        sell_leg.exchange = "SMART"
        sell_leg.currency = "USD"
        sell_leg.right = "C"
        sell_leg.strike = float(otm_strike)
        sell_leg.last_trade_date_or_contract_month = "20260424"
        sell_leg.multiplier = "100"

        # Subscribe to both legs
        self.wrapper.got_tick[3001] = threading.Event()
        self.wrapper.got_tick[3002] = threading.Event()

        self.client.req_mkt_data(3001, buy_leg, "", False)
        self.client.req_mkt_data(3002, sell_leg, "", False)

        got_buy = self.wrapper.got_tick[3001].wait(timeout=30)
        got_sell = self.wrapper.got_tick[3002].wait(timeout=30)

        # Wait for bid/ask to populate
        time.sleep(5)

        self.client.cancel_mkt_data(3001)
        self.client.cancel_mkt_data(3002)

        if not got_buy and not got_sell:
            pytest.skip("No option tick data — usopt farm may not be available")

        buy_data = self.wrapper.ticks.get(3001, {})
        sell_data = self.wrapper.ticks.get(3002, {})

        print(f"  Buy leg ({atm_strike}C): {buy_data}")
        print(f"  Sell leg ({otm_strike}C): {sell_data}")

        # Verify buy leg is more expensive than sell leg (bull call spread)
        if "bid" in buy_data and "bid" in sell_data:
            spread_bid = buy_data["bid"] - sell_data.get("ask", sell_data["bid"])
            spread_ask = buy_data.get("ask", buy_data["bid"]) - sell_data["bid"]
            print(f"  Spread value: {spread_bid:.2f} - {spread_ask:.2f}")
            assert buy_data["bid"] > sell_data["bid"], "ATM call should be more expensive than OTM call"
