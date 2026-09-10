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


"""Recipe: place a non-marketable BUY LMT on SPY, watch Submitted, then cancel.

Usage:
    IB_USERNAME=... IB_PASSWORD=... python examples/hello_limit_order.py
"""

import os
import threading

from ibx import Contract, EClient, EWrapper, Order


class OrderWrapper(EWrapper):
    def __init__(self):
        self.next_id = None
        self.connected = threading.Event()
        self.submitted = threading.Event()
        self.cancelled = threading.Event()

    def next_valid_id(self, order_id):
        self.next_id = order_id
        self.connected.set()

    def order_status(
        self,
        order_id,
        status,
        filled,
        remaining,
        avg_fill_price,
        perm_id,
        parent_id,
        last_fill_price,
        client_id,
        why_held,
        mkt_cap_price,
    ):
        print(f"[status] oid={order_id} status={status}")
        if status == "Submitted":
            self.submitted.set()
        if status == "Cancelled":
            self.cancelled.set()

    def error(self, req_id, code, msg, advanced=""):
        if code not in (2104, 2106, 2158):
            print(f"[error] {code}: {msg}")


w = OrderWrapper()
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

order_id = w.next_id

spy = Contract()
spy.con_id = 756733
spy.symbol = "SPY"
spy.sec_type = "STK"
spy.exchange = "SMART"
spy.currency = "USD"

order = Order()
order.action = "BUY"
order.total_quantity = 1
order.order_type = "LMT"
order.lmt_price = 1.00
order.tif = "DAY"
order.outside_rth = True

print(f"placing BUY 1 SPY LMT 1.00 (oid={order_id})")
c.place_order(order_id, spy, order)
w.submitted.wait(timeout=15)

print(f"cancelling oid={order_id}")
c.cancel_order(order_id, "")
w.cancelled.wait(timeout=15)

c.disconnect()
