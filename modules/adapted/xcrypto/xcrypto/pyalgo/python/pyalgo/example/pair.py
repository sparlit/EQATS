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


from pyalgo import *


class Demo:
    """"""

    def __init__(self, leading: DepthSubscription, hedge: DepthSubscription):
        self.leading = leading
        self.hedge = hedge

        # set callback
        self.leading.on_data = self.on_depth
        self.hedge.on_data = self.on_depth

    def on_depth(self, depth: Depth):
        print(
            depth.datetime,
            depth.symbol,
            self.leading.bid_prc(0) - self.hedge.bid_prc(0),
        )


if __name__ == "__main__":
    eng = Engine(0.001)
    session = eng.make_session(addr="ws://localhost:8111", session_id=1, name="test", trading=True)

    leading = session.subscribe("dogeusdt", "depth")
    hedge = session.subscribe("btcusdt", "depth")
    demo = Demo(leading, hedge)
    eng.run()
