import asyncio
import datetime
import json
from collections.abc import AsyncGenerator
from typing import Any

import pytz

try:
    from tectonic import TectonicDB
except ImportError:

    class TectonicDB:
        """Mock TectonicDB for environments without tectonic installed."""

        async def subscribe(self, name: str) -> bool:
            return True

        async def poll(self) -> tuple[Any, bytes]:
            await asyncio.sleep(0.1)
            return (None, b"NONE")


def is_ist_market_session_active(dt: datetime.datetime | None = None) -> bool:
    """Checks whether current or provided time falls within NSE/BSE IST market session (09:15 to 15:30 IST Mon-Fri)."""
    ist = pytz.timezone("Asia/Kolkata")
    if dt is not None:
        if dt.tzinfo is None:
            dt = ist.localize(dt)
        now = dt.astimezone(ist)
    else:
        now = datetime.datetime.now(ist)
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


async def subscribe(name: str) -> AsyncGenerator[dict]:
    db = TectonicDB()
    print(await db.subscribe(name))
    while True:
        _, item = await db.poll()
        if item == b"NONE":
            await asyncio.sleep(0.01)
        else:
            yield json.loads(item)


class TickBatcher:
    def __init__(self, db_name: str):
        self.one_batch: list[dict] = []
        self.db_name = db_name

    async def batch(self) -> None:
        async for item in subscribe(self.db_name):
            self.one_batch.append(item)

    async def timer(self) -> None:
        while True:
            await asyncio.sleep(5)
            print(self.one_batch)


if __name__ == "__main__":
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    proc = TickBatcher("bnc_eth_btc")
    loop.create_task(proc.batch())
    loop.create_task(proc.timer())
    try:
        loop.run_forever()
    finally:
        loop.close()
