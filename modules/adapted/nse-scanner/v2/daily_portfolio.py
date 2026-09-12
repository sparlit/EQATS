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


"""Apply completed daily bars to all persistent V2 positions."""


from typing import TYPE_CHECKING

from .lifecycle import Position
from .lifecycle_processor import ProcessedEvent, process_daily_bar

if TYPE_CHECKING:
    from collections.abc import Mapping

    from .portfolio_store import PortfolioStore


def process_portfolio_day(
    store: PortfolioStore,
    trade_date: str,
    bars_by_symbol: Mapping[str, Mapping[str, float]],
    *,
    qualification_by_symbol: Mapping[str, bool] | None = None,
    invalidated_symbols: set[str] | None = None,
    partial_fraction: float = 0.5,
) -> dict[str, list[ProcessedEvent]]:
    """Process every non-terminal position and persist each state transition."""
    qualification_by_symbol = qualification_by_symbol or {}
    invalidated_symbols = invalidated_symbols or set()
    output: dict[str, list[ProcessedEvent]] = {}

    for position in store.open_positions():
        bar = bars_by_symbol.get(position.symbol)
        if bar is None:
            continue
        events = process_daily_bar(
            position,
            trade_date,
            bar,
            qualified=qualification_by_symbol.get(position.symbol, True),
            invalidated=position.symbol in invalidated_symbols,
            partial_fraction=partial_fraction,
        )
        for event in events:
            store.save_position(
                event.position,
                event_type=event.event_type,
                previous_state=event.previous_state,
                price=event.price,
            )
        if events:
            output[position.trade_id] = events
            final = events[-1].position
            if final.state.value in {"CLOSED", "CANCELLED"}:
                store.deactivate_watch(final.symbol, final.horizon, final.reason)
    return output
