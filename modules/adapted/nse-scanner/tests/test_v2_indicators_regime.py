from __future__ import annotations

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
import pandas as pd
import pytest
from v2.indicators import atr, fixed_hybrid_hull_signals, hma, hybrid_hull, relative_strength_return, wma
from v2.regime import classify_market_regime, rank_relative_strength


def test_wma_matches_manual_calculation():
    values = pd.Series([1.0, 2.0, 3.0, 4.0])
    result = wma(values, 3)
    assert result.iloc[-1] == pytest.approx((2 * 1 + 3 * 2 + 4 * 3) / 6)


def test_hma_tracks_linear_series_after_warmup():
    values = pd.Series(np.arange(1.0, 121.0))
    result = hma(values, 20)
    assert result.notna().sum() > 80
    assert result.iloc[-1] > result.iloc[-2]
    assert abs(result.iloc[-1] - values.iloc[-1]) < 5.0


def test_atr_uses_true_range_gap():
    frame = pd.DataFrame({"high": [11.0, 16.0], "low": [9.0, 14.0], "close": [10.0, 15.0]})
    result = atr(frame, length=1)
    assert result.iloc[0] == pytest.approx(2.0)
    assert result.iloc[1] == pytest.approx(6.0)


def test_hybrid_hull_returns_positive_state_in_strong_uptrend():
    close = pd.Series(np.linspace(100.0, 200.0, 160))
    frame = pd.DataFrame({"close": close})
    result = hybrid_hull(frame, fast=21, slow=55)
    assert result.iloc[-1]["hybrid_hull_state"] == 1


def test_fixed_hybrid_hull_uses_agreed_parameters_and_confirms_uptrend():
    dates = pd.bdate_range("2025-01-01", periods=300)
    close = np.linspace(100.0, 220.0, len(dates))
    frame = pd.DataFrame(
        {
            "trade_date": dates,
            "open": close - 0.5,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
        }
    )
    result = fixed_hybrid_hull_signals(frame)
    assert result["daily_bullish"]
    assert result["weekly_bullish"]
    assert result["kama_rising"]
    assert result["trail_stop"] == pytest.approx(result["hull55"] - 3.5 * result["atr14"], abs=0.02)


def test_relative_strength_return_is_excess_return():
    stock = pd.Series([100.0, 120.0])
    benchmark = pd.Series([100.0, 110.0])
    result = relative_strength_return(stock, benchmark, lookback=1)
    assert result.iloc[-1] == pytest.approx(0.10)


def _regime_fixture(up: bool = True):
    index = pd.bdate_range("2026-01-01", periods=100)
    close = np.linspace(100.0, 150.0, 100) if up else np.linspace(150.0, 100.0, 100)
    benchmark = pd.DataFrame({"close": close}, index=index)
    breadth = pd.DataFrame(
        {
            "pct_above_50dma": 70.0 if up else 30.0,
            "pct_above_200dma": 60.0 if up else 25.0,
        },
        index=index,
    )
    return benchmark, breadth


def test_market_regime_bull_is_date_explicit():
    benchmark, breadth = _regime_fixture(True)
    result = classify_market_regime(benchmark, breadth, hma_length=20)
    assert result.state == "BULL"
    assert result.as_of_date == benchmark.index[-1].date().isoformat()
    assert result.score == 4


def test_market_regime_bear():
    benchmark, breadth = _regime_fixture(False)
    result = classify_market_regime(benchmark, breadth, hma_length=20)
    assert result.state == "BEAR"


def test_rs_rank_has_no_static_bias():
    ranked = rank_relative_strength({"IT": 0.08, "BANK": 0.12, "AUTO": 0.04})
    assert ranked.iloc[0]["symbol"] == "BANK"
    assert list(ranked["rs_rank"]) == [1, 2, 3]
