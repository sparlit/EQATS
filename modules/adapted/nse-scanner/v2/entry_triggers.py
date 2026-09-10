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


"""Institutional entry-trigger classification for MIS candidate scoring.

The trigger engine answers whether a technically qualified stock is actionable
now.  It does not determine stock quality; horizon scoring remains authoritative.
"""

from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING

import pandas as pd

from .indicators import atr, fixed_hybrid_hull_signals, hma
from .setups import breakout_signal, compression_signal

if TYPE_CHECKING:
    from .horizon_scoring import HorizonScore
    from .pullback import PullbackResult


@dataclass(frozen=True)
class EntryTrigger:
    name: str
    actionable: bool
    score: float
    reasons: tuple[str, ...]
    metrics: dict[str, float | bool | str]

    def to_dict(self) -> dict:
        return asdict(self)


_PRIORITY = {
    "QUALIFIED_PULLBACK": 90,
    "BREAKOUT": 85,
    "COMPRESSION_RELEASE": 80,
    "HULL_CROSSOVER": 75,
    "RS_ACCELERATION": 65,
    "TREND_CONTINUATION": 60,
    "REACCUMULATION": 55,
    "NO_TRIGGER": 0,
}


def _qualified_horizons(scores: dict[str, HorizonScore]) -> tuple[str, ...]:
    return tuple(h for h in ("1M", "3M", "6M", "12M") if h in scores and scores[h].state == "QUALIFIED")


def _watch_horizons(scores: dict[str, HorizonScore]) -> tuple[str, ...]:
    return tuple(h for h in ("1M", "3M", "6M", "12M") if h in scores and scores[h].state == "WATCH")


def _highest_quality_score(scores: dict[str, HorizonScore]) -> float:
    eligible = [score.score for score in scores.values() if score.state in {"QUALIFIED", "WATCH"}]
    return max(eligible, default=0.0)


def _rs_acceleration(scores: dict[str, HorizonScore]) -> tuple[bool, float]:
    metrics = next(iter(scores.values())).metrics if scores else {}
    rs20 = float(metrics.get("rs20", 0.0))
    rs63 = float(metrics.get("rs63", 0.0))
    accelerated = rs20 > 0.03 and rs20 > rs63 / 3.0
    score = min(100.0, max(0.0, 50.0 + rs20 * 500.0)) if accelerated else 0.0
    return accelerated, score


def evaluate_entry_triggers(
    frame: pd.DataFrame,
    horizon_scores: dict[str, HorizonScore],
    pullback: PullbackResult | None = None,
) -> tuple[EntryTrigger, ...]:
    """Evaluate all supported triggers and return them in priority order."""
    data = frame.sort_values("trade_date").copy()
    if len(data) < 60:
        return (EntryTrigger("NO_TRIGGER", False, 0.0, ("insufficient_history",), {}),)

    qualified = _qualified_horizons(horizon_scores)
    watched = _watch_horizons(horizon_scores)
    quality_available = bool(qualified or watched)
    hybrid = fixed_hybrid_hull_signals(data)
    close = pd.to_numeric(data["close"], errors="coerce")
    current_atr = float(atr(data, 14).iloc[-1])
    last = data.iloc[-1]
    prior = data.iloc[-2]

    hma21 = hma(close, 21)
    hma51 = hma(close, 51)
    hull_cross = bool(
        pd.notna(hma21.iloc[-2])
        and pd.notna(hma51.iloc[-2])
        and hma21.iloc[-2] <= hma51.iloc[-2]
        and hma21.iloc[-1] > hma51.iloc[-1]
        and hybrid["daily_bullish"]
    )

    breakout = breakout_signal(data)
    compression = compression_signal(data)
    recent_high = float(data["high"].shift(1).rolling(10).max().iloc[-1])
    trend_continuation = bool(
        hybrid["daily_bullish"]
        and hybrid["weekly_bullish"]
        and float(last["close"]) > recent_high
        and not hybrid["stretched"]
        and not hybrid["chop"]
    )

    volume_avg = float(data["volume"].shift(1).rolling(20).mean().iloc[-1]) if "volume" in data else 0.0
    volume_multiple = float(last.get("volume", 0.0) / volume_avg) if volume_avg > 0 else 0.0
    range20_high = float(data["high"].shift(1).rolling(20).max().iloc[-1])
    range20_low = float(data["low"].shift(1).rolling(20).min().iloc[-1])
    range_width_atr = (range20_high - range20_low) / current_atr if current_atr > 0 else 999.0
    compression_release = bool(compression.passed and float(last["close"]) > range20_high and volume_multiple >= 1.2)

    reaccumulation = bool(
        any(h in qualified for h in ("6M", "12M"))
        and hybrid["weekly_bullish"]
        and hybrid["daily_bullish"]
        and 0.0 <= float(hybrid["distance_atr"]) <= 1.0
        and volume_multiple >= 1.0
        and float(last["close"]) > float(prior["high"])
    )

    rs_accel, rs_accel_score = _rs_acceleration(horizon_scores)
    pullback_actionable = bool(pullback and pullback.state == "CONFIRMED_PULLBACK_ENTRY")

    common_metrics: dict[str, float | bool | str] = {
        "qualified_horizons": ",".join(qualified),
        "watch_horizons": ",".join(watched),
        "highest_quality_score": round(_highest_quality_score(horizon_scores), 2),
        "volume_multiple": round(volume_multiple, 3),
        "range20_width_atr": round(range_width_atr, 3),
        "daily_bullish": bool(hybrid["daily_bullish"]),
        "weekly_bullish": bool(hybrid["weekly_bullish"]),
        "daily_persistent": bool(hybrid["daily_persistent"]),
        "stretched": bool(hybrid["stretched"]),
        "chop": bool(hybrid["chop"]),
    }

    candidates = [
        EntryTrigger(
            "QUALIFIED_PULLBACK",
            quality_available and pullback_actionable,
            float(pullback.score if pullback else 0.0),
            tuple(pullback.reasons if pullback else ("pullback_not_evaluated",)),
            {**common_metrics, "pullback_state": pullback.state if pullback else "NOT_EVALUATED"},
        ),
        EntryTrigger(
            "BREAKOUT",
            quality_available and breakout.passed and not hybrid["stretched"] and not hybrid["chop"],
            float(breakout.score),
            tuple(breakout.reasons),
            {**common_metrics, **breakout.metrics},
        ),
        EntryTrigger(
            "COMPRESSION_RELEASE",
            quality_available and compression_release and not hybrid["chop"],
            85.0 if compression_release else float(compression.score),
            (
                "volatility_compression_released",
                "close_above_compression_range",
                "volume_confirmed",
            )
            if compression_release
            else tuple(compression.reasons),
            {**common_metrics, **compression.metrics},
        ),
        EntryTrigger(
            "HULL_CROSSOVER",
            quality_available and hull_cross and not hybrid["stretched"] and not hybrid["chop"],
            80.0 if hull_cross else 0.0,
            ("hma21_crossed_above_hma51", "hybrid_hull_confirmed") if hull_cross else ("no_fresh_hull_crossover",),
            common_metrics,
        ),
        EntryTrigger(
            "RS_ACCELERATION",
            quality_available and rs_accel and hybrid["daily_bullish"] and not hybrid["stretched"],
            round(rs_accel_score, 2),
            ("short_term_relative_strength_accelerating", "daily_trend_confirmed")
            if rs_accel
            else ("no_rs_acceleration",),
            common_metrics,
        ),
        EntryTrigger(
            "TREND_CONTINUATION",
            quality_available and trend_continuation,
            78.0 if trend_continuation else 0.0,
            ("daily_and_weekly_trend_aligned", "close_above_recent_pivot")
            if trend_continuation
            else ("no_trend_continuation_trigger",),
            {**common_metrics, "recent_pivot_high": round(recent_high, 2)},
        ),
        EntryTrigger(
            "REACCUMULATION",
            quality_available and reaccumulation,
            76.0 if reaccumulation else 0.0,
            ("higher_horizon_leader", "controlled_reaccumulation", "pivot_reclaim")
            if reaccumulation
            else ("no_reaccumulation_trigger",),
            common_metrics,
        ),
    ]

    actionable = [trigger for trigger in candidates if trigger.actionable]
    if not actionable:
        return (
            *candidates,
            EntryTrigger(
                "NO_TRIGGER",
                False,
                0.0,
                ("technically_qualified_but_no_actionable_entry",)
                if quality_available
                else ("no_qualified_or_watch_horizon",),
                common_metrics,
            ),
        )
    return tuple(
        sorted(candidates, key=lambda trigger: (-int(trigger.actionable), -_PRIORITY[trigger.name], -trigger.score))
    )


def select_primary_trigger(triggers: tuple[EntryTrigger, ...]) -> EntryTrigger:
    """Return the strongest actionable trigger, otherwise NO_TRIGGER."""
    actionable = [trigger for trigger in triggers if trigger.actionable]
    if actionable:
        return max(actionable, key=lambda trigger: (_PRIORITY[trigger.name], trigger.score))
    for trigger in triggers:
        if trigger.name == "NO_TRIGGER":
            return trigger
    return EntryTrigger("NO_TRIGGER", False, 0.0, ("no_actionable_entry",), {})
