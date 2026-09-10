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


"""Higher-horizon pullback classification for MIS candidate scoring."""

from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING

import pandas as pd

from .indicators import atr, fixed_hybrid_hull_signals, kama

if TYPE_CHECKING:
    from .horizon_scoring import HorizonScore


@dataclass(frozen=True)
class PullbackResult:
    state: str
    eligible: bool
    score: float
    reasons: tuple[str, ...]
    metrics: dict[str, float | bool]

    def to_dict(self) -> dict:
        return asdict(self)


def _qualified_higher_horizon(scores: dict[str, HorizonScore]) -> tuple[str, ...]:
    return tuple(h for h in ("3M", "6M", "12M") if h in scores and scores[h].state == "QUALIFIED")


def evaluate_pullback(frame: pd.DataFrame, scores: dict[str, HorizonScore]) -> PullbackResult:
    """Classify pullbacks only for stocks qualified at 3M or above."""
    qualified = _qualified_higher_horizon(scores)
    if not qualified:
        return PullbackResult(
            state="NOT_ELIGIBLE",
            eligible=False,
            score=0.0,
            reasons=("no_qualified_horizon_above_1m",),
            metrics={},
        )

    data = frame.sort_values("trade_date").copy()
    if len(data) < 80:
        return PullbackResult(
            state="NOT_ELIGIBLE",
            eligible=False,
            score=0.0,
            reasons=("insufficient_history",),
            metrics={},
        )

    hybrid = fixed_hybrid_hull_signals(data)
    close = pd.to_numeric(data["close"], errors="coerce")
    current_atr = float(atr(data, 14).iloc[-1])
    kama30 = kama(close, 30)
    last = data.iloc[-1]
    prior = data.iloc[-2]
    hull55 = float(hybrid["hull55"])
    kama_value = float(kama30.iloc[-1]) if pd.notna(kama30.iloc[-1]) else hull55
    support = max(hull55, kama_value)
    distance_atr = (float(last["close"]) - support) / current_atr if current_atr > 0 else 0.0

    recent_low = float(data["low"].iloc[-10:].min())
    structural_low = float(data["low"].iloc[-60:].min())
    volume_avg = float(data["volume"].shift(1).rolling(20).mean().iloc[-1]) if "volume" in data else 0.0
    volume_multiple = float(last.get("volume", 0.0) / volume_avg) if volume_avg > 0 else 0.0
    bearish_breakdown = bool(
        float(last["close"]) < structural_low
        or (float(last["close"]) < support - current_atr and float(last.get("volume", 0.0)) > 1.5 * volume_avg)
    )
    bullish_reversal = bool(float(last["close"]) > float(last["open"]) and float(last["close"]) > float(prior["high"]))
    near_support = bool(-0.5 <= distance_atr <= 1.0)
    deep = bool(-1.5 <= distance_atr < -0.5)
    weekly_intact = any(scores[h].metrics.get("weekly_bullish", False) for h in qualified)
    rs_retained = any(
        float(scores[h].metrics.get({"3M": "rs63", "6M": "rs126", "12M": "rs252"}[h], 0.0)) > 0 for h in qualified
    )

    components = {
        "higher_horizon": 25.0,
        "weekly_structure": 20.0 if weekly_intact else 0.0,
        "support_zone": 15.0 if near_support else (7.5 if deep else 0.0),
        "rs_retained": 15.0 if rs_retained else 0.0,
        "reversal": 10.0 if bullish_reversal else 0.0,
        "volume_behaviour": 10.0 if volume_multiple <= 1.2 else 4.0,
        "risk_reward_readiness": 5.0 if not bearish_breakdown else 0.0,
    }
    score = round(sum(components.values()), 2)

    if bearish_breakdown or not weekly_intact or not rs_retained:
        state = "STRUCTURAL_BREAKDOWN"
    elif deep:
        state = "DEEP_PULLBACK"
    elif near_support and bullish_reversal and score >= 70:
        state = "CONFIRMED_PULLBACK_ENTRY"
    elif near_support:
        state = "NORMAL_PULLBACK"
    else:
        state = "NO_PULLBACK"

    reasons = [f"qualified_{h.lower()}" for h in qualified]
    reasons.extend(
        [
            "weekly_structure_intact" if weekly_intact else "weekly_structure_failed",
            "relative_strength_retained" if rs_retained else "relative_strength_failed",
            "near_support" if near_support else ("deep_pullback" if deep else "outside_pullback_zone"),
            "bullish_reversal_confirmed" if bullish_reversal else "reversal_not_confirmed",
        ]
    )
    if bearish_breakdown:
        reasons.append("bearish_structural_breakdown")

    return PullbackResult(
        state=state,
        eligible=True,
        score=score,
        reasons=tuple(dict.fromkeys(reasons)),
        metrics={
            **hybrid,
            "support": round(support, 2),
            "distance_atr": round(distance_atr, 3),
            "recent_low": round(recent_low, 2),
            "structural_low": round(structural_low, 2),
            "volume_multiple": round(volume_multiple, 3),
            "bullish_reversal": bullish_reversal,
            "weekly_intact": weekly_intact,
            "rs_retained": rs_retained,
        },
    )
