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


"""Sequential weekly-discovery to 12-month compounding progression."""

from dataclasses import dataclass
from enum import Enum, StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping


class ProgressionStage(StrEnum):
    WEEKLY_EMERGING = "WEEKLY_EMERGING"
    WEEKLY_CONFIRMED = "WEEKLY_CONFIRMED"
    ENTRY_PENDING = "ENTRY_PENDING"
    ACTIVE_1M = "ACTIVE_1M"
    QUALIFIED_3M = "QUALIFIED_3M"
    QUALIFIED_6M = "QUALIFIED_6M"
    QUALIFIED_12M = "QUALIFIED_12M"
    TRAILING = "TRAILING"
    EXITED = "EXITED"


@dataclass(frozen=True)
class ProgressionDecision:
    stage: ProgressionStage
    changed: bool
    reason: str


_STATE_RANK = {"REJECTED": 0, "DEVELOPING": 1, "WATCH": 2, "QUALIFIED": 3}


def weekly_discovery(metrics: Mapping[str, object]) -> ProgressionDecision:
    """Identify weekly improvement before a daily entry is allowed."""
    bullish = bool(metrics.get("weekly_bullish"))
    rising = bool(metrics.get("weekly_rising"))
    daily = bool(metrics.get("daily_bullish"))
    rs = max(float(metrics.get("rs63", 0.0) or 0.0), float(metrics.get("rs126", 0.0) or 0.0))
    if bullish and rising and rs > 0:
        return ProgressionDecision(
            ProgressionStage.WEEKLY_CONFIRMED, True, "weekly_trend_and_relative_strength_confirmed"
        )
    if (bullish or rising) and daily and rs > -0.02:
        return ProgressionDecision(ProgressionStage.WEEKLY_EMERGING, True, "weekly_structure_improving")
    return ProgressionDecision(ProgressionStage.EXITED, False, "weekly_discovery_not_present")


def classify_opportunity(
    previous_stage: str | None,
    *,
    weekly_stage: ProgressionStage,
    actionable_trigger: bool,
    trade_plan_ready: bool,
    previously_exited: bool = False,
) -> tuple[str, ProgressionStage]:
    """Return the daily opportunity label and current pre-entry stage."""
    if actionable_trigger and trade_plan_ready and weekly_stage == ProgressionStage.WEEKLY_CONFIRMED:
        stage = ProgressionStage.ENTRY_PENDING
        if previously_exited:
            return "RE_ENTRY", stage
        if previous_stage in {None, ProgressionStage.WEEKLY_EMERGING.value, ProgressionStage.WEEKLY_CONFIRMED.value}:
            return "FRESH_SIGNAL", stage
        return "CONTINUING", stage
    if weekly_stage == ProgressionStage.WEEKLY_CONFIRMED:
        label = "NEWLY_QUALIFIED" if previous_stage in {None, ProgressionStage.WEEKLY_EMERGING.value} else "CONTINUING"
        return label, weekly_stage
    if weekly_stage == ProgressionStage.WEEKLY_EMERGING:
        return "WEEKLY_EMERGING", weekly_stage
    return "UNQUALIFIED", ProgressionStage.EXITED


def next_holding_stage(
    current_stage: str,
    horizon_states: Mapping[str, str],
    sessions_held: int,
    *,
    trend_intact: bool,
    fundamentals_passed: bool | None = None,
) -> ProgressionDecision:
    """Promote only after time and positive requalification; time alone never promotes."""
    current = ProgressionStage(current_stage)
    if not trend_intact:
        return ProgressionDecision(
            ProgressionStage.TRAILING, current != ProgressionStage.TRAILING, "trend_weakened_protect_position"
        )

    if current in {ProgressionStage.ENTRY_PENDING, ProgressionStage.ACTIVE_1M}:
        if sessions_held >= 20 and _STATE_RANK.get(horizon_states.get("3M", "REJECTED"), 0) >= 2:
            return ProgressionDecision(ProgressionStage.QUALIFIED_3M, True, "one_month_survived_and_3m_requalified")
        return ProgressionDecision(
            ProgressionStage.ACTIVE_1M, current != ProgressionStage.ACTIVE_1M, "one_month_stage_continues"
        )

    if current == ProgressionStage.QUALIFIED_3M:
        if sessions_held >= 60 and _STATE_RANK.get(horizon_states.get("6M", "REJECTED"), 0) >= 2:
            if fundamentals_passed is not True:
                return ProgressionDecision(current, False, "six_month_fundamental_confirmation_required")
            return ProgressionDecision(ProgressionStage.QUALIFIED_6M, True, "three_months_survived_and_6m_requalified")
        return ProgressionDecision(current, False, "three_month_stage_continues")

    if current == ProgressionStage.QUALIFIED_6M:
        if sessions_held >= 120 and _STATE_RANK.get(horizon_states.get("12M", "REJECTED"), 0) >= 2:
            if fundamentals_passed is not True:
                return ProgressionDecision(current, False, "twelve_month_fundamental_confirmation_required")
            return ProgressionDecision(ProgressionStage.QUALIFIED_12M, True, "six_months_survived_and_12m_requalified")
        return ProgressionDecision(current, False, "six_month_stage_continues")

    return ProgressionDecision(current, False, "stage_continues")
