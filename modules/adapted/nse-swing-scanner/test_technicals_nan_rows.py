"""Tests for the trailing-NaN-row drop in compute_technicals.

yfinance sometimes returns the most recent session with all-NaN OHLCV (e.g.
incomplete feed, intraday session still settling). The scanner must use the
last *complete* session as the "current" reference, otherwise drawdown and
EMA-distance gates fail for nearly every stock.
"""
import numpy as np
import pandas as pd
import pytest

import technicals


def _make_history_with_trailing_nan(n: int = 250, trailing_nan_bars: int = 1) -> pd.DataFrame:
    """Build a synthetic yfinance-style DataFrame whose last `trailing_nan_bars`
    rows have NaN OHLCV but valid Volume (matches yfinance's typical behavior
    on an incomplete feed)."""
    dates = pd.date_range("2025-01-01", periods=n, freq="B")
    # Synthetic uptrend with normal noise
    np.random.seed(42)
    prices = 100 + np.cumsum(np.random.normal(0, 1, n))
    df = pd.DataFrame({
        "Open": prices + np.random.normal(0, 0.5, n),
        "High": prices + np.abs(np.random.normal(0, 1, n)),
        "Low": prices - np.abs(np.random.normal(0, 1, n)),
        "Close": prices,
        "Volume": np.random.randint(1_000_000, 5_000_000, n).astype(float),
    }, index=dates)
    # Make last `trailing_nan_bars` rows NaN across OHLCV but keep volume non-NaN.
    # Note: iloc[-0:] is the same as iloc[0:] (all rows), so guard against 0.
    if trailing_nan_bars > 0:
        df.iloc[-trailing_nan_bars:, 0:5] = np.nan
    return df


def _patched_history(monkeypatch, df: pd.DataFrame):
    """Patch yfinance Ticker.history to return our synthetic DataFrame."""
    class _FakeTicker:
        def history(self, period=None, auto_adjust=None):
            return df
    monkeypatch.setattr(technicals.yf, "Ticker", lambda symbol: _FakeTicker())


def test_technicals_drops_trailing_nan_row(monkeypatch):
    """When the last bar is all-NaN OHLCV, current_price must use the previous valid bar."""
    df = _make_history_with_trailing_nan(n=250, trailing_nan_bars=1)
    expected_price = float(df["Close"].iloc[-2])  # the last valid close
    _patched_history(monkeypatch, df)

    result = technicals.compute_technicals("RELIANCE.NS")

    assert result.get("error") is None, f"unexpected error: {result.get('error')}"
    assert result["current_price"] == round(expected_price, 2)


def test_technicals_drops_multiple_trailing_nan_rows(monkeypatch):
    """When the last 3 bars are NaN, current_price must use the bar before them."""
    df = _make_history_with_trailing_nan(n=250, trailing_nan_bars=3)
    expected_price = float(df["Close"].iloc[-4])  # 4th-from-last
    _patched_history(monkeypatch, df)

    result = technicals.compute_technicals("RELIANCE.NS")

    assert result.get("error") is None
    assert result["current_price"] == round(expected_price, 2)


def test_technicals_does_not_drop_internal_nan_rows(monkeypatch):
    """A single internal NaN (e.g. a holiday or half-day) must not be dropped."""
    df = _make_history_with_trailing_nan(n=250, trailing_nan_bars=0)
    # Introduce a single NaN in the middle
    df.iloc[100, 0:5] = np.nan
    _patched_history(monkeypatch, df)

    result = technicals.compute_technicals("RELIANCE.NS")

    assert result.get("error") is None
    # Last bar is valid, so current_price comes from the last bar
    assert result["current_price"] == round(float(df["Close"].iloc[-1]), 2)


def test_technicals_returns_error_when_too_many_nan_bars(monkeypatch):
    """If 30+ trailing bars are NaN (e.g. a delisted/paused stock), error out."""
    df = _make_history_with_trailing_nan(n=250, trailing_nan_bars=50)
    _patched_history(monkeypatch, df)

    result = technicals.compute_technicals("RELIANCE.NS")

    assert result.get("error") is not None
    assert "insufficient_valid_history" in result["error"]


def test_nifty50_context_drops_trailing_nan(monkeypatch):
    """The Nifty 50 context must also tolerate a trailing NaN bar."""
    df = _make_history_with_trailing_nan(n=250, trailing_nan_bars=1)
    expected_last = float(df["Close"].iloc[-2])
    _patched_history(monkeypatch, df)

    result = technicals.compute_nifty50_context()

    assert result.get("error") is None, f"unexpected error: {result.get('error')}"
    assert result["index_last"] == round(expected_last, 2)