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


"""Deterministic daily OHLC processor for persistent V2 positions.

Conservative execution rule: when a stop and target are both reachable inside the
same daily bar, the stop is processed first because intraday ordering is unknown.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .lifecycle import Position, TradeState, transition

if TYPE_CHECKING:
    from collections.abc import Mapping


@dataclass(frozen=True)
class ProcessedEvent:
    event_type: str
    previous_state: TradeState
    position: Position
    price: float | None


TRAIL_ATR_MULTIPLIER = {
    "SWING_1_3M": 2.0,
    "POSITIONAL_3_6M": 2.5,
    "POSITIONAL_6_12M": 3.0,
}


def _price(bar: Mapping[str, float], field: str) -> float:
    value = bar.get(field)
    if value is None:
        msg = f"bar missing {field}"
        raise ValueError(msg)
    return float(value)


def horizon_trailing_stop(position: Position, bar: Mapping[str, float]) -> float | None:
    """Return a monotonic ATR trailing stop when ATR14 is supplied in the bar."""
    atr14 = bar.get("atr14")
    if atr14 is None or float(atr14) <= 0:
        return None
    close = _price(bar, "close")
    multiplier = TRAIL_ATR_MULTIPLIER.get(position.horizon, 2.5)
    candidate = close - multiplier * float(atr14)
    return round(max(position.stop, candidate), 4)


def process_daily_bar(
    position: Position,
    trade_date: str,
    bar: Mapping[str, float],
    *,
    qualified: bool = True,
    invalidated: bool = False,
    partial_fraction: float = 0.5,
) -> list[ProcessedEvent]:
    """Apply one completed OHLC bar and return every auditable transition.

    WATCH/READY positions can qualify, cancel, or enter. Open positions apply a
    conservative stop-first collision policy. T1 and T2 may both be processed on
    one bar only when the stop was not touched.
    """
    low, high, close = _price(bar, "low"), _price(bar, "high"), _price(bar, "close")
    current = position
    events: list[ProcessedEvent] = []

    def apply(event_type: str, **kwargs: object) -> None:
        nonlocal current
        previous = current.state
        current = transition(current, event_type, trade_date, **kwargs)
        events.append(ProcessedEvent(event_type, previous, current, kwargs.get("price")))

    if current.state in {TradeState.CLOSED, TradeState.CANCELLED}:
        return events

    if current.state == TradeState.WATCH:
        if invalidated:
            apply("CANCEL", price=close, reason="watch_setup_invalidated")
            return events
        if qualified:
            apply("QUALIFY", price=close, reason="daily_qualification_confirmed")

    if current.state == TradeState.READY:
        if invalidated:
            apply("CANCEL", price=close, reason="ready_setup_invalidated")
            return events
        if high >= current.entry:
            apply("ENTER", price=current.entry, reason="entry_level_traded")
            # Entry and stop inside one daily bar: assume adverse ordering.
            if low <= current.stop:
                apply("STOP_HIT", price=current.stop, reason="same_bar_entry_stop_collision")
                return events
        else:
            apply("MARK", price=close, reason="ready_carried_forward")
            return events

    if current.state in {TradeState.OPEN, TradeState.PARTIAL, TradeState.TRAILING}:
        # Stop always wins when daily-bar event ordering is unknowable.
        if low <= current.stop:
            apply("STOP_HIT", price=current.stop, reason="protective_stop_traded")
            return events

        if current.state == TradeState.OPEN and high >= current.target1:
            apply(
                "T1_HIT",
                price=current.target1,
                partial_fraction=partial_fraction,
                reason="target1_traded_partial_exit",
            )

        if current.state in {TradeState.PARTIAL, TradeState.TRAILING} and high >= current.target2:
            apply("T2_HIT", price=current.target2, reason="target2_traded_final_exit")
            return events

        trailing_stop = horizon_trailing_stop(current, bar)
        if trailing_stop is not None and trailing_stop > current.stop:
            apply(
                "TRAIL",
                price=close,
                trailing_stop=trailing_stop,
                reason="horizon_atr_trailing_stop_advanced",
            )
        else:
            apply("MARK", price=close, reason="position_carried_forward")

    return events
