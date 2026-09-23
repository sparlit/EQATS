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


import asyncio
import json

from tectonic import TectonicDB


async def subscribe(name):
    db = TectonicDB()
    print(await db.subscribe(name))
    while 1:
        _, item = await db.poll()
        if item == b"NONE":
            await asyncio.sleep(0.01)
        else:
            yield json.loads(item)


class TickBatcher:
    def __init__(self, db_name):
        self.one_batch = []
        self.db_name = db_name

    async def batch(self):
        generator = subscribe(self.db_name)
        async for item in generator:
            self.one_batch.append(item)

    async def timer(self):
        while 1:
            await asyncio.sleep(5)
            print(self.one_batch)


if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    proc = TickBatcher("bnc_eth_btc")
    loop.create_task(proc.batch())
    loop.create_task(proc.timer())
    loop.run_forever()
    loop.close()
