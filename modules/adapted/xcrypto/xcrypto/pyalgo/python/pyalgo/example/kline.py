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

    def __init__(self, depth: DepthSubscription, kline: BarSubscription):
        self.depth = depth
        self.kline = kline

        # set callback
        self.depth.on_data = self.on_depth
        self.kline.on_data = self.on_kline

    def on_kline(self, kline: Kline):
        print(
            self.kline.datetime,
            self.kline.open,
            self.kline.high,
            self.kline.low,
            self.kline.close,
        )

    def on_depth(self, depth: Depth):
        print(
            depth.datetime,
            depth.symbol,
        )


if __name__ == "__main__":
    eng = Engine(0.001)
    session = eng.make_session(addr="ws://localhost:8111", session_id=1, name="test", trading=True)

    depth = session.subscribe("dogeusdt", "depth")
    kline = session.subscribe("btcusdt", "kline:1m")
    demo = Demo(depth, kline)
    eng.run()
