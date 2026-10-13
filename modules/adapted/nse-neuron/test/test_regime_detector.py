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


"""Tests for utils/regime_detector.py - rule-based BULL/BEAR/SIDEWAYS logic."""
import pandas as pd
import pytest
from utils.regime_detector import (
    _classify_trend,
    apply_regime_confidence,
    detect_regime,
    regime_summary_line,
)

import config

# ── _classify_trend ───────────────────────────────────────────────────────────


def test_classify_trend_bull():
    assert _classify_trend(close_last=200, sma_fast_last=180, sma_slow_last=150) == "BULL"


def test_classify_trend_bear():
    assert _classify_trend(close_last=100, sma_fast_last=120, sma_slow_last=150) == "BEAR"


def test_classify_trend_sideways_inside_tolerance():
    # 1% away from the slow SMA -> inside the 3% tolerance band
    assert _classify_trend(close_last=101, sma_fast_last=120, sma_slow_last=100) == "SIDEWAYS"


def test_classify_trend_ambiguous_cross_is_sideways():
    # close far above slow SMA but fast SMA below it -> ambiguous
    assert _classify_trend(close_last=200, sma_fast_last=140, sma_slow_last=150) == "SIDEWAYS"


# ── detect_regime ─────────────────────────────────────────────────────────────


def test_detect_regime_insufficient_data_falls_back(price_df_factory):
    df = price_df_factory([100.0] * 50)
    out = detect_regime(df)
    assert out["regime"] == "UNKNOWN"
    assert out["sufficient_data"] is False
    assert out["recommended_model"] == "LSTM"
    assert out["rows"] == 50
    assert out["sma_fast"] is None and out["sma_slow"] is None


def test_detect_regime_never_raises_on_empty_frame():
    out = detect_regime(pd.DataFrame({"close": []}))
    assert out["sufficient_data"] is False


def test_detect_regime_bull(bull_df):
    out = detect_regime(bull_df)
    assert out["regime"] == "BULL"
    assert out["sufficient_data"] is True
    assert out["sma_fast"] > out["sma_slow"]
    assert out["recommended_model"] == config.REGIME_MODEL_MAP["BULL"]


def test_detect_regime_bear(bear_df):
    out = detect_regime(bear_df)
    assert out["regime"] == "BEAR"
    assert out["sma_fast"] < out["sma_slow"]
    assert out["recommended_model"] == config.REGIME_MODEL_MAP["BEAR"]


def test_detect_regime_sideways(sideways_df):
    out = detect_regime(sideways_df)
    assert out["regime"] == "SIDEWAYS"
    assert out["recommended_model"] == config.REGIME_MODEL_MAP["SIDEWAYS"]


def test_detect_regime_result_is_json_serialisable(bull_df):
    import json

    json.dumps(detect_regime(bull_df))  # must not raise


def test_detect_regime_handles_string_closes(bull_df):
    bull_df["close"] = bull_df["close"].astype(str)
    assert detect_regime(bull_df)["regime"] == "BULL"


# ── apply_regime_confidence ───────────────────────────────────────────────────


def _sig(label, confidence):
    return {"label": label, "confidence": confidence}


BULL = {"regime": "BULL", "sufficient_data": True}
BEAR = {"regime": "BEAR", "sufficient_data": True}
FLAT = {"regime": "SIDEWAYS", "sufficient_data": True}


def test_bull_boosts_buy():
    out = apply_regime_confidence([_sig("BUY", 60.0)], BULL)[0]
    assert out["confidence"] == pytest.approx(60 + config.REGIME_CONFIDENCE_BOOST)
    assert out["regime_adjusted"] is True
    assert out["confidence_orig"] == pytest.approx(60.0)


def test_bull_penalises_sell():
    out = apply_regime_confidence([_sig("SELL", 60.0)], BULL)[0]
    assert out["confidence"] == pytest.approx(60 - config.REGIME_CONFIDENCE_PENALTY)
    assert out["regime_adjusted"] is True


def test_bear_boosts_sell():
    out = apply_regime_confidence([_sig("SELL", 40.0)], BEAR)[0]
    assert out["confidence"] == pytest.approx(40 + config.REGIME_CONFIDENCE_BOOST)


def test_bear_penalises_buy():
    out = apply_regime_confidence([_sig("BUY", 40.0)], BEAR)[0]
    assert out["confidence"] == pytest.approx(40 - config.REGIME_CONFIDENCE_PENALTY)


def test_hold_is_never_adjusted():
    out = apply_regime_confidence([_sig("HOLD", 55.0)], BULL)[0]
    assert out["confidence"] == pytest.approx(55.0)
    assert out["regime_adjusted"] is False


def test_sideways_leaves_confidence_unchanged():
    for label in ("BUY", "SELL", "HOLD"):
        out = apply_regime_confidence([_sig(label, 55.0)], FLAT)[0]
        assert out["confidence"] == pytest.approx(55.0)
        assert out["regime_adjusted"] is False


def test_confidence_is_clamped_to_100():
    out = apply_regime_confidence([_sig("BUY", 99.0)], BULL)[0]
    assert out["confidence"] <= 100.0


def test_confidence_is_clamped_to_zero():
    out = apply_regime_confidence([_sig("BUY", 1.0)], BEAR)[0]
    assert out["confidence"] >= 0.0


def test_insufficient_data_passes_signals_through_untouched():
    signals = [_sig("BUY", 60.0)]
    assert apply_regime_confidence(signals, {"regime": "BULL", "sufficient_data": False}) is signals


def test_empty_signal_list_passes_through():
    assert apply_regime_confidence([], BULL) == []


def test_delta_string_is_signed():
    boosted = apply_regime_confidence([_sig("BUY", 50.0)], BULL)[0]
    penalised = apply_regime_confidence([_sig("SELL", 50.0)], BULL)[0]
    assert boosted["confidence_delta"].startswith("+")
    assert penalised["confidence_delta"].startswith("-")


def test_original_signal_keys_are_preserved():
    out = apply_regime_confidence([{"label": "BUY", "confidence": 60.0, "day": 3}], BULL)[0]
    assert out["day"] == 3


# ── regime_summary_line ───────────────────────────────────────────────────────


def test_summary_line_for_insufficient_data():
    line = regime_summary_line({"sufficient_data": False})
    assert "insufficient data" in line.lower()


def test_summary_line_includes_regime_and_model(bull_df):
    line = regime_summary_line(detect_regime(bull_df))
    assert "BULL" in line
    assert config.REGIME_MODEL_MAP["BULL"] in line
