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


# Raw keep-alive HTTPS GET baseline — no CCXT. aiohttp (what CCXT async uses) through the agent proxy.
import asyncio
import json
import os
import ssl
import sys
import time

import aiohttp
import certifi

URL = "https://api.coinbase.com/api/v3/brokerage/market/product_book?product_id=BTC-USD"
N = int(sys.argv[1]) if len(sys.argv) > 1 else 10


async def main():
    ctx = ssl.create_default_context(cafile=os.environ.get("SSL_CERT_FILE", certifi.where()))
    conn = aiohttp.TCPConnector(ssl=ctx, limit=10, keepalive_timeout=60)
    proxy = os.environ.get("HTTPS_PROXY")
    async with aiohttp.ClientSession(connector=conn) as s:

        async def get():
            async with s.get(URL, proxy=proxy) as r:
                return len(await r.read())

        for _ in range(3):
            await get()
        t, b = [], 0
        for _ in range(N):
            a = time.perf_counter()
            b = await get()
            t.append(round((time.perf_counter() - a) * 1000, 2))
            await asyncio.sleep(0.25)
        print(json.dumps({"lang": "Python", "samples": t, "bytes": b}))


asyncio.run(main())
