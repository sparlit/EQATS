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


"""Live-account login recipe: connect with paper=False, wait for next_valid_id,
disconnect. Read-only — no orders, no market data.

When the live login triggers a second-factor push, approve it on your mobile
authenticator. The connect call blocks until the gate clears.

Usage:
    IB_LIVE_USERNAME=... IB_LIVE_PASSWORD=... python examples/hello_login_live.py
"""

import os
import threading

from ibx import EClient, EWrapper


class LoginWrapper(EWrapper):
    def __init__(self):
        self.ready = threading.Event()
        self.order_id = None

    def next_valid_id(self, order_id):
        self.order_id = order_id
        self.ready.set()


w = LoginWrapper()
c = EClient(w)
c.connect(
    username=os.environ["IB_LIVE_USERNAME"],
    password=os.environ["IB_LIVE_PASSWORD"],
    host=os.environ.get("IB_HOST", "cdc1.ibllc.com"),
    paper=False,
)
threading.Thread(target=c.run, daemon=True).start()

if not w.ready.wait(timeout=60):
    msg = "did not receive next_valid_id"
    raise RuntimeError(msg)

print(f"logged in LIVE. next_valid_id = {w.order_id}")

c.disconnect()
