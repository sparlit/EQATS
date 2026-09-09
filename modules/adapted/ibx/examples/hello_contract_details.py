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


"""Recipe: req_contract_details for AAPL on paper, print con_id and primary exchange.

Usage:
    IB_USERNAME=... IB_PASSWORD=... python examples/hello_contract_details.py
"""

import os
import threading

from ibx import Contract, EClient, EWrapper


class DetailsWrapper(EWrapper):
    def __init__(self):
        self.connected = threading.Event()
        self.rows = []
        self.done = threading.Event()

    def next_valid_id(self, order_id):
        self.connected.set()

    def contract_details(self, req_id, details):
        self.rows.append(details)

    def contract_details_end(self, req_id):
        self.done.set()

    def error(self, req_id, code, msg, advanced=""):
        if code not in (2104, 2106, 2158):
            print(f"[error] {code}: {msg}")


w = DetailsWrapper()
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

aapl = Contract()
aapl.symbol = "AAPL"
aapl.sec_type = "STK"
aapl.exchange = "SMART"
aapl.currency = "USD"
c.req_contract_details(1, aapl)

if not w.done.wait(timeout=15):
    msg = "contract_details_end not received"
    raise RuntimeError(msg)

print(f"matches: {len(w.rows)}")
for d in w.rows:
    print(
        f"  con_id={d.contract.con_id:>8}  "
        f"primary={d.contract.primary_exchange:<10}  "
        f"trading_class={d.contract.trading_class}"
    )

c.disconnect()
