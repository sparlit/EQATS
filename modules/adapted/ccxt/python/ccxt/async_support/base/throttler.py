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
import collections
from time import time


class Throttler:
    def __init__(self, config, loop=None):
        self.loop = loop
        self.config = {
            "refillRate": 1.0,  # leaky bucket refill rate in tokens per second
            "delay": 0.001,  # leaky bucket seconds before checking the queue after waiting
            "capacity": 1.0,  # leaky bucket
            "tokens": 0,  # leaky bucket
            "cost": 1.0,  # leaky bucket and rolling window
            "algorithm": "leakyBucket",
            "windowSize": 60000.0,  # rolling window size in milliseconds
            "maxWeight": 0.0,  # rolling window - rollingWindowSize / rateLimit   // ms_of_window / ms_of_rate_limit
        }
        self.config.update(config)
        if self.config["algorithm"] != "leakyBucket":
            self.config["maxWeight"] = self.config["windowSize"] / self.config["rateLimit"]
        self.queue = collections.deque()
        self.running = False
        self.timestamps = []

    async def leaky_bucket_loop(self):
        last_timestamp = time() * 1000
        while self.running:
            future, cost = self.queue[0]
            cost = self.config["cost"] if cost is None else cost
            if self.config["tokens"] >= 0:
                self.config["tokens"] -= cost
                if not future.done():
                    future.set_result(None)
                self.queue.popleft()
                # context switch
                await asyncio.sleep(0)
                if len(self.queue) == 0:
                    self.running = False
            else:
                await asyncio.sleep(self.config["delay"])
                now = time() * 1000
                elapsed = now - last_timestamp
                last_timestamp = now
                self.config["tokens"] = min(
                    self.config["tokens"] + elapsed * self.config["refillRate"], self.config["capacity"]
                )

    async def rolling_window_loop(self):
        while self.running:
            future, cost = self.queue[0]
            cost = self.config["cost"] if cost is None else cost
            now = time() * 1000
            cutoffTime = now - self.config["windowSize"]
            totalCost = 0
            # Remove expired timestamps & sum the remaining requests
            timestamps = []
            for t in self.timestamps:
                if t["timestamp"] > cutoffTime:
                    totalCost += t["cost"]
                    timestamps.append(t)
            self.timestamps = timestamps
            # handle current request
            if totalCost + cost <= self.config["maxWeight"]:
                self.timestamps.append({"timestamp": now, "cost": cost})
                if not future.done():
                    future.set_result(None)
                self.queue.popleft()
                # context switch
                await asyncio.sleep(0)
                if not self.queue:
                    self.running = False
            else:
                wait_time = (self.timestamps[0]["timestamp"] + self.config["windowSize"]) - now
                if wait_time > 0:
                    await asyncio.sleep(wait_time / 1000)

    async def looper(self):
        if self.config["algorithm"] == "leakyBucket":
            await self.leaky_bucket_loop()
        else:
            await self.rolling_window_loop()

    def __call__(self, cost=None):
        future = asyncio.Future()
        self.queue.append((future, cost))
        if not self.running:
            self.running = True
            asyncio.ensure_future(self.looper(), loop=self.loop)
        return future
