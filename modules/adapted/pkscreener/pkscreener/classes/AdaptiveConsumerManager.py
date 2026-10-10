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


"""
    The MIT License (MIT)

    Copyright (c) 2023 pkjmesra

    Permission is hereby granted, free of charge, to any person obtaining a copy
    of this software and associated documentation files (the "Software"), to deal
    in the Software without restriction, including without limitation the rights
    to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
    copies of the Software, and to permit persons to whom the Software is
    furnished to do so, subject to the following conditions:

    The above copyright notice and this permission notice shall be included in all
    copies or substantial portions of the Software.

    THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
    IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
    FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
    AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
    LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
    OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
    SOFTWARE.

"""


class AdaptiveConsumerManager:
    """
    Dynamically adjusts consumer count based on workload and platform.

    This class measures processing time and adjusts the number of consumers
    to find the optimal balance for the current hardware and workload.
    """

    _instance = None
    _optimal_consumers = None
    _last_measurement = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @staticmethod
    def get_optimal_consumers(items_count, userPassedArgs=None):
        """
        Determine the optimal number of consumers based on multiple factors.

        Returns:
            int: Recommended number of consumer processes
        """
        import multiprocessing
        import sys

        import psutil  # Optional, for better system info

        cpu_count = multiprocessing.cpu_count()
        memory_gb = psutil.virtual_memory().total / (1024**3) if "psutil" in sys.modules else 8

        # Base calculation
        base_consumers = cpu_count

        # Platform adjustments
        if sys.platform.startswith("win"):
            # Windows spawn is expensive - reduce by 50-75%
            base_consumers = max(2, cpu_count // 2)
        elif sys.platform.startswith("darwin"):
            # macOS moderate overhead - reduce by 25-33%
            base_consumers = max(2, int(cpu_count * 0.66))
        else:
            # Linux efficient - use all cores or slightly more
            base_consumers = cpu_count

        # Memory constraints
        if memory_gb < 4:
            base_consumers = min(base_consumers, 2)
        elif memory_gb < 8:
            base_consumers = min(base_consumers, 4)

        # Workload-based adjustment
        if userPassedArgs and userPassedArgs.stocklist:
            # Specific stocks - fewer consumers needed
            stock_count = len(userPassedArgs.stocklist.split(","))
            if stock_count < 50:
                base_consumers = min(base_consumers, 2)
            elif stock_count < 200:
                base_consumers = min(base_consumers, 4)

        # For single stock analysis, use single process
        if userPassedArgs and userPassedArgs.options and ":0:" in userPassedArgs.options:
            base_consumers = 1

        # Cap based on items count (no point having more consumers than items)
        base_consumers = min(base_consumers, max(1, items_count // 100))

        # Ensure reasonable bounds
        base_consumers = max(1, min(base_consumers, 12))

        AdaptiveConsumerManager._optimal_consumers = base_consumers
        return base_consumers
