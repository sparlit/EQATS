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


"""Recipe: subscribe to account-level PnL, take one update, then cancel.

Usage:
    IB_USERNAME=... IB_PASSWORD=... python examples/hello_pnl.py
"""

import os
import threading

from ibx import EClient, EWrapper


class PnlWrapper(EWrapper):
    def __init__(self):
        self.connected = threading.Event()
        self.got_pnl = threading.Event()
        self.pnl_data = None

    def next_valid_id(self, order_id):
        self.connected.set()

    def pnl(self, req_id, daily_pnl, unrealized_pnl, realized_pnl):
        self.pnl_data = (daily_pnl, unrealized_pnl, realized_pnl)
        self.got_pnl.set()

    def error(self, req_id, code, msg, advanced=""):
        if code not in (2104, 2106, 2158):
            print(f"[error] {code}: {msg}")


w = PnlWrapper()
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

account = c.get_account_id()
print(f"account: {account}")

req_id = 1
c.req_pnl(req_id, account)

if w.got_pnl.wait(timeout=15):
    daily, unrealized, realized = w.pnl_data
    print(f"daily={daily:.2f}  unrealized={unrealized:.2f}  realized={realized:.2f}")
else:
    print("no pnl update within 15s — try again with an open position")

c.cancel_pnl(req_id)
c.disconnect()
