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


"""Opportunity timing and higher-timeframe transition helpers for V2.

This layer enriches ACTION/WATCH/REJECT with where an opportunity sits in its
move. It intentionally does not add new hard selection gates.
"""


from typing import TYPE_CHECKING

import pandas as pd

from .indicators import hma

if TYPE_CHECKING:
    from collections.abc import Mapping

_HORIZON_ORDER = {"1M": 1, "3M": 2, "6M": 3, "12M": 4}
_PULLBACK_STATES = {"DEEP_PULLBACK", "CONFIRMED_PULLBACK_ENTRY", "PULLBACK", "REENTRY_READY"}


def compute_htf_transition(frame: pd.DataFrame) -> tuple[str, dict[str, float | bool]]:
    data = frame.sort_values("trade_date").copy()
    weekly = data.set_index(pd.to_datetime(data["trade_date"]))["close"].resample("W-FRI").last().dropna()
    if len(weekly) < 52:
        return "NEUTRAL", {"weekly_count": float(len(weekly))}
    fast, slow = hma(weekly, 21), hma(weekly, 51)
    required = [fast.iloc[-1], fast.iloc[-2], slow.iloc[-1], slow.iloc[-2]]
    if any(pd.isna(value) for value in required):
        return "NEUTRAL", {"weekly_count": float(len(weekly))}
    gap = float(fast.iloc[-1] - slow.iloc[-1])
    prior_gap = float(fast.iloc[-2] - slow.iloc[-2])
    fast_slope = float(fast.iloc[-1] - fast.iloc[-2])
    slow_slope = float(slow.iloc[-1] - slow.iloc[-2])
    bullish = gap > 0 and fast_slope >= 0
    if bullish:
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
        "weekly_count": float(len(weekly)),
        "weekly_hma_gap": round(gap, 4),
        "weekly_hma_gap_prior": round(prior_gap, 4),
        "weekly_fast_slope": round(fast_slope, 4),
        "weekly_slow_slope": round(slow_slope, 4),
        "weekly_bullish": bullish,
    }


def htf_transition(metrics: Mapping[str, object]) -> str:
    if bool(metrics.get("weekly_bullish")):
        return "BULLISH" if bool(metrics.get("weekly_rising", True)) else "DETERIORATING"
    gap = float(metrics.get("weekly_hma_gap", 0.0) or 0.0)
    prior_gap = float(metrics.get("weekly_hma_gap_prior", gap) or gap)
    fast_slope = float(metrics.get("weekly_fast_slope", 0.0) or 0.0)
    slow_slope = float(metrics.get("weekly_slow_slope", 0.0) or 0.0)
    if gap < 0 and gap > prior_gap and fast_slope > 0:
        return "IMPROVING"
    if gap >= 0 and fast_slope >= 0:
        return "IMPROVING"
    if fast_slope < 0 and slow_slope < 0 and gap <= prior_gap:
        return "BEARISH"
    if fast_slope < 0 or gap < prior_gap:
        return "DETERIORATING"
    return "NEUTRAL"


def entry_horizon(primary_horizon: str, trigger_name: str) -> str:
    if trigger_name in {"HULL_CROSSOVER", "RS_ACCELERATION"}:
        preferred = "1M"
    elif trigger_name in {
        "QUALIFIED_PULLBACK",
        "BREAKOUT",
        "COMPRESSION_RELEASE",
        "TREND_CONTINUATION",
        "REACCUMULATION",
    }:
        preferred = "3M"
    else:
        preferred = primary_horizon
    return preferred if _HORIZON_ORDER.get(primary_horizon, 1) >= _HORIZON_ORDER.get(preferred, 1) else primary_horizon


def entry_route(trigger_name: str, pullback_state: str, classification: str) -> str:
    if trigger_name == "QUALIFIED_PULLBACK" or (pullback_state or "") in _PULLBACK_STATES:
        return "PULLBACK / RE-ENTRY"
    if classification == "ACTION" and trigger_name in {"TREND_CONTINUATION", "REACCUMULATION", "BREAKOUT"}:
        return "DIRECT ENTRY"
    if classification == "ACTION":
        return "FRESH ENTRY"
    return "DEVELOPING"


def timing_state(
    *,
    classification: str,
    metrics: Mapping[str, object],
    htf_state: str,
    trade_plan_state: str,
    reward_risk_t1: float,
    pullback_state: str,
) -> str:
    stretched = bool(metrics.get("stretched"))
    bool(metrics.get("daily_bullish"))
    structure_holding = bool(metrics.get("daily_persistent", metrics.get("daily_bullish")))
    if stretched or trade_plan_state == "RISKY" or (reward_risk_t1 > 0 and reward_risk_t1 < 1.0):
        return "EXTENDED"
    if (pullback_state or "") in _PULLBACK_STATES and classification in {"ACTION", "WATCH"}:
        return "PULLBACK_REENTRY" if classification == "WATCH" else "READY"
    if classification == "ACTION" and trade_plan_state == "READY":
        return "READY"
    if classification == "WATCH" and structure_holding and htf_state in {"BULLISH", "IMPROVING", "NEUTRAL"}:
        return "EARLY"
    if classification == "WATCH" and htf_state == "BULLISH":
        return "EARLY"
    return "WEAK"
