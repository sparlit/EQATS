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


"""Telegram Message 2: persistent V2 position lifecycle report."""

from datetime import date
from typing import TYPE_CHECKING

import pandas as pd

from .lifecycle import Position, TradeState
from .preview import HORIZON_LABELS
from .v3_telegram import currency, text, ticker

if TYPE_CHECKING:
    from collections.abc import Iterable


def _price(value: float | None) -> str:
    return currency(value)


def _sessions_held(position: Position, trade_date: str) -> int:
    start, end = pd.Timestamp(position.created_date), pd.Timestamp(trade_date)
    return max(0, len(pd.bdate_range(start, end)) - 1)


def _current_r(position: Position) -> str:
    if position.last_price is None or position.initial_stop >= position.entry:
        return "-"
    return f"{(position.last_price - position.entry) / (position.entry - position.initial_stop):+.2f}R"


def _pnl(position: Position) -> tuple[float, float]:
    unrealised = position.remaining_quantity * ((position.last_price or position.entry) - position.entry)
    return position.realised_pnl, unrealised


def _action(position: Position) -> str:
    actions = {
        TradeState.WATCH: "Wait. The setup is being monitored; do not enter yet.",
        TradeState.READY: "Buy only after the entry trigger is reached.",
        TradeState.OPEN: "No change. The original protective stop remains active.",
        TradeState.PARTIAL: "Target 1 is complete. Hold the balance with the current stop.",
        TradeState.TRAILING: "Hold while price remains above the trailing stop.",
        TradeState.CLOSED: f"Closed — {position.reason.replace('_', ' ')}.",
        TradeState.CANCELLED: "Cancelled before entry; do not buy this setup.",
    }
    return actions[position.state]


def render_portfolio_message(positions: Iterable[Position], trade_date: str) -> str:
    rows = sorted(positions, key=lambda p: (p.created_date, p.symbol, p.trade_id))
    active = [p for p in rows if p.state not in {TradeState.CLOSED, TradeState.CANCELLED}]
    pending = [p for p in active if p.state in {TradeState.WATCH, TradeState.READY}]
    lines = [
        "🧭 <b>NSE V3 — PORTFOLIO LIFECYCLE</b>",
        f"<b>Data:</b> {text(trade_date)} EOD",
        f"Open Positions: {len(active)} | Pending Setups: {len(pending)}",
        "",
        "━━━━━━━━━━━━━━━━━━",
    ]
    if not rows:
        return "\n".join([*lines, "No active positions or lifecycle changes today."])

    for position in rows:
        quantity = f"{position.remaining_quantity:g}/{position.quantity:g} open"
        realised, unrealised = _pnl(position)
        lines.extend(
            [
                f"Trade ID: {position.trade_id}",
                f"Symbol: {ticker(position.symbol)}",
                f"Horizon: {HORIZON_LABELS.get(position.horizon, position.horizon)}",
                f"Progression: {position.progression_stage}",
                f"State: {position.state.value}",
                "",
                f"Entry: {_price(position.entry)} | Current Close: {_price(position.last_price)}",
                f"Initial Stop: {_price(position.initial_stop)} | Current Stop: {_price(position.stop)}",
                f"Target 1: {_price(position.target1)} | Target 2: {_price(position.target2)}",
                f"Current R: {_current_r(position)} | Holding Period: {_sessions_held(position, trade_date)} sessions",
                f"Quantity: {quantity}",
                f"Realised P&L: {_price(realised)} | Unrealised P&L: {_price(unrealised)}",
                "",
                f"Action: {_action(position)}",
                "━━━━━━━━━━━━━━━━━━",
            ]
        )
    return "\n".join(lines)


def positions_for_message(before: Iterable[Position], after: Iterable[Position]) -> list[Position]:
    """Include every active position plus positions closed/cancelled on this run."""
    previous = {p.trade_id: p for p in before}
    return [
        p for p in after if p.state not in {TradeState.CLOSED, TradeState.CANCELLED} or previous.get(p.trade_id) != p
    ]
