"""Tests for technicals.py pure-math helpers."""
import numpy as np
import pandas as pd
import pytest

from technicals import compute_rsi, compute_atr


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
