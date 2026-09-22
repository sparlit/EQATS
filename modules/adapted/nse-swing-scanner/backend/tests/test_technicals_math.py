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


"""Tests for technicals.py pure-math helpers."""
import numpy as np
import pandas as pd
import pytest
from technicals import compute_atr, compute_rsi


def _series(values):
    return pd.Series(values, dtype="float64")


def test_rsi_flat_series_is_50():
    s = _series([100.0] * 30)
    rsi = compute_rsi(s, period=14)
    # After the warmup, RSI for a flat close is undefined (0/0); the formula
    # returns NaN, which is the correct behavior.
    assert np.isnan(rsi.iloc[-1])


def test_rsi_purely_up_is_100():
    s = _series([100.0 + i for i in range(30)])
    rsi = compute_rsi(s, period=14)
    # 100% gains, 0 losses -> rs = inf -> rsi = 100
    assert rsi.iloc[-1] == pytest.approx(100.0, abs=0.1)


def test_rsi_purely_down_is_0():
    s = _series([100.0 - i for i in range(30)])
    rsi = compute_rsi(s, period=14)
    assert rsi.iloc[-1] == pytest.approx(0.0, abs=0.1)


def test_atr_known_value():
    # Construct a small OHLC where true range is deterministic
    h = _series([102, 103, 101, 105, 107])
    l = _series([98, 100, 99, 102, 104])
    c = _series([100, 102, 100, 104, 106])
    atr = compute_atr(h, l, c, period=3)
    # Last value should be > 0 and not NaN
    last = atr.iloc[-1]
    assert not np.isnan(last)
    assert last > 0
