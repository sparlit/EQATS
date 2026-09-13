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


"""PAPER-only card rendering for the opt-in multi-horizon preview."""

from html import escape

from telegram_dashboard import status_icon, status_label

# Kept for compatibility with callers/tests; validation now has one compact
# explanatory message instead of a second public candidate watchlist.
MAX_MESSAGE_CHARS = 3850


def _score(row: dict, horizon: str) -> str:
    value = row.get(f"score_{horizon.lower()}")
    return f"{float(value):.0f}" if value is not None else "—"


def _card(row: dict) -> str:
    symbol = escape(str(row["symbol"]))
    url = f"https://www.tradingview.com/chart/?symbol=NSE%3A{symbol}"
    confirmations = ", ".join(row.get("confirming_horizons") or []) or "none"
    levels = row.get("trade_levels") or {}
    trigger = levels.get("entry_trigger")
    atr = float(row.get("atr", 0) or 0)
    if levels.get("eligible_for_paper") and trigger:
        entry = f"₹{float(trigger):,.2f}–₹{float(trigger) + 0.15 * atr:,.2f}"
        state = (
            "READY"
            if str(row.get("lifecycle_status")) in {"NEW_TRIGGER", "NEWLY_QUALIFIED", "UPGRADED"}
            else "CONFIRMING"
        )
    else:
        entry = "Awaiting valid structure"
        state = "WAIT"
    reason = (
        "Multi-horizon strength • confirmation present"
        if confirmations != "none"
        else "Primary horizon qualified • confirmation pending"
    )
    return "\n".join(
        [
            "━━━━━━━━━━━━━━",
            f'{status_icon(state)} <b><a href="{url}">{symbol}</a> • {status_label(state)} • {float(row.get("primary_score", 0)):.0f}/100</b>',
            f"Entry: {entry}",
            f"CMP ₹{float(row.get('close', 0)):,.2f}",
            f"Context: {escape(reason)} • {escape(str(row.get('primary_horizon', '—')))} primary • ATR {float(row.get('atr_pct', 0)):.1f}%",
            "Next: Await executable closed-bar confirmation",
            "PAPER ONLY — SHADOW VALIDATION",
        ]
    )


def render_messages(report: dict) -> list[str]:
    """Render the experimental comparison in the dedicated validation topic."""
    shadow = report.get("multi_horizon_shadow", {})
    summary = shadow.get("comparison_summary", {})
    observed, target = summary.get("sessions_observed", 0), summary.get("target_sessions", 20)
    remaining = max(0, target - observed)
    status = "Ready for manual review" if summary.get("validation_ready") else "Still collecting evidence"
    return [
        "\n".join(
            [
                "⚙️ <b>MOMENTUM LADDER — SYSTEM VALIDATION</b>",
                "ADMINISTRATIVE COMPARISON • NOT A WATCHLIST",
                f"Data: {escape(str(shadow.get('as_of_date', 'N/A')))} EOD",
                "",
                f"Progress: {observed}/{target} sessions ({remaining} remaining)",
                f"Average setups: main watchlist {summary.get('average_baseline_candidates', 0)} | experimental model {summary.get('average_shadow_candidates', 0)}",
                f"Average overlap: {summary.get('average_overlap', 0)}",
                "",
                f"Status: <b>{status}</b>",
                "What this means: this compares two research models. It does not alter today’s watchlist or create orders.",
            ]
        )
    ]
