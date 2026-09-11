import datetime
import time
from asyncio import get_event_loop

import pytz


def is_ist_market_session_active(dt: datetime.datetime | None = None) -> bool:
    """Checks whether current or provided time falls within NSE/BSE IST market session (09:15 to 15:30 IST Mon-Fri)."""
    ist = pytz.timezone("Asia/Kolkata")
    if dt is not None:
        if dt.tzinfo is None:
            dt = ist.localize(dt)
        now = dt.astimezone(ist)
    else:
        now = datetime.datetime.now(tz=ist)
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


class MockTectonicDB:
    """Mock TectonicDB for latency measurement when tectonic module is unavailable."""

    def __init__(self):
        self._data = {}

    async def insert(self, *args, **kwargs):
        await asyncio.sleep(0.0001)
        return True

    def destroy(self):
        pass


try:
    from tectonic import TectonicDB
except ImportError:
    import asyncio

    TectonicDB = MockTectonicDB


async def measure_latency():
    dts = []
    db = TectonicDB()
    t = time.perf_counter()
    for _ in range(10000):
        await db.insert(0, 0, True, True, 0.0, 0.0, "default")
        t_ = time.perf_counter()
        dt = t_ - t
        t = t_
        dts.append(dt)
    print(f"AVG: {sum(dts) / len(dts):.6f}s")
    db.destroy()


if __name__ == "__main__":
    loop = get_event_loop()
    measure = measure_latency()
    loop.run_until_complete(measure)
