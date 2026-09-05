import numpy as np
import pandas as pd
from app.utils.indicators import compute_indicators

EXPECTED_KEYS = [
    "current_price", "day_change_pct", "sma50", "sma200", "atr_pct",
    "avg_vol", "today_vol", "volume_ratio", "avg_daily_value",
    "rsi", "macd", "macd_signal", "macd_hist", "macd_hist_prev",
    "macd_hist_trend", "bb_upper", "bb_mid", "bb_lower",
    "momentum_5d", "momentum_20d",
]


def make_df(n_rows=250, seed=42):
    rng = np.random.default_rng(seed)
    prices = 500.0 + np.cumsum(rng.normal(0, 2, n_rows))
    prices = np.maximum(prices, 10.0)
    return pd.DataFrame({
        "Close": prices,
        "High": prices * 1.01,
        "Low": prices * 0.99,
        "Volume": rng.integers(100_000, 500_000, n_rows).astype(float),
    })


def test_all_keys_present():
    ind = compute_indicators(make_df())
    for key in EXPECTED_KEYS:
        assert key in ind, f"Missing key: {key}"


def test_sma200_none_when_insufficient_rows():
    ind = compute_indicators(make_df(n_rows=150))
    assert ind["sma200"] is None


def test_sma200_present_with_sufficient_rows():
    ind = compute_indicators(make_df(n_rows=250))
    assert ind["sma200"] is not None
    assert ind["sma200"] > 0


def test_rsi_in_valid_range():
    ind = compute_indicators(make_df())
    assert 0 <= ind["rsi"] <= 100


def test_bollinger_band_order():
    ind = compute_indicators(make_df())
    assert ind["bb_lower"] < ind["bb_mid"] < ind["bb_upper"]


def test_macd_hist_trend_valid_value():
    ind = compute_indicators(make_df())
    assert ind["macd_hist_trend"] in ("expanding", "contracting", "mixed")


def test_current_price_matches_last_close():
    df = make_df()
    ind = compute_indicators(df)
    assert ind["current_price"] == round(float(df["Close"].iloc[-1]), 2)


def test_volume_ratio_non_negative():
    ind = compute_indicators(make_df())
    assert ind["volume_ratio"] >= 0


def test_atr_pct_positive():
    ind = compute_indicators(make_df())
    assert ind["atr_pct"] > 0


def test_sma50_less_than_price_in_uptrend():
    # Monotonically rising prices — SMA50 should be below current price
    prices = np.linspace(100, 600, 250)
    df = pd.DataFrame({
        "Close": prices,
        "High": prices * 1.01,
        "Low": prices * 0.99,
        "Volume": np.ones(250) * 200_000,
    })
    ind = compute_indicators(df)
    assert ind["current_price"] > ind["sma50"]
    assert ind["current_price"] > ind["sma200"]
