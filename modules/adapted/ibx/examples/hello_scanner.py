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


"""Recipe: subscribe to TOP_PERC_GAIN scanner, print first 10 results.

Usage:
    IB_USERNAME=... IB_PASSWORD=... python examples/hello_scanner.py
"""

import os
import threading

from ibx import EClient, EWrapper


class ScannerSubscription:
    def __init__(self):
        self.instrument = "STK"
        self.locationCode = "STK.US.MAJOR"
        self.scanCode = "TOP_PERC_GAIN"
        self.numberOfRows = 25


class ScannerWrapper(EWrapper):
    def __init__(self):
        self.connected = threading.Event()
        self.rows = []
        self.done = threading.Event()

    def next_valid_id(self, order_id):
        self.connected.set()

    def scanner_data(self, req_id, rank, contract_details, distance, benchmark, projection, legs_str):
        self.rows.append((rank, contract_details))

    def scanner_data_end(self, req_id):
        self.done.set()

    def error(self, req_id, code, msg, advanced=""):
        if code not in (2104, 2106, 2158):
            print(f"[error] {code}: {msg}")


w = ScannerWrapper()
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

req_id = 1
print("subscribing TOP_PERC_GAIN, STK.US.MAJOR…")
c.req_scanner_subscription(req_id, ScannerSubscription())

if not w.done.wait(timeout=30):
    print(f"(scanner_data_end not received; got {len(w.rows)} rows so far)")

w.rows.sort(key=lambda r: r[0])
print(f"results: {len(w.rows)}")
for rank, d in w.rows[:10]:
    print(f"  #{rank:<3}  {d.contract.symbol:<8} {d.contract.primary_exchange:<6} con_id={d.contract.con_id}")

c.cancel_scanner_subscription(req_id)
c.disconnect()
