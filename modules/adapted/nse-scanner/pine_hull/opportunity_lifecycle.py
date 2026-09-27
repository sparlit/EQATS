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


"""Independent Pine Hull opportunity lifecycle helpers."""

import pandas as pd


def weekly_transition(weekly21: pd.Series, weekly51: pd.Series) -> tuple[str, dict[str, float]]:
    if len(weekly21) < 2 or len(weekly51) < 2:
        return "NEUTRAL", {}
    values = [weekly21.iloc[-1], weekly21.iloc[-2], weekly51.iloc[-1], weekly51.iloc[-2]]
    if any(pd.isna(value) for value in values):
        return "NEUTRAL", {}
    gap = float(weekly21.iloc[-1] - weekly51.iloc[-1])
    prior_gap = float(weekly21.iloc[-2] - weekly51.iloc[-2])
    fast_slope = float(weekly21.iloc[-1] - weekly21.iloc[-2])
    slow_slope = float(weekly51.iloc[-1] - weekly51.iloc[-2])
    if gap > 0 and fast_slope >= 0:
        state = "BULLISH"
    elif (gap < 0 and gap > prior_gap and fast_slope > 0) or (gap >= 0 and fast_slope > 0):
        state = "IMPROVING"
    elif fast_slope < 0 and slow_slope < 0 and gap <= prior_gap:
        state = "BEARISH"
    elif fast_slope < 0 or gap < prior_gap:
        state = "DETERIORATING"
    else:
        state = "NEUTRAL"
    return state, {
        "weekly_hma_gap": round(gap, 4),
        "weekly_hma_gap_prior": round(prior_gap, 4),
        "weekly_fast_slope": round(fast_slope, 4),
        "weekly_slow_slope": round(slow_slope, 4),
    }


def timing_state(
    *,
    daily_bullish: bool,
    hma_aligned: bool,
    kama_rising: bool,
    trend_commitment: bool,
    chop: bool,
    rotational: bool,
    overextended: bool,
    score: float,
    htf_state: str,
    daily_persistent: bool | None = None,
    adx_confirmed: bool = True,
) -> str:
    # kama_rising is accepted for report compatibility only; it is not a gate.
    structure_holding = daily_bullish if daily_persistent is None else daily_persistent
    if overextended:
        return "EXTENDED"
    if chop or rotational or not structure_holding:
        return "WEAK"
    daily_ready = structure_holding and hma_aligned and trend_commitment and adx_confirmed and score >= 75
    if daily_ready and htf_state == "BULLISH":
        return "READY"
    if daily_ready and htf_state in {"IMPROVING", "NEUTRAL"}:
        return "EARLY"
    if structure_holding and htf_state in {"BULLISH", "IMPROVING", "NEUTRAL"} and score >= 60:
        return "EARLY"
    if htf_state in {"BEARISH", "DETERIORATING"}:
        return "WEAK"
    return "WEAK"
