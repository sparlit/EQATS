import pytest
from app.utils.scoring import (
    _rules_entry_timing,
    _rules_momentum_quality,
    _rules_risk_reward,
)

RSI_MIN = 55.0
RSI_MAX = 70.0


@pytest.fixture(autouse=True)
def patch_scoring_settings(monkeypatch):
    monkeypatch.setattr("app.utils.scoring.settings.rsi_min", RSI_MIN)
    monkeypatch.setattr("app.utils.scoring.settings.rsi_max", RSI_MAX)
    monkeypatch.setattr("app.utils.scoring.settings.vix_high_fear_level", 22.0)
    monkeypatch.setattr("app.utils.scoring.settings.vix_medium_fear_level", 18.0)
    monkeypatch.setattr("app.utils.scoring.settings.vix_high_fear_penalty", 20)
    monkeypatch.setattr("app.utils.scoring.settings.vix_medium_fear_penalty", 10)
    monkeypatch.setattr("app.utils.scoring.settings.nifty_20d_decline_threshold", -3.0)
    monkeypatch.setattr("app.utils.scoring.settings.nifty_10d_decline_threshold", -2.0)
    monkeypatch.setattr(
        "app.utils.scoring.settings.round_number_levels",
        [500.0, 1000.0, 2000.0, 5000.0],
    )
    monkeypatch.setattr("app.utils.scoring.settings.resistance_proximity_pct", 0.02)


GOOD_TIMING_IND = {
    "rsi": 62.0,
    "macd_hist": 0.5,
    "macd_hist_prev": 0.3,
    "volume_ratio": 2.5,
    "day_change_pct": 1.5,
    "current_price": 750.0,
}


# ── _rules_entry_timing ───────────────────────────────────────────────────────


def test_entry_timing_ideal():
    assert _rules_entry_timing(GOOD_TIMING_IND) == "IDEAL"


def test_entry_timing_poor_day_change_too_high():
    assert _rules_entry_timing({**GOOD_TIMING_IND, "day_change_pct": 6.0}) == "POOR"


def test_entry_timing_poor_low_volume():
    assert _rules_entry_timing({**GOOD_TIMING_IND, "volume_ratio": 1.0}) == "POOR"


def test_entry_timing_poor_near_round_number():
    # 998 is within 2% of 1000
    assert _rules_entry_timing({**GOOD_TIMING_IND, "current_price": 998.0}) == "POOR"


def test_entry_timing_acceptable_three_of_four_conditions():
    # rsi 68 fails the rsi < 67 condition → 3/4 met → ACCEPTABLE
    assert _rules_entry_timing({**GOOD_TIMING_IND, "rsi": 68.0}) == "ACCEPTABLE"


def test_entry_timing_poor_macd_not_rising():
    # Fail macd rising (hist < prev) AND rsi < 67 → only 2/4 conditions met → POOR
    ind = {**GOOD_TIMING_IND, "macd_hist": 0.2, "macd_hist_prev": 0.5, "rsi": 68.0}
    assert _rules_entry_timing(ind) == "POOR"


# ── _rules_momentum_quality ───────────────────────────────────────────────────


STRONG_MOMENTUM_IND = {"rsi": 64.0, "macd_hist_trend": "expanding", "momentum_5d": 5.0}


def test_momentum_quality_strong():
    # STRONG requires an IDEAL entry — see the late-entry test below
    assert _rules_momentum_quality(STRONG_MOMENTUM_IND, "IDEAL") == "STRONG"


def test_momentum_quality_strong_but_late_entry_is_downgraded():
    # Textbook momentum you are late to is not STRONG. Replaces the old flat -15
    # penalty for STRONG momentum on a non-IDEAL entry.
    assert _rules_momentum_quality(STRONG_MOMENTUM_IND, "ACCEPTABLE") == "MODERATE"
    assert _rules_momentum_quality(STRONG_MOMENTUM_IND, "POOR") == "MODERATE"


def test_momentum_quality_weak_rsi_too_high():
    ind = {"rsi": 72.0, "macd_hist_trend": "expanding", "momentum_5d": 5.0}
    assert _rules_momentum_quality(ind, "IDEAL") == "WEAK"


def test_momentum_quality_weak_rsi_too_low():
    ind = {"rsi": 50.0, "macd_hist_trend": "expanding", "momentum_5d": 5.0}
    assert _rules_momentum_quality(ind, "IDEAL") == "WEAK"


def test_momentum_quality_weak_contracting_macd():
    ind = {"rsi": 63.0, "macd_hist_trend": "contracting", "momentum_5d": 5.0}
    assert _rules_momentum_quality(ind, "IDEAL") == "WEAK"


def test_momentum_quality_weak_momentum_too_high():
    ind = {"rsi": 63.0, "macd_hist_trend": "expanding", "momentum_5d": 12.0}
    assert _rules_momentum_quality(ind, "IDEAL") == "WEAK"


def test_momentum_quality_weak_momentum_too_low():
    ind = {"rsi": 63.0, "macd_hist_trend": "expanding", "momentum_5d": 0.5}
    assert _rules_momentum_quality(ind, "IDEAL") == "WEAK"


def test_momentum_quality_moderate():
    ind = {"rsi": 60.0, "macd_hist_trend": "mixed", "momentum_5d": 4.0}
    assert _rules_momentum_quality(ind, "IDEAL") == "MODERATE"


# ── _rules_risk_reward ────────────────────────────────────────────────────────


def test_risk_reward_favorable():
    # R:R = (650 - 500) / (500 - 450) = 3.0, >= 2.5
    assert (
        _rules_risk_reward({"stop_loss": 450, "take_profit": 650}, 500) == "FAVORABLE"
    )


def test_risk_reward_neutral():
    # R:R = (580 - 500) / (500 - 450) = 1.6
    assert _rules_risk_reward({"stop_loss": 450, "take_profit": 580}, 500) == "NEUTRAL"


def test_risk_reward_unfavorable():
    # R:R = (540 - 500) / (500 - 450) = 0.8, < 1.5
    assert (
        _rules_risk_reward({"stop_loss": 450, "take_profit": 540}, 500) == "UNFAVORABLE"
    )


def test_risk_reward_missing_stop_loss():
    assert _rules_risk_reward({"take_profit": 650}, 500) == "NEUTRAL"


def test_risk_reward_price_at_or_below_stop():
    # current_price <= stop_loss is an invalid setup
    assert _rules_risk_reward({"stop_loss": 500, "take_profit": 650}, 500) == "NEUTRAL"
