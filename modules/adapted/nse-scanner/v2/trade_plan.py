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


"""Trigger-aware entry, stop, target and plan-quality construction."""

from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING

import pandas as pd

from .indicators import atr, fixed_hybrid_hull_signals

if TYPE_CHECKING:
    from .entry_triggers import EntryTrigger


@dataclass(frozen=True)
class TradePlan:
    valid: bool
    entry: float
    stop: float
    target1: float
    target2: float
    risk_per_share: float
    reward_risk_t1: float
    reward_risk_t2: float
    resistance: float | None
    reasons: tuple[str, ...]
    state: str = "INVALID"
    score: float = 0.0
    trigger: str = "LEGACY"
    entry_basis: str = ""
    stop_basis: str = ""
    risk_percent: float = 0.0
    valid_for_sessions: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


def _nearest_resistance(data: pd.DataFrame, entry: float, lookback: int = 120) -> float | None:
    history = data.iloc[:-1].tail(lookback)
    if history.empty:
        return None
    candidates = history.loc[history["high"] > entry, "high"]
    if candidates.empty:
        return None
    return float(candidates.min())


def _resistance_levels(data: pd.DataFrame, entry: float, lookback: int = 120) -> list[float]:
    values = sorted(
        float(value)
        for value in data.iloc[:-1].tail(lookback).loc[data.iloc[:-1].tail(lookback)["high"] > entry, "high"]
    )
    levels: list[float] = []
    for value in values:
        if not levels or value > levels[-1] * 1.005:
            levels.append(value)
    return levels


def _expiry_for_horizon(primary_horizon: str) -> int:
    return {"1M": 3, "3M": 5, "6M": 10, "12M": 15}.get(primary_horizon, 3)


def _trigger_levels(data: pd.DataFrame, trigger: EntryTrigger, current_atr: float) -> tuple[float, float, str, str]:
    last = data.iloc[-1]
    hybrid = fixed_hybrid_hull_signals(data)
    pd.to_numeric(data["close"], errors="coerce")
    name = trigger.name

    if name == "BREAKOUT":
        return (
            float(last["high"] + 0.05 * current_atr),
            float(last["low"] - 0.15 * current_atr),
            "breakout_high_plus_0.05_atr",
            "breakout_candle_low_minus_0.15_atr",
        )
    if name == "QUALIFIED_PULLBACK":
        pullback_low = float(data["low"].iloc[-10:].min())
        return (
            float(last["high"] + 0.10 * current_atr),
            float(pullback_low - 0.20 * current_atr),
            "reversal_high_plus_0.10_atr",
            "pullback_low_minus_0.20_atr",
        )
    if name == "COMPRESSION_RELEASE":
        range_high = float(data["high"].shift(1).rolling(20).max().iloc[-1])
        range_low = float(data["low"].shift(1).rolling(20).min().iloc[-1])
        return (
            float(max(last["high"], range_high) + 0.05 * current_atr),
            float(range_low - 0.15 * current_atr),
            "compression_range_high_plus_0.05_atr",
            "compression_range_low_minus_0.15_atr",
        )
    if name == "TREND_CONTINUATION":
        pivot_high = float(data["high"].shift(1).rolling(10).max().iloc[-1])
        swing_low = float(data["low"].iloc[-10:].min())
        return (
            float(max(last["high"], pivot_high) + 0.10 * current_atr),
            float(swing_low - 0.20 * current_atr),
            "recent_pivot_high_plus_0.10_atr",
            "recent_swing_low_minus_0.20_atr",
        )
    if name == "HULL_CROSSOVER":
        return (
            float(last["high"] + 0.10 * current_atr),
            float(min(last["low"], float(hybrid["hull55"])) - 0.20 * current_atr),
            "crossover_high_plus_0.10_atr",
            "hull_support_minus_0.20_atr",
        )
    if name == "RS_ACCELERATION":
        pivot_high = float(data["high"].shift(1).rolling(5).max().iloc[-1])
        pivot_low = float(data["low"].iloc[-5:].min())
        return (
            float(max(last["high"], pivot_high) + 0.10 * current_atr),
            float(pivot_low - 0.20 * current_atr),
            "rs_confirmation_pivot_plus_0.10_atr",
            "rs_confirmation_pivot_low_minus_0.20_atr",
        )
    if name == "REACCUMULATION":
        range_high = float(data["high"].shift(1).rolling(20).max().iloc[-1])
        range_low = float(data["low"].shift(1).rolling(20).min().iloc[-1])
        return (
            float(max(last["high"], range_high) + 0.10 * current_atr),
            float(range_low - 0.20 * current_atr),
            "reaccumulation_range_high_plus_0.10_atr",
            "reaccumulation_range_low_minus_0.20_atr",
        )
    return (
        float(last["high"] + 0.10 * current_atr),
        float(data["low"].iloc[-10:].min() - 0.25 * current_atr),
        "latest_high_plus_0.10_atr",
        "recent_swing_low_minus_0.25_atr",
    )


def build_trigger_trade_plan(
    frame: pd.DataFrame,
    trigger: EntryTrigger,
    primary_horizon: str,
    *,
    target1_r: float = 1.5,
    target2_r: float = 3.0,
    minimum_rr_t1: float = 1.25,
    minimum_rr_t2: float = 2.0,
    min_risk_percent: float = 3.0,
    max_risk_percent: float = 8.0,
) -> TradePlan:
    data = frame.sort_values("trade_date").copy()
    if len(data) < 60:
        return TradePlan(False, 0, 0, 0, 0, 0, 0, 0, None, ("insufficient_history",))
    if not trigger.actionable or trigger.name == "NO_TRIGGER":
        return TradePlan(
            False,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            None,
            ("no_actionable_trigger",),
            state="WAIT",
            trigger=trigger.name,
            valid_for_sessions=_expiry_for_horizon(primary_horizon),
        )

    current_atr = float(atr(data, 14).iloc[-1])
    if not pd.notna(current_atr) or current_atr <= 0:
        return TradePlan(False, 0, 0, 0, 0, 0, 0, 0, None, ("invalid_atr",), trigger=trigger.name)

    entry, stop, entry_basis, stop_basis = _trigger_levels(data, trigger, current_atr)
    risk = entry - stop
    if risk <= 0 or entry <= 0:
        return TradePlan(
            False,
            round(entry, 2),
            round(stop, 2),
            0,
            0,
            round(risk, 2),
            0,
            0,
            None,
            ("non_positive_risk",),
            state="INVALID",
            trigger=trigger.name,
            entry_basis=entry_basis,
            stop_basis=stop_basis,
            valid_for_sessions=_expiry_for_horizon(primary_horizon),
        )

    resistance_levels = _resistance_levels(data, entry)
    resistance = resistance_levels[0] if resistance_levels else None
    raw_t1 = entry + target1_r * risk
    raw_t2 = entry + target2_r * risk
    target1 = min(raw_t1, resistance) if resistance is not None else raw_t1
    target2_resistance = resistance_levels[1] if len(resistance_levels) > 1 else None
    target2 = min(raw_t2, target2_resistance) if target2_resistance is not None else raw_t2
    rr1 = (target1 - entry) / risk
    rr2 = (target2 - entry) / risk
    risk_percent = 100.0 * risk / entry

    resistance_clear = resistance is None or resistance > entry
    rr_ok = rr1 >= minimum_rr_t1
    risk_ok = min_risk_percent <= risk_percent <= max_risk_percent
    rr2_ok = rr2 >= minimum_rr_t2
    close_extension = (entry - float(data.iloc[-1]["close"])) / current_atr
    extension_ok = close_extension <= 1.5

    rr_component = min(30.0, 30.0 * max(rr1, 0.0) / 1.5)
    stop_component = 25.0 if risk_ok else max(0.0, 25.0 * max_risk_percent / max(risk_percent, 0.01))
    entry_component = 20.0 if extension_ok else 5.0
    resistance_component = 15.0 if resistance_clear and rr_ok else 3.0
    atr_component = 10.0 if risk_percent <= 5.0 else (6.0 if risk_ok else 0.0)
    score = round(min(100.0, rr_component + stop_component + entry_component + resistance_component + atr_component), 2)

    if not resistance_clear or risk <= 0:
        state = "INVALID"
    elif not rr_ok or not rr2_ok or not extension_ok:
        state = "WAIT"
    elif not risk_ok or score < 65:
        state = "RISKY"
    else:
        state = "READY"

    reasons = (
        "trigger_specific_entry",
        "t1_reward_risk_ok" if rr_ok else "near_resistance_limits_reward",
        "t2_reward_risk_ok" if rr2_ok else "target2_resistance_limits_reward",
        "risk_percent_ok" if risk_ok else "stop_distance_outside_3_to_8_percent",
        "entry_extension_ok" if extension_ok else "entry_too_extended",
        "resistance_clear" if resistance_clear else "entry_above_resistance_invalid",
    )
    return TradePlan(
        valid=state == "READY",
        entry=round(entry, 2),
        stop=round(stop, 2),
        target1=round(target1, 2),
        target2=round(target2, 2),
        risk_per_share=round(risk, 2),
        reward_risk_t1=round(rr1, 2),
        reward_risk_t2=round(rr2, 2),
        resistance=round(resistance, 2) if resistance is not None else None,
        reasons=reasons,
        state=state,
        score=score,
        trigger=trigger.name,
        entry_basis=entry_basis,
        stop_basis=stop_basis,
        risk_percent=round(risk_percent, 2),
        valid_for_sessions=_expiry_for_horizon(primary_horizon),
    )


def build_long_trade_plan(
    frame: pd.DataFrame,
    entry_buffer_atr: float = 0.10,
    stop_buffer_atr: float = 0.25,
    target1_r: float = 1.5,
    target2_r: float = 3.0,
    max_entry_extension_atr: float = 1.5,
    minimum_rr_t1: float = 1.25,
) -> TradePlan:
    """Backward-compatible legacy plan used until the new candidate path is wired."""
    data = frame.sort_values("trade_date").copy()
    if len(data) < 60:
        return TradePlan(False, 0, 0, 0, 0, 0, 0, 0, None, ("insufficient_history",))
    current_atr = float(atr(data, 14).iloc[-1])
    if not pd.notna(current_atr) or current_atr <= 0:
        return TradePlan(False, 0, 0, 0, 0, 0, 0, 0, None, ("invalid_atr",))
    last = data.iloc[-1]
    entry = float(last["high"] + entry_buffer_atr * current_atr)
    stop = float(data["low"].iloc[-10:].min() - stop_buffer_atr * current_atr)
    risk = entry - stop
    if risk <= 0:
        return TradePlan(False, entry, stop, 0, 0, risk, 0, 0, None, ("non_positive_risk",))
    resistance = _nearest_resistance(data, entry)
    target1 = min(entry + target1_r * risk, resistance) if resistance is not None else entry + target1_r * risk
    target2 = entry + target2_r * risk
    rr1 = (target1 - entry) / risk
    rr2 = (target2 - entry) / risk
    extension_ok = (entry - float(last["close"])) / current_atr <= max_entry_extension_atr
    rr_ok = rr1 >= minimum_rr_t1
    resistance_ok = resistance is None or resistance > entry
    valid = extension_ok and rr_ok and resistance_ok
    return TradePlan(
        valid,
        round(entry, 2),
        round(stop, 2),
        round(target1, 2),
        round(target2, 2),
        round(risk, 2),
        round(rr1, 2),
        round(rr2, 2),
        round(resistance, 2) if resistance is not None else None,
        (
            "entry_extension_ok" if extension_ok else "entry_too_extended",
            "t1_reward_risk_ok" if rr_ok else "near_resistance_limits_reward",
            "resistance_clear" if resistance_ok else "entry_above_resistance_invalid",
        ),
        state="READY" if valid else "INVALID",
        score=100.0 if valid else 0.0,
    )
