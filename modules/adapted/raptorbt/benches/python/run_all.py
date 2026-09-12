import datetime
import hashlib
import json
import pathlib
import platform
import resource
import sys
import time

import pytz

try:
    import numpy as np
except ImportError:
    np = None

try:
    import raptorbt as r
except ImportError:
    r = None


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


def _ticks(n, seed=11):
    if np is None:
        msg = "numpy is required for _ticks"
        raise RuntimeError(msg)
    rng = np.random.default_rng(seed)
    logp = np.clip(np.cumsum(rng.normal(0, 0.00005, n)), -0.5, 0.5) + np.log(1000.0)
    ltp = np.exp(logp)
    half = ltp * 0.00025
    bq = np.abs(rng.normal(500, 150, n))
    sq = np.abs(rng.normal(500, 150, n))
    return ltp, half, bq, sq


if __name__ == "__main__":
    pass
