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


"""On-demand V2 portfolio P&L and risk report rendering."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .portfolio_performance import PortfolioSnapshot


def _money(value: float) -> str:
    sign = "+" if value > 0 else ""
    return f"{sign}₹{value:,.2f}"


def render_portfolio_summary(snapshot: PortfolioSnapshot) -> str:
    """Return a concise report suitable for the future /portfolio command."""
    return "\n".join(
        [
            "💰 KJ V2 PORTFOLIO SUMMARY",
            f"Date: {snapshot.portfolio_date}",
            "━━━━━━━━━━━━━━━━━━",
            f"Capital Base: ₹{snapshot.capital_base:,.2f}",
            f"Committed Capital: ₹{snapshot.committed_capital:,.2f}",
            f"Current Equity: ₹{snapshot.capital_base + snapshot.total_pnl:,.2f}",
            f"Realised P&L: {_money(snapshot.realised_pnl)}",
            f"Unrealised P&L: {_money(snapshot.unrealised_pnl)}",
            f"Total P&L: {_money(snapshot.total_pnl)} ({snapshot.portfolio_return_pct:+.2f}%)",
            "",
            f"Open Positions: {snapshot.open_positions} | Pending Setups: {snapshot.pending_setups}",
            f"Initial Risk Committed: ₹{snapshot.initial_risk:,.2f}",
            f"Remaining Loss Risk to Stops: ₹{snapshot.open_risk_to_stops:,.2f}",
            "",
            "P&L is based on recorded V2 entries, partial exits and closing prices.",
        ]
    )
