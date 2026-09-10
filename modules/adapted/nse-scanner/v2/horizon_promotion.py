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


"""Auditable monthly carry-forward decisions for V2 positions."""

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

import pandas as pd

from .indicators import fixed_hybrid_hull_signals
from .lifecycle import Position, TradeState

if TYPE_CHECKING:
    from .portfolio_store import PortfolioStore

PROMOTION_TARGETS = {"SWING_1_3M": "POSITIONAL_3_6M", "POSITIONAL_3_6M": "POSITIONAL_6_12M"}
MIN_SESSIONS = {"SWING_1_3M": 20, "POSITIONAL_3_6M": 60}
ACTIVE_STATES = {TradeState.OPEN, TradeState.PARTIAL, TradeState.TRAILING}


@dataclass(frozen=True)
class PromotionDecision:
    trade_id: str
    symbol: str
    current_horizon: str
    target_horizon: str | None
    action: str
    sessions_held: int
    current_r: float | None
    daily_bullish: bool
    weekly_bullish: bool
    kama_rising: bool
    stretched: bool
    chop: bool
    reasons: tuple[str, ...]

    @property
    def promoted(self) -> bool:
        return self.action == "PROMOTE"


def _sessions_held(frame: pd.DataFrame, created_date: str) -> int:
    created = pd.Timestamp(created_date).normalize()
    dates = pd.to_datetime(frame["trade_date"], errors="coerce").dropna().dt.normalize()
    return max(0, int((dates > created).sum()))


def _current_r(position: Position) -> float | None:
    if position.last_price is None or position.entry <= position.initial_stop:
        return None
    return round((position.last_price - position.entry) / (position.entry - position.initial_stop), 2)


def assess_promotion(position: Position, frame: pd.DataFrame) -> PromotionDecision:
    """Require an open, profitable, stable trend before a horizon promotion."""
    signals = fixed_hybrid_hull_signals(frame)
    held, current_r = _sessions_held(frame, position.created_date), _current_r(position)
    target, reasons = PROMOTION_TARGETS.get(position.horizon), []
    if target is None:
        reasons.append("already_at_6_12_month_horizon")
    if position.state not in ACTIVE_STATES:
        reasons.append("position_not_open")
    if target and held < MIN_SESSIONS[position.horizon]:
        reasons.append(f"minimum_{MIN_SESSIONS[position.horizon]}_sessions_not_reached")
    if current_r is None or current_r < 1.0:
        reasons.append("one_r_profit_cushion_not_reached")
    if not signals.get("daily_persistent", signals.get("daily_bullish", False)):
        reasons.append("daily_hull_structure_not_persistent")
    if not signals.get("weekly_bullish", False):
        reasons.append("weekly_hma21_hma51_not_aligned")
    if signals["stretched"]:
        reasons.append("price_extended_above_hybrid_hull")
    if signals["chop"]:
        reasons.append("hybrid_hull_chop")
    return PromotionDecision(
        position.trade_id,
        position.symbol,
        position.horizon,
        target,
        "PROMOTE" if target and not reasons else "HOLD",
        held,
        current_r,
        bool(signals.get("daily_persistent", signals.get("daily_bullish", False))),
        bool(signals["weekly_bullish"]),
        bool(signals["kama_rising"]),
        bool(signals["stretched"]),
        bool(signals["chop"]),
        tuple(reasons or ("all_carry_forward_rules_passed",)),
    )


def apply_monthly_promotions(store: PortfolioStore, prices: pd.DataFrame, review_date: str) -> list[PromotionDecision]:
    """Persist only horizon changes; stop, quantity and P&L remain untouched."""
    groups = {str(s): rows.sort_values("trade_date") for s, rows in prices.groupby("symbol")}
    decisions = []
    for position in store.open_positions():
        frame = groups.get(position.symbol)
        if frame is None or frame.empty:
            continue
        decision = assess_promotion(position, frame)
        decisions.append(decision)
        if decision.promoted and decision.target_horizon:
            updated = replace(
                position,
                horizon=decision.target_horizon,
                updated_date=review_date,
                reason=f"monthly_horizon_promoted_to_{decision.target_horizon.lower()}",
            )
            store.save_position(updated, "HORIZON_PROMOTE", previous_state=position.state, price=position.last_price)
    return decisions
