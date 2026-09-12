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


"""Auditable V2 portfolio P&L and risk snapshots."""

from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING

from .lifecycle import Position, TradeState

if TYPE_CHECKING:
    from collections.abc import Iterable


@dataclass(frozen=True)
class PortfolioSnapshot:
    portfolio_date: str
    capital_base: float
    committed_capital: float
    market_value: float
    realised_pnl: float
    unrealised_pnl: float
    total_pnl: float
    portfolio_return_pct: float
    initial_risk: float
    open_risk_to_stops: float
    open_positions: int
    pending_setups: int

    def to_dict(self) -> dict:
        return asdict(self)


def build_portfolio_snapshot(
    positions: Iterable[Position],
    portfolio_date: str,
    capital_base: float,
) -> PortfolioSnapshot:
    rows = list(positions)
    live_states = {TradeState.OPEN, TradeState.PARTIAL, TradeState.TRAILING}
    committed_states = live_states | {TradeState.WATCH, TradeState.READY}
    live = [position for position in rows if position.state in live_states]
    committed = [position for position in rows if position.state in committed_states]
    realised = sum(position.realised_pnl for position in rows)
    unrealised = sum(
        position.remaining_quantity * ((position.last_price or position.entry) - position.entry) for position in live
    )
    committed_capital = sum(position.quantity * position.entry for position in committed)
    market_value = sum(position.remaining_quantity * (position.last_price or position.entry) for position in live)
    initial_risk = sum(position.quantity * (position.entry - position.initial_stop) for position in committed)
    open_risk = sum(position.remaining_quantity * max(position.entry - position.stop, 0.0) for position in live)
    total = realised + unrealised
    return PortfolioSnapshot(
        portfolio_date=portfolio_date,
        capital_base=round(capital_base, 2),
        committed_capital=round(committed_capital, 2),
        market_value=round(market_value, 2),
        realised_pnl=round(realised, 2),
        unrealised_pnl=round(unrealised, 2),
        total_pnl=round(total, 2),
        portfolio_return_pct=round(total / capital_base * 100, 4) if capital_base else 0.0,
        initial_risk=round(initial_risk, 2),
        open_risk_to_stops=round(open_risk, 2),
        open_positions=len(live),
        pending_setups=sum(p.state in {TradeState.WATCH, TradeState.READY} for p in committed),
    )
