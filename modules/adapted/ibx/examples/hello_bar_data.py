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


"""Recipe: fetch 1 day of 5-minute SPY bars, print first/last bar.

Usage:
    IB_USERNAME=... IB_PASSWORD=... python examples/hello_bar_data.py
"""

import os
import threading

from ibx import Contract, EClient, EWrapper


class BarsWrapper(EWrapper):
    def __init__(self):
        self.connected = threading.Event()
        self.bars = []
        self.done = threading.Event()

    def next_valid_id(self, order_id):
        self.connected.set()

    def historical_data(self, req_id, bar):
        self.bars.append(bar)

    def historical_data_end(self, req_id, start, end):
        self.done.set()

    def error(self, req_id, code, msg, advanced=""):
        if code not in (2104, 2106, 2158):
            print(f"[error] {code}: {msg}")


w = BarsWrapper()
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

c.req_historical_data(
    1,
    spy,
    end_date_time="",
    duration_str="1 D",
    bar_size_setting="5 mins",
    what_to_show="TRADES",
    use_rth=1,
)

if not w.done.wait(timeout=30):
    msg = "historical_data_end not received"
    raise RuntimeError(msg)

print(f"bars: {len(w.bars)}")
if w.bars:
    first, last = w.bars[0], w.bars[-1]
    print(f"  first: {first.date}  O={first.open} H={first.high} L={first.low} C={first.close} V={first.volume}")
    print(f"  last : {last.date}  O={last.open} H={last.high} L={last.low} C={last.close} V={last.volume}")

c.disconnect()
