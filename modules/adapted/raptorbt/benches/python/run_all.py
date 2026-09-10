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


def _ticks(n, seed=11):
    import numpy as np

    rng = np.random.default_rng(seed)
    logp = np.clip(np.cumsum(rng.normal(0, 0.00005, n)), -0.5, 0.5) + np.log(1000.0)
    ltp = np.exp(logp)
    half = ltp * 0.00025
    bq = np.abs(rng.normal(500, 150, n))
    sq = np.abs(rng.normal(500, 150, n))
    return ltp, half, bq, sq


"""Produce every published raptorbt performance figure.

Run after `uv run maturin develop --release`. Prints the table used in the docs
and writes a JSON summary next to this file. See README.md in this directory for
why the 0.7.0 numbers are not comparable to the 0.6.4 ones.
"""

import hashlib
import json
import pathlib
import platform
import resource
import sys
import time

try:
    import numpy as np
except ImportError:
    np = None

try:
    import raptorbt as r
except ImportError:
    r = None

sys.path.insert(0, str(pathlib.Path(__file__).parent))
try:
    from _data import bars, sma_signals
except ImportError:
    bars = None
    sma_signals = None

CAPITAL = 100_000.0
FEES = 0.0002


def _cfg():
    if r is None:
        msg = "raptorbt not installed"
        raise RuntimeError(msg)
    return r.BacktestConfig(initial_capital=CAPITAL, fees=FEES)


def _time(fn, reps):
    """Fastest of `reps` runs -- engine time, not scheduler noise."""
    samples = []
    out = None
    for _ in range(reps):
        t0 = time.perf_counter()
        out = fn()
        samples.append(time.perf_counter() - t0)
    samples.sort()
    return samples[0], samples[len(samples) // 2], out


def bench_bars():
    if np is None or r is None or bars is None or sma_signals is None:
        msg = "Required dependencies not available"
        raise RuntimeError(msg)
    rows = {}
    cfg = _cfg()
    for n, reps in (
        (1_000, 5000),
        (5_000, 3000),
        (10_000, 2000),
        (50_000, 1000),
        (93_750, 500),
        (1_875_000, 30),
        (25_000_000, 3),
    ):
        ts, o, h, l, c, v = bars(n)
        e, x = sma_signals(c)
        best, p50, res = _time(
            lambda: r.run_single_backtest(
                timestamps=ts,
                open=o,
                high=h,
                low=l,
                close=c,
                volume=v,
                entries=e,
                exits=x,
                direction=1,
                weight=1.0,
                symbol="B",
                config=cfg,
            ),
            reps,
        )
        rows[n] = {
            "best_ms": best * 1e3,
            "p50_ms": p50 * 1e3,
            "m_bars_per_s": n / best / 1e6,
            "trades": res.metrics.total_trades,
        }
    return rows
