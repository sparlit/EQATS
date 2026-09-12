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


"""Render Telegram Portfolio Message 3 from portfolio_health.json."""

from typing import Any

_ACTION_ICON = {
    "HOLD": "✅",
    "WATCH": "👀",
    "REVIEW": "🟠",
    "REDUCE": "🔻",
    "TECHNICAL_EXIT": "🚨",
    "INSUFFICIENT_DATA": "⚪",
}

_RISK_ICON = {"LOW": "🟢", "MEDIUM": "🟡", "HIGH": "🔴", "UNKNOWN": "⚪"}


def render_portfolio_health_message(health: dict[str, Any], max_positions: int = 20) -> str:
    rows = health.get("positions", [])
    if not isinstance(rows, list):
        rows = []

    lines = [
        "🧠 KJ PORTFOLIO INTELLIGENCE",
        f"Health Date: {health.get('generated_date', '-')}",
        (
            f"Positions: {health.get('position_count', len(rows))} | "
            f"Reviewed: {health.get('reviewed_count', 0)} | "
            f"Pending: {health.get('pending_count', 0)}"
        ),
        "",
        "━━━━━━━━━━━━━━━━━━",
    ]

    if not rows:
        return "\n".join([*lines, "No active portfolio positions found."])

    for row in rows[: max(max_positions, 0)]:
        if not isinstance(row, dict):
            continue
        action = str(row.get("suggested_action", "INSUFFICIENT_DATA"))
        risk = str(row.get("risk_status", "UNKNOWN"))
        lines.extend(
            [
                f"{_ACTION_ICON.get(action, '⚪')} {row.get('symbol', '-')}",
                (
                    f"Technical: {row.get('technical_status', 'NOT_REVIEWED')} | "
                    f"Fundamental: {row.get('fundamental_status', 'NOT_REVIEWED')}"
                ),
                f"Risk: {_RISK_ICON.get(risk, '⚪')} {risk} | Action: {action}",
                (f"Reviewed: {row.get('review_date') or 'Pending'} | Confidence: {row.get('confidence_score', 0):g}%"),
                f"View: {row.get('summary', 'No review summary available.')}",
                "━━━━━━━━━━━━━━━━━━",
            ]
        )

    omitted = len(rows) - min(len(rows), max(max_positions, 0))
    if omitted > 0:
        lines.append(f"+ {omitted} additional positions in portfolio_health.json")
    lines.append("AI review supports monitoring only; existing stop-loss rules remain authoritative.")
    return "\n".join(lines)
