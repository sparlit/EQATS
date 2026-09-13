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

    def __init__(self, sub: DepthSubscription):
        self.sub = sub
        # use to send/kill order
        self.smtord = SmartOrder(sub)

        self.fin = False

        # add trading phase if you need
        # otherwise self.sub.phase is always Phase.UNDEF
        self.sub.add_phase(0, 0, 0, Phase.OPEN)
        self.sub.add_phase(16, 0, 0, Phase.CLOSE)

        # set callback
        self.sub.on_data = self.on_depth
        self.sub.on_order = self.on_order

    def on_order(self, order: Order):
        print(order)

    def on_depth(self, depth: Depth):
        print(self.sub.datetime, self.sub.symbol)

        match self.sub.phase:
            case Phase.OPEN:
                if self.sub.net == 0:
                    if not self.fin:
                        if self.smtord.is_active:
                            self.smtord.kill()

                        else:
                            self.smtord.send(
                                self.sub.bid_prc(5),
                                10,
                                Side.BUY,
                                OrderType.LIMIT,
                                Tif.GTC,
                            )
                            self.fin = True

            case Phase.CLOSE:
                # TODO
                pass


if __name__ == "__main__":
    eng = Engine(0.001)
    session = eng.make_session(addr="ws://localhost:8111", session_id=1, name="test", trading=True)

    sub = session.subscribe("dogeusdt", "depth")
    demo = Demo(sub)
    eng.run()
