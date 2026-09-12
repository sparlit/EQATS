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


"""Persistent, auditable trade lifecycle state machine for NSE Scanner V2."""

from dataclasses import dataclass, replace
from enum import Enum, StrEnum
from uuid import uuid4


class TradeState(StrEnum):
    WATCH = "WATCH"
    READY = "READY"
    OPEN = "OPEN"
    PARTIAL = "PARTIAL"
    TRAILING = "TRAILING"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True)
class Position:
    trade_id: str
    symbol: str
    horizon: str
    state: TradeState
    created_date: str
    updated_date: str
    entry: float
    initial_stop: float
    stop: float
    target1: float
    target2: float
    quantity: float
    remaining_quantity: float
    realised_quantity: float = 0.0
    realised_pnl: float = 0.0
    last_price: float | None = None
    exit_price: float | None = None
    reason: str = "created"
    progression_stage: str = "ENTRY_PENDING"


def new_position(
    symbol: str,
    horizon: str,
    trade_date: str,
    entry: float,
    stop: float,
    target1: float,
    target2: float,
    quantity: float = 1.0,
) -> Position:
    if not (stop < entry < target1 <= target2):
        msg = "invalid long trade geometry"
        raise ValueError(msg)
    if quantity <= 0:
        msg = "quantity must be positive"
        raise ValueError(msg)
    return Position(
        trade_id=str(uuid4()),
        symbol=symbol,
        horizon=horizon,
        state=TradeState.WATCH,
        created_date=trade_date,
        updated_date=trade_date,
        entry=entry,
        initial_stop=stop,
        stop=stop,
        target1=target1,
        target2=target2,
        quantity=quantity,
        remaining_quantity=quantity,
    )


def transition(
    position: Position,
    event: str,
    trade_date: str,
    price: float | None = None,
    partial_fraction: float = 0.5,
    trailing_stop: float | None = None,
    reason: str | None = None,
) -> Position:
    event = event.upper()
    state = position.state

    if event == "QUALIFY" and state == TradeState.WATCH:
        return replace(
            position,
            state=TradeState.READY,
            updated_date=trade_date,
            last_price=price,
            reason=reason or "qualification_confirmed",
        )
    if event == "ENTER" and state == TradeState.READY:
        return replace(
            position,
            state=TradeState.OPEN,
            updated_date=trade_date,
            last_price=price or position.entry,
            reason=reason or "entry_triggered",
            progression_stage="ACTIVE_1M",
        )
    if event == "PROMOTE" and state in {TradeState.OPEN, TradeState.PARTIAL, TradeState.TRAILING}:
        if not reason:
            msg = "promotion requires a progression stage"
            raise ValueError(msg)
        return replace(position, updated_date=trade_date, last_price=price, progression_stage=reason)
    if event == "T1_HIT" and state == TradeState.OPEN:
        if not 0 < partial_fraction < 1:
            msg = "partial_fraction must be between 0 and 1"
            raise ValueError(msg)
        sold = position.remaining_quantity * partial_fraction
        return replace(
            position,
            state=TradeState.PARTIAL,
            updated_date=trade_date,
            remaining_quantity=position.remaining_quantity - sold,
            realised_quantity=position.realised_quantity + sold,
            realised_pnl=position.realised_pnl + sold * ((price or position.target1) - position.entry),
            last_price=price or position.target1,
            stop=max(position.stop, position.entry),
            reason=reason or "target1_partial_exit",
        )
    if event == "TRAIL" and state in {TradeState.OPEN, TradeState.PARTIAL, TradeState.TRAILING}:
        if trailing_stop is None or trailing_stop < position.stop:
            msg = "trailing stop cannot move backward"
            raise ValueError(msg)
        return replace(
            position,
            state=TradeState.TRAILING,
            updated_date=trade_date,
            stop=trailing_stop,
            last_price=price,
            reason=reason or "trailing_stop_advanced",
        )
    if event in {"STOP_HIT", "T2_HIT", "EXIT"} and state in {TradeState.OPEN, TradeState.PARTIAL, TradeState.TRAILING}:
        exit_price = price if price is not None else (position.stop if event == "STOP_HIT" else position.target2)
        sold = position.remaining_quantity
        return replace(
            position,
            state=TradeState.CLOSED,
            updated_date=trade_date,
            realised_quantity=position.quantity,
            remaining_quantity=0.0,
            realised_pnl=position.realised_pnl + sold * (exit_price - position.entry),
            last_price=exit_price,
            exit_price=exit_price,
            reason=reason or event.lower(),
            progression_stage="EXITED",
        )
    if event == "CANCEL" and state in {TradeState.WATCH, TradeState.READY}:
        return replace(
            position,
            state=TradeState.CANCELLED,
            updated_date=trade_date,
            last_price=price,
            reason=reason or "setup_invalidated_before_entry",
        )
    if event == "MARK":
        return replace(position, updated_date=trade_date, last_price=price, reason=reason or position.reason)
    msg = f"invalid transition: {state.value} + {event}"
    raise ValueError(msg)
