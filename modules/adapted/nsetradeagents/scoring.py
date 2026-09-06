from app.core.config import settings

DIMENSION_SCORES = {
    "entry_timing": {"IDEAL": 30, "ACCEPTABLE": 18, "POOR": 0},
    "momentum_quality": {"STRONG": 25, "MODERATE": 15, "WEAK": 0},
    "risk_reward_view": {"FAVORABLE": 20, "NEUTRAL": 12, "UNFAVORABLE": 0},
    "market_regime": {"FAVORABLE": 25, "NEUTRAL": 15, "HOSTILE": 0},
}


def _rules_entry_timing(ind: dict) -> str:
    """Grade today as an entry point: IDEAL, ACCEPTABLE or POOR.

    Any hard disqualifier (a large day move, thin volume, or price sitting on
    a round number) forces POOR. Otherwise the band comes from how many of
    the four ideal conditions hold.
    """
    rsi = ind.get("rsi", 50)
    macd_hist = ind.get("macd_hist", 0)
    macd_hist_prev = ind.get("macd_hist_prev", 0)
    volume_ratio = ind.get("volume_ratio", 0)
    day_change = ind.get("day_change_pct", 0)
    current_price = ind.get("current_price", 0)

    if day_change > 5:
        return "POOR"
    if volume_ratio < 1.5:
        return "POOR"
    for level in settings.round_number_levels:
        if (
            current_price > 0
            and abs(current_price - level) / level < settings.resistance_proximity_pct
        ):
            return "POOR"

    conditions = [
        macd_hist > macd_hist_prev,
        rsi < 67,
        volume_ratio > 2,
        day_change < 3,
    ]
    met = sum(conditions)
    if met == 4:
        return "IDEAL"
    if met >= 3:
        return "ACCEPTABLE"
    return "POOR"


def _rules_momentum_quality(ind: dict, entry_timing: str) -> str:
    """Grade whether momentum is building or fading: STRONG, MODERATE or WEAK.

    STRONG also requires an IDEAL entry: textbook momentum arrived at too
    late is downgraded to MODERATE.
    """
    rsi = ind.get("rsi", 50)
    macd_hist_trend = ind.get("macd_hist_trend", "mixed")
    momentum_5d = ind.get("momentum_5d", 0)

    if rsi > settings.rsi_max or rsi < settings.rsi_min:
        return "WEAK"
    if macd_hist_trend == "contracting":
        return "WEAK"
    if momentum_5d > 10 or momentum_5d < 1:
        return "WEAK"
    if 62 <= rsi <= 67 and macd_hist_trend == "expanding" and 3 <= momentum_5d <= 8:
        return "STRONG" if entry_timing == "IDEAL" else "MODERATE"
    return "MODERATE"


def _rules_risk_reward(risk: dict, current_price: float) -> str:
    """Grade reward against risk: FAVORABLE, NEUTRAL or UNFAVORABLE.

    Falls back to NEUTRAL when the stop or target is missing or nonsensical.
    """
    stop_loss = risk.get("stop_loss", 0)
    take_profit = risk.get("take_profit", 0)
    if not stop_loss or not take_profit or current_price <= stop_loss:
        return "NEUTRAL"
    rr = (take_profit - current_price) / (current_price - stop_loss)
    if rr >= 2.5:
        return "FAVORABLE"
    if rr >= 1.5:
        return "NEUTRAL"
    return "UNFAVORABLE"


def _rules_market_regime(market_context: dict | None) -> str:
    """Grade the market backdrop: FAVORABLE, NEUTRAL or HOSTILE.

    High VIX or a falling Nifty over 20 days is an outright disqualifier.
    Otherwise the band comes from a count of softer warnings, where a stock
    rising while its sector falls cancels the weak-sector warning and can
    earn back the top band.
    """
    ctx = market_context or {}
    india_vix = ctx.get("india_vix") or 0
    nifty_day = ctx.get("nifty_day_pct") or 0
    nifty_10d = ctx.get("nifty_10d_pct") or 0
    nifty_20d = ctx.get("nifty_20d_pct") or 0
    sector_day = ctx.get("sector_day_pct") or 0

    relative_strength = (
        "relative strength" in (ctx.get("divergence_note") or "").lower()
    )

    if india_vix > settings.vix_high_fear_level:
        return "HOSTILE"
    if nifty_20d < settings.nifty_20d_decline_threshold:
        return "HOSTILE"

    warnings = sum(
        [
            india_vix > settings.vix_medium_fear_level,
            nifty_10d < settings.nifty_10d_decline_threshold,
            nifty_day < -1.0,
            sector_day < -0.5
            and not relative_strength,  # A weak sector is not a warning for a stock that is beating it
        ]
    )

    if warnings >= 3:
        return "HOSTILE"
    if warnings == 0 or (relative_strength and warnings == 1):
        return "FAVORABLE"
    return "NEUTRAL"


def compute_rules_confidence(
    technical: dict, risk: dict, market_context: dict | None = None
) -> dict:
    """Score a setup 0-100 across four banded dimensions.

    Returns the score plus the band each dimension landed in, so callers can
    record why a candidate scored what it did, not just what it scored"""
    ind = technical.get("indicators") or {}
    current_price = ind.get("current_price", 0)

    entry_timing = _rules_entry_timing(ind)
    bands = {
        "entry_timing": entry_timing,
        "momentum_quality": _rules_momentum_quality(ind, entry_timing),
        "risk_reward_view": _rules_risk_reward(risk, current_price),
        "market_regime": _rules_market_regime(market_context),
    }

    score = sum(DIMENSION_SCORES[dim][band] for dim, band in bands.items())
    return {"score": score, **bands}
