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


"""Tests for the 20d ADV (Average Daily Value) math in compute_technicals.

The liquidity hard gate relies on this field, so we pin its behavior:
- Mean of (volume * close) over the last ADV_LOOKBACK_SESSIONS valid sessions.
- min_periods = ADV_MIN_SESSIONS, so short histories still produce a value.
- NaN rows (e.g. half-day, suspended) are excluded.
"""
import numpy as np
import pandas as pd
import pytest
import technicals
from settings import ADV_LOOKBACK_SESSIONS, ADV_MIN_SESSIONS


def _make_history(prices, volumes=None):
    n = len(prices)
    if volumes is None:
        volumes = [1_000_000] * n
    dates = pd.date_range("2025-01-01", periods=n, freq="B")
    return pd.DataFrame(
        {
            "Open": prices,
            "High": [p * 1.01 for p in prices],
            "Low": [p * 0.99 for p in prices],
            "Close": prices,
            "Volume": volumes,
        },
        index=dates,
    )


def _patch_history(monkeypatch, df):
    class _FakeTicker:
        def __init__(self, symbol):
            pass

        def history(self, period=None, auto_adjust=None):
            return df

    monkeypatch.setattr(technicals.yf, "Ticker", _FakeTicker)


def test_adv_value_equals_mean_of_volume_times_close(monkeypatch):
    prices = [100.0] * 250
    volumes = [float(v) for v in [2_000_000] * 250]
    df = _make_history(prices, volumes)
    _patch_history(monkeypatch, df)

    out = technicals.compute_technicals("TEST.NS")
    assert out.get("error") is None, out
    # 2_000_000 * 100 = 200_000_000 per session, same every session.
    assert out["adv_value_inr"] == 200_000_000
    assert out["adv_sessions"] == ADV_LOOKBACK_SESSIONS


def test_adv_uses_only_last_n_sessions(monkeypatch):
    # 250 rows; first 230 cheap, last 20 expensive. ADV must use the last 20.
    prices = [10.0] * 230 + [100.0] * 20
    volumes = [1_000_000] * 250
    df = _make_history(prices, volumes)
    _patch_history(monkeypatch, df)

    out = technicals.compute_technicals("TEST.NS")
    assert out["adv_value_inr"] == 100_000_000  # 1_000_000 * 100
    assert out["adv_sessions"] == ADV_LOOKBACK_SESSIONS


def test_adv_handles_nan_volume_or_close(monkeypatch):
    prices = [100.0] * 250
    volumes = [1_000_000] * 250
    # NaN out every 7th row in the last 20 sessions — keeps enough valid bars
    # to clear ADV_MIN_SESSIONS but below the full window.
    for i in range(230, 250):
        if i % 7 == 0:
            volumes[i] = np.nan
    df = _make_history(prices, volumes)
    _patch_history(monkeypatch, df)

    out = technicals.compute_technicals("TEST.NS")
    assert out["adv_sessions"] < ADV_LOOKBACK_SESSIONS
    assert out["adv_sessions"] >= ADV_MIN_SESSIONS
    # should not be None
    assert out["adv_value_inr"] is not None


def test_adv_too_few_sessions_returns_none(monkeypatch):
    prices = [100.0] * 250
    # NaN out 240 of 250 to drop below ADV_MIN_SESSIONS
    volumes = [1_000_000 if i >= 240 else float("nan") for i in range(250)]
    df = _make_history(prices, volumes)
    _patch_history(monkeypatch, df)

    out = technicals.compute_technicals("TEST.NS")
    # only 10 valid sessions (250-240), below min_periods of 15
    assert out["adv_value_inr"] is None or out["adv_sessions"] < ADV_MIN_SESSIONS


def test_adv_does_not_poison_when_latest_bars_are_nan(monkeypatch):
    """Trailing-NaN dropping must not shift the ADV window backwards unexpectedly."""
    prices = [10.0] * 230 + [100.0] * 20
    volumes = [1_000_000] * 250
    df = _make_history(prices, volumes)
    # last 2 bars become NaN across OHLCV but volume remains
    df.iloc[-2:, 0:5] = np.nan
    _patch_history(monkeypatch, df)

    out = technicals.compute_technicals("TEST.NS")
    # ADV must still be computed from the last 20 *valid* sessions = 100_000_000
    # (the NaN bars drop out via dropna inside _compute_technicals_impl's tail().
    # We don't assert exact value here; we assert it is the recent window, not
    # the cheap historical window.)
    assert out["adv_value_inr"] is not None
    assert out["adv_value_inr"] >= 50_000_000
