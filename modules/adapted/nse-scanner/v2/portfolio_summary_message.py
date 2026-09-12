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


"""Telegram Message 3: consolidated portfolio P&L and risk."""

from typing import TYPE_CHECKING

from .lifecycle import Position, TradeState
from .v3_telegram import currency, percent, text, ticker

if TYPE_CHECKING:
    from .portfolio_performance import PortfolioSnapshot


def render_portfolio_summary(
    snapshot: PortfolioSnapshot,
    previous_total_pnl: float | None = None,
    positions: list[Position] | None = None,
) -> str:
    daily_change = snapshot.total_pnl - previous_total_pnl if previous_total_pnl is not None else None
    rows = positions or []
    live = [row for row in rows if row.state in {TradeState.OPEN, TradeState.PARTIAL, TradeState.TRAILING}]
    returns = {
        row.symbol: ((row.last_price or row.entry) - row.entry) / row.entry * 100.0 for row in live if row.entry > 0
    }
    r_values = [
        ((row.last_price or row.entry) - row.entry) / (row.entry - row.initial_stop)
        for row in live
        if row.entry > row.initial_stop
    ]
    winners = sum(value > 0.05 for value in returns.values())
    losers = sum(value < -0.05 for value in returns.values())
    flat = len(returns) - winners - losers
    best = max(returns.items(), key=lambda item: item[1]) if returns else None
    worst = min(returns.items(), key=lambda item: item[1]) if returns else None
    horizon_pnl: dict[str, float] = {}
    for row in rows:
        pnl = row.realised_pnl + row.remaining_quantity * ((row.last_price or row.entry) - row.entry)
        horizon_pnl[row.progression_stage] = horizon_pnl.get(row.progression_stage, 0.0) + pnl
    lines = [
        "💼 <b>NSE V3 — DAILY PORTFOLIO SUMMARY</b>",
        f"<b>Data:</b> {text(snapshot.portfolio_date)} EOD",
        "",
        f"Capital Base: {currency(snapshot.capital_base)}",
        f"Committed Capital: ₹{snapshot.committed_capital:,.2f}",
        f"Current Market Value: ₹{snapshot.market_value:,.2f}",
        f"Realised P&L: ₹{snapshot.realised_pnl:,.2f}",
        f"Unrealised P&L: ₹{snapshot.unrealised_pnl:,.2f}",
        f"Total P&L: ₹{snapshot.total_pnl:,.2f}",
        f"Daily Change: {currency(daily_change)}",
        f"Portfolio Return: {snapshot.portfolio_return_pct:+.2f}%",
        "",
        f"Open Positions: {snapshot.open_positions}",
        f"Pending Setups: {snapshot.pending_setups}",
        f"Initial Risk: ₹{snapshot.initial_risk:,.2f}",
        f"Open Risk to Stops: ₹{snapshot.open_risk_to_stops:,.2f}",
        f"Total / Average R: {sum(r_values):+.2f}R / {(sum(r_values) / len(r_values) if r_values else 0):+.2f}R",
        f"Winners / Losers / Flat: {winners} / {losers} / {flat}",
        f"Best: {ticker(best[0])} {percent(best[1])} | Worst: {ticker(worst[0])} {percent(worst[1])}"
        if best and worst
        else "Best / Worst: N/A (no open positions)",
    ]
    if horizon_pnl:
        lines.extend(["", "Horizon P&L"])
        lines.extend(f"{stage}: ₹{pnl:,.2f}" for stage, pnl in sorted(horizon_pnl.items()))
    return "\n".join(lines)
