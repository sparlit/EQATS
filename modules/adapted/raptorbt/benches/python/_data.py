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


import numpy as np


def bars(n, seed=7):
    """Bounded random walk -- clipped in log space so 25M bars stay finite."""
    rng = np.random.default_rng(seed)
    steps = rng.normal(0, 0.001, n)
    logp = np.cumsum(steps)
    logp = np.clip(logp, -1.0, 1.0) + np.log(1000.0)
    close = np.exp(logp)
    spread = close * 0.0008
    o = close + rng.normal(0, spread / 2)
    h = np.maximum(o, close) + np.abs(rng.normal(0, spread))
    l = np.minimum(o, close) - np.abs(rng.normal(0, spread))
    v = np.abs(rng.normal(1e5, 2e4, n))
    ts = np.arange(n, dtype=np.int64) * 60_000_000_000
    return ts, o, h, l, close, v


def sma_signals(close, fast=10, slow=30):
    def sma(a, w):
        c = np.cumsum(np.insert(a, 0, 0.0))
        out = np.full(len(a), np.nan)
        out[w - 1 :] = (c[w:] - c[:-w]) / w
        return out

    f, s = sma(close, fast), sma(close, slow)
    up = (f > s) & ~np.isnan(f) & ~np.isnan(s)
    entries = np.zeros(len(close), bool)
    exits = np.zeros(len(close), bool)
    entries[1:] = up[1:] & ~up[:-1]
    exits[1:] = ~up[1:] & up[:-1]
    return entries, exits
