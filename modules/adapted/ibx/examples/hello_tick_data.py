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


"""Recipe: stream SPY market data for 5 seconds, print latest bid/ask/last.

Usage:
    IB_USERNAME=... IB_PASSWORD=... python examples/hello_tick_data.py
"""

import os
import threading
import time

from ibx import Contract, EClient, EWrapper


class TickWrapper(EWrapper):
    def __init__(self):
        self.connected = threading.Event()
        self.bid = 0.0
        self.ask = 0.0
        self.last = 0.0
        self.ticks = 0

    def next_valid_id(self, order_id):
        self.connected.set()

    def tick_price(self, req_id, tick_type, price, attrib):
        self.ticks += 1
        if tick_type == 1:
            self.bid = price
        elif tick_type == 2:
            self.ask = price
        elif tick_type == 4:
            self.last = price

    def tick_size(self, req_id, tick_type, size):
        self.ticks += 1

    def error(self, req_id, code, msg, advanced=""):
        if code not in (2104, 2106, 2158):
            print(f"[error] {code}: {msg}")


w = TickWrapper()
c = EClient(w)
c.connect(
    username=os.environ["IB_USERNAME"],
    password=os.environ["IB_PASSWORD"],
    host="cdc1.ibllc.com",
    paper=True,
)
threading.Thread(target=c.run, daemon=True).start()
if not w.connected.wait(timeout=15):
    msg = "connect failed"
    raise RuntimeError(msg)

spy = Contract()
spy.con_id = 756733
spy.symbol = "SPY"
spy.sec_type = "STK"
spy.exchange = "SMART"
spy.currency = "USD"

req_id = 1
print("streaming SPY for 5s…")
c.req_mkt_data(req_id, spy, "", False, False)
deadline = time.monotonic() + 5
while time.monotonic() < deadline:
    time.sleep(0.1)
c.cancel_mkt_data(req_id)

print(f"ticks: {w.ticks}  bid={w.bid:.2f}  ask={w.ask:.2f}  last={w.last:.2f}")
c.disconnect()
