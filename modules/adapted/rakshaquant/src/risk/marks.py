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


"""Marking the book for risk: per-position owners and open P&L by strategy."""


from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal

from src.domain.types import Position
from src.oms.position_book import PositionBook


def open_positions(book: PositionBook, now: datetime) -> list[Position]:
    return [p for p in book.positions(now) if p.quantity]


def owner(book: PositionBook, position: Position) -> str:
    """The strategy of the position's oldest open lot (FIFO closes it first)."""
    lots = book.lots(position.instrument_key, position.product)
    return lots[0].strategy if lots else "unknown"


def unrealized_by_strategy(
    book: PositionBook, marks: Mapping[str, Decimal], now: datetime
) -> dict[str, Decimal]:
    """Open P&L per strategy, lot by lot, at ``marks`` (every open position needs a mark)."""
    out: dict[str, Decimal] = {}
    for position in open_positions(book, now):
        sign = 1 if position.quantity > 0 else -1
        mark = marks[position.instrument_key]
        for lot in book.lots(position.instrument_key, position.product):
            pnl = (mark - lot.price) * lot.quantity * sign
            out[lot.strategy] = out.get(lot.strategy, Decimal(0)) + pnl
    return out
