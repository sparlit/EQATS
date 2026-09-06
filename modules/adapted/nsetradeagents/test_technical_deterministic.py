import numpy as np
import pandas as pd
import pytest
from app.agents.technical import _compute_signal, _compute_strength, run_technical_analysis

RSI_MIN = 55.0
RSI_MAX = 70.0


@pytest.fixture(autouse=True)
def patch_technical_settings(monkeypatch):
    monkeypatch.setattr("app.agents.technical.settings.rsi_min", RSI_MIN)
    monkeypatch.setattr("app.agents.technical.settings.rsi_max", RSI_MAX)


# ── _compute_signal ───────────────────────────────────────────────────────────

BULLISH_IND = {"current_price": 500.0, "sma50": 480.0, "sma200": 400.0, "rsi": 62.0}


def test_compute_signal_buy():
    assert _compute_signal(BULLISH_IND) == "BUY"


def test_compute_signal_hold_below_sma200():
    ind = {**BULLISH_IND, "current_price": 390.0}
    assert _compute_signal(ind) == "HOLD"


def test_compute_signal_hold_below_sma50():
    ind = {**BULLISH_IND, "current_price": 470.0}
    assert _compute_signal(ind) == "HOLD"


def test_compute_signal_sell_rsi_too_high():
    ind = {**BULLISH_IND, "rsi": 75.0}
    assert _compute_signal(ind) == "SELL"


def test_compute_signal_hold_rsi_too_low():
    ind = {**BULLISH_IND, "rsi": 40.0}
    assert _compute_signal(ind) == "HOLD"


def test_compute_signal_hold_no_sma200():
    ind = {"current_price": 500.0, "sma50": 480.0, "sma200": None, "rsi": 62.0}
    assert _compute_signal(ind) == "BUY"


# ── _compute_strength ─────────────────────────────────────────────────────────

def test_compute_strength_maximum():
    # RSI in sweet spot (62-67) → 30, expanding → 25, vol ≥ 2 → 25, momentum ≤ 8 → 20
    ind = {"rsi": 64.0, "macd_hist_trend": "expanding", "volume_ratio": 2.5, "momentum_5d": 5.0}
    assert _compute_strength(ind) == 100


def test_compute_strength_minimum():
    # RSI outside both ranges → 5, contracting → 0, vol < 1.5 → 0, momentum > 10 → 0
    ind = {"rsi": 80.0, "macd_hist_trend": "contracting", "volume_ratio": 0.5, "momentum_5d": 15.0}
    assert _compute_strength(ind) == 5


def test_compute_strength_rsi_broad_zone():
    # RSI 55-70 but not sweet spot (62-67) → 20; expanding → 25; vol ≥ 2 → 25; momentum ≤ 8 → 20
    ind = {"rsi": 58.0, "macd_hist_trend": "expanding", "volume_ratio": 2.0, "momentum_5d": 5.0}
    assert _compute_strength(ind) == 90  # 20+25+25+20


def test_compute_strength_mixed_macd():
    ind = {"rsi": 64.0, "macd_hist_trend": "mixed", "volume_ratio": 2.0, "momentum_5d": 5.0}
    assert _compute_strength(ind) == 90  # 30+15+25+20


def test_compute_strength_capped_at_100():
    ind = {"rsi": 64.0, "macd_hist_trend": "expanding", "volume_ratio": 3.0, "momentum_5d": 2.0}
    assert _compute_strength(ind) == 100


# ── run_technical_analysis (deterministic path) ───────────────────────────────

def make_ticker_df(n_rows=250, seed=7):
    rng = np.random.default_rng(seed)
    prices = 500.0 + np.cumsum(rng.normal(0.2, 1.5, n_rows))
    prices = np.maximum(prices, 10.0)
    return pd.DataFrame({
        "Close": prices,
        "High": prices * 1.01,
        "Low": prices * 0.99,
        "Volume": rng.integers(100_000, 500_000, n_rows).astype(float),
    })


def test_run_technical_returns_expected_keys():
    df = make_ticker_df()
    result = run_technical_analysis("TEST.NS", ticker_df=df)
    assert "signal" in result
    assert "strength" in result
    assert "summary" in result
    assert "indicators" in result


def test_run_technical_signal_is_valid():
    df = make_ticker_df()
    result = run_technical_analysis("TEST.NS", ticker_df=df)
    assert result["signal"] in ("BUY", "HOLD", "SELL")


def test_run_technical_strength_in_range():
    df = make_ticker_df()
    result = run_technical_analysis("TEST.NS", ticker_df=df)
    assert 0 <= result["strength"] <= 100


def test_run_technical_insufficient_data_returns_hold():
    df = make_ticker_df(n_rows=30)
    result = run_technical_analysis("TEST.NS", ticker_df=df)
    assert result["signal"] == "HOLD"
    assert result["strength"] == 0
