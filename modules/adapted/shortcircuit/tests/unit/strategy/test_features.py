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


"""
Tests for strategy/features.py — the stateless math library.

These functions feed every gate in the pipeline, so an error here is silent and
systemic: a wrong VWAP does not raise, it just produces a slightly wrong signal
forever. They are also completely pure, so they are testable with no mocking at
all, which makes them the highest value-per-line tests in the repository.
"""
import numpy as np
import pandas as pd
import pytest
from shortcircuit.strategy import features as F

# enrich_dataframe / VWAP


def test_vwap_of_constant_price_is_that_price(flat_candles):
    F.enrich_dataframe(flat_candles)
    assert flat_candles["vwap"].iloc[-1] == pytest.approx(100.0)


def test_vwap_lies_within_the_price_range(sample_candles):
    F.enrich_dataframe(sample_candles)
    vwap = sample_candles["vwap"].iloc[-1]
    assert sample_candles["low"].min() <= vwap <= sample_candles["high"].max()


def test_vwap_is_volume_weighted_not_a_simple_mean():
    """A heavy bar must pull VWAP toward its own typical price."""
    df = pd.DataFrame(
        {
            "open": [100.0, 200.0],
            "high": [100.0, 200.0],
            "low": [100.0, 200.0],
            "close": [100.0, 200.0],
            "volume": [1, 999],
        }
    )
    F.enrich_dataframe(df)
    assert df["vwap"].iloc[-1] > 199.0, "heavy second bar should dominate"


def test_enrich_adds_vwap_column_in_place(flat_candles):
    assert "vwap" not in flat_candles.columns
    F.enrich_dataframe(flat_candles)
    assert "vwap" in flat_candles.columns


# compute_vwap_sd


def test_vwap_sd_returns_zero_without_a_vwap_column(sample_candles):
    assert F.compute_vwap_sd(sample_candles) == 0.0


def test_vwap_sd_returns_zero_when_series_shorter_than_window(flat_candles):
    F.enrich_dataframe(flat_candles)
    assert F.compute_vwap_sd(flat_candles.iloc[:5], window=20) == 0.0


def test_vwap_sd_zero_when_price_never_deviates(flat_candles):
    """Zero dispersion must yield 0.0, not a division-by-zero or inf."""
    F.enrich_dataframe(flat_candles)
    sd = F.compute_vwap_sd(flat_candles)
    assert sd == 0.0
    assert np.isfinite(sd)


def test_vwap_sd_is_positive_when_price_is_above_vwap(trending_candles):
    F.enrich_dataframe(trending_candles)
    assert F.compute_vwap_sd(trending_candles) > 0


# compute_vwap_slope


def test_slope_of_flat_series_is_zero(flat_candles):
    slope, status = F.compute_vwap_slope(flat_candles, window=30)
    assert slope == pytest.approx(0.0, abs=1e-9)
    assert status == "FLAT"


def test_slope_of_rising_series_is_positive(trending_candles):
    slope, status = F.compute_vwap_slope(trending_candles, window=30)
    assert slope > 0
    assert status == "TRENDING"


def test_slope_reports_insufficient_data_rather_than_guessing(single_bar):
    slope, status = F.compute_vwap_slope(single_bar, window=30)
    assert slope == 0.0
    assert status == "INSUFFICIENT_DATA"


# compute_atr


def test_atr_returns_nan_on_insufficient_data(single_bar):
    """
    The docstring is explicit that ATR must NOT return a sentinel like 1.0,
    because the value feeds stop-loss sizing directly. NaN forces the caller
    to handle it.
    """
    assert np.isnan(F.compute_atr(single_bar))


def test_atr_is_positive_for_a_normal_series(sample_candles):
    atr = F.compute_atr(sample_candles)
    assert np.isfinite(atr) and atr > 0


def test_atr_of_zero_range_bars_is_zero(flat_candles):
    atr = F.compute_atr(flat_candles)
    assert atr == pytest.approx(0.0)


def test_atr_never_returns_a_sentinel_on_malformed_input():
    bad = pd.DataFrame({"high": [], "low": [], "close": []})
    assert np.isnan(F.compute_atr(bad))


# compute_volume_fade_ratio


def test_volume_fade_detects_declining_volume():
    candles = [{"volume": 1000} for _ in range(15)] + [{"volume": 100} for _ in range(3)]
    ratio = F.compute_volume_fade_ratio(candles, lookback=10)
    assert ratio < 0.65, "collapsing volume should register as fading"


def test_volume_fade_detects_expanding_volume():
    candles = [{"volume": 100} for _ in range(15)] + [{"volume": 5000} for _ in range(3)]
    assert F.compute_volume_fade_ratio(candles, lookback=10) > 1.0


def test_volume_fade_neutral_when_insufficient_history():
    assert F.compute_volume_fade_ratio([{"volume": 100}] * 3, lookback=10) == 1.0


def test_volume_fade_neutral_when_prior_window_is_all_zero():
    """Guards a division by zero — must degrade to neutral, not raise."""
    candles = [{"volume": 0} for _ in range(15)] + [{"volume": 50}] * 3
    assert F.compute_volume_fade_ratio(candles, lookback=10) == 1.0


def test_volume_fade_drops_the_forming_bar_by_default():
    """
    The final bar is still forming, so its partial volume would fake a fade.
    Dropping it must change the answer.
    """
    candles = [{"volume": 1000} for _ in range(15)] + [{"volume": 1000}] * 2 + [{"volume": 1}]
    with_forming = F.compute_volume_fade_ratio(candles, lookback=10, drop_forming=False)
    without = F.compute_volume_fade_ratio(candles, lookback=10, drop_forming=True)
    assert without != with_forming


# compute_rsi_divergence


def test_rsi_divergence_false_on_short_series(flat_candles):
    assert F.compute_rsi_divergence(flat_candles.iloc[:5], window=25) is False


def test_rsi_divergence_false_on_a_clean_uptrend(trending_candles):
    """A series making higher highs with rising momentum is not divergent."""
    assert F.compute_rsi_divergence(trending_candles, window=25) is False


def test_rsi_divergence_returns_a_bool_not_a_truthy_value(sample_candles):
    assert isinstance(F.compute_rsi_divergence(sample_candles, window=20), bool)


def test_rsi_divergence_swallows_malformed_input():
    """Documented to fail closed rather than propagate — a gate must not crash the scan."""
    assert F.compute_rsi_divergence(pd.DataFrame({"close": [1, 2]}), window=25) is False


# is_narrowing_highs


def test_narrowing_highs_true_for_a_descending_staircase():
    df = pd.DataFrame(
        {
            "high": [110.0, 108.0, 106.0, 104.0, 102.0],
            "low": [100.0] * 5,
            "close": [101.0] * 5,
            "open": [101.0] * 5,
            "volume": [10] * 5,
        }
    )
    assert F.is_narrowing_highs(df, n=3) is True


def test_narrowing_highs_false_when_highs_are_rising(trending_candles):
    assert F.is_narrowing_highs(trending_candles, n=3) is False


def test_narrowing_highs_false_on_insufficient_bars(single_bar):
    assert F.is_narrowing_highs(single_bar, n=3) is False


# compute_stretch_score


def test_stretch_score_is_zero_at_the_scanner_floor():
    assert F.compute_stretch_score(7.5, 7.5) == 0.0


def test_stretch_score_is_one_at_double_the_floor():
    assert F.compute_stretch_score(15.0, 7.5) == pytest.approx(1.0)


def test_stretch_score_guards_zero_denominator():
    assert F.compute_stretch_score(10.0, 0) == 0.0


# detect_pattern


def test_detect_pattern_returns_normal_for_insufficient_bars(single_bar):
    pattern, vol_z = F.detect_pattern(single_bar)
    assert pattern == "NORMAL" and vol_z == 0.0


def test_detect_pattern_identifies_vah_rejection(sample_candles):
    """Price probed above VAH in the last 3 bars and closed back inside."""
    vah = float(sample_candles["close"].iloc[-1]) + 0.5
    sample_candles.loc[sample_candles.index[-2], "high"] = vah * 1.01
    pattern, _ = F.detect_pattern(sample_candles, vah=vah)
    assert pattern == "VAH_REJECTION"


def test_detect_pattern_returns_a_known_label(sample_candles):
    known = {
        "VAH_REJECTION",
        "BEARISH_ENGULFING",
        "EVENING_STAR",
        "SHOOTING_STAR",
        "ABSORPTION_DOJI",
        "MOMENTUM_BREAKDOWN",
        "VOLUME_TRAP",
        "NORMAL",
    }
    pattern, _ = F.detect_pattern(sample_candles)
    assert pattern in known
