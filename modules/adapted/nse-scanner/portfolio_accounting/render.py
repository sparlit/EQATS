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


"""Identical portfolio vocabulary with bounded Telegram-compatible pages."""

from html import escape
from urllib.parse import quote

from telegram_dashboard import dashboard_url


def render_messages(snapshot: dict, limit: int = 3400) -> list[str]:
    def money(value):
        return f"₹{value:,.2f}"

    s = snapshot
    header = (
        f"<b>{escape(s['scanner'])} — PAPER PORTFOLIO</b>\nData: {escape(s['as_of_date'])} EOD\n"
    )
    blocks = [
        "\n".join(
            [
                f"Starting capital: {money(s['starting_capital'])}",
                f"Available cash: {money(s['available_cash'])}",
                f"Invested capital: {money(s['invested_capital'])}",
                f"Pending reservations: {money(s['reserved_capital'])} (not invested)",
                f"Holdings value: {money(s['market_value'])}",
                f"Booked P&L: {money(s['realised_pnl'])}",
                f"Open P&L: {money(s['unrealised_pnl'])}",
                f"Recorded fees: {money(s['fees'])}",
                f"Total P&L: {money(s['total_pnl'])} ({s['return_pct']:+.2f}%)",
                f"Total equity: {money(s['equity'])}",
                f"Open: {s['open_positions']} | Closed: {s['closed_positions']} | Pending: {s['pending_setups']}",
                escape(s["cost_basis"]),
                f"Evidence: {escape(s['provenance'])}",
            ]
        )
    ]
    if not s["positions"]:
        blocks.append("No recorded simulated fills in this accounting ledger.")
    for p in s["positions"]:

        def value(key):
            return money(p[key]) if p.get(key) is not None else "Not recorded"

        action = (
            "Review holding and valuation"
            if p["status"] == "REVIEW"
            else "Position closed"
            if not p["remaining_quantity"]
            else "Follow the scanner's current stop and exit rules"
        )
        lines = [
            f"<b>{escape(p['symbol'])}</b> — {escape(p['status'])}",
            f"Entry: {value('entry')} | Date: {escape(str(p.get('entry_date') or 'Not recorded'))}",
            f"Quantity: {p['quantity']:g} | Remaining: {p['remaining_quantity']:g}",
            f"Current price: {value('last_price')} | Mark: {escape(str(p.get('mark_date') or 'Not recorded'))}",
            f"Initial SL: {value('initial_stop')} | Current SL: {value('stop')}",
            f"T1: {value('target1')} | T2: {value('target2')}",
            f"Booked: {value('realised_pnl')} | Open: {value('unrealised_pnl')}",
            f"Total: {value('total_pnl')} ({p['return_pct']:+.2f}%)",
            f"Next: {action}",
        ]
        if s["scanner"] in {"Penny", "Momentum Ladder"}:
            lines.append(
                f'<a href="https://www.tradingview.com/chart/?symbol=NSE%3A{quote(str(p["symbol"]), safe="")}">📈 Open {escape(str(p["symbol"]))} chart</a>'
            )
        blocks.append("\n".join(lines))
    if s["pending_setups"]:
        blocks.append("Pending entries are tracked separately and contribute no P&L.")
    blocks.extend(escape(w) for w in s["warnings"])
    if s["scanner"] in {"Penny", "Momentum Ladder"}:
        scanner_id = "penny" if s["scanner"] == "Penny" else "ladder"
        blocks.append(
            f'<a href="{escape(dashboard_url(scanner_id), quote=True)}">📊 Open {escape(s["scanner"])} dashboard</a>'
        )
    if s.get("strategy_profile") == "LADDER_DAILY_20260922":
        blocks = [b.replace(" | T2:", " | TP2 reference:") for b in blocks]
        blocks.append(
            "After TP1, follow the stored structural trailing stop. TP2 is a reference, not a forced exit."
        )
    pages, page = [], header
    for block in blocks:
        if len(header + block) > limit:
            raise ValueError("Portfolio block exceeds message limit")
        if len(page + "\n\n" + block) > limit:
            pages.append(page)
            page = header
        page += "\n\n" + block
    pages.append(page)
    return pages
