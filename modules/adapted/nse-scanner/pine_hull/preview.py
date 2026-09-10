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


"""Mobile-first Telegram rendering for the isolated Pine Hull paper system."""

from html import escape
from urllib.parse import quote

from telegram_dashboard import status_icon, status_label


def _number(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _price(value: object) -> str:
    return f"₹{_number(value):,.2f}"


def _rank_badge(rank: int) -> str:
    return {1: "🥇", 2: "🥈", 3: "🥉"}.get(rank, f"#{rank}")


def _ticker(symbol: object) -> str:
    raw = str(symbol).strip().upper()
    label = escape(raw)
    url = f"https://www.tradingview.com/chart/?symbol={quote('NSE:' + raw, safe='')}"
    return f'<a href="{url}"><b>{label}</b></a>'


def _watch_range(item: dict) -> tuple[float, float]:
    close, atr = _number(item.get("close")), _number(item.get("atr14"))
    supports = [_number(item.get(name)) for name in ("hybrid_hull", "hma21") if _number(item.get(name)) > 0]
    center = max(supports) if item.get("overextended") and supports else max(close, max(supports, default=close))
    return max(0.01, center - 0.15 * atr), center + 0.15 * atr


def render_daily_signals(result: dict) -> str:
    """Render Pine Hull signals in the same decision-first style as V2 ACTION.

    Pine remains an independent paper system and is delivered to the dedicated
    Pine Hull Signals topic; only presentation is aligned with the V2 card UX.
    """
    created = list(result.get("created", []))
    watch = list(result.get("watch", []))
    lines = [
        "📐 <b>PINE HULL — DAILY WATCHLIST</b>",
        "<b>SIMULATED WATCHLIST • NO LIVE ORDERS</b>",
        f"{len(created)} new simulated positions • {len(watch)} watchlist setups",
        f"Data: {result.get('trade_date', '-')} close",
        "",
        "Hull55 • HMA21/51 • KAMA30 • ATR14×3.5",
    ]

    if not created:
        lines.extend(["", "✅ Scan completed", "Fresh Signals: 0", "No new qualified Pine Hull entry today."])
    for _rank, position in enumerate(created, 1):
        weekly = "Confirmed" if position.get("htf_weekly_bullish") else "Pending / weak"
        entry = _number(position["entry"])
        entry_high = entry + 0.15 * max(0.0, _number(position.get("target1")) - entry) / 1.5
        lines.extend(
            [
                "",
                "━━━━━━━━━━━━━━",
                f"{status_icon('READY')} {_ticker(position['symbol'])} • <b>Watch for entry • {_number(position.get('score')):.0f}/100</b>",
                f"CMP {_price(position.get('last_price', entry))}",
                "Evidence: Hull pullback continuation • Daily Hull bullish",
                f"Planned entry: {_price(entry)}–{_price(entry_high)}",
                f"SL {_price(position['initial_stop'])} | T1 {_price(position['target1'])} | T2 {_price(position['target2'])}",
                f"Context: Weekly {weekly} • HMA21 > HMA51 • KAMA30 rising",
                "Next: The simulated portfolio will add it only after the trigger is confirmed.",
            ]
        )

    if watch:
        lines.extend(["", f"<b>More watchlist setups • {len(watch)} stocks</b>"])
        for item in watch:
            timing = str(item.get("timing_state", "EARLY"))
            state = "EXTENDED" if item.get("overextended") else "EARLY" if timing == "EARLY" else "CONFIRMING"
            reason = "Hull rising • commitment pending"
            if item.get("overextended"):
                reason = "Extended price • wait for reset"
            elif item.get("chop") or item.get("rotational"):
                state, reason = "WAIT", "Sideways movement • confirmation missing"
            low, high = _watch_range(item)
            lines.extend(
                [
                    "",
                    "━━━━━━━━━━━━━━",
                    f"{status_icon(state)} {_ticker(item['symbol'])} • <b>{status_label(state)} • {_number(item.get('score')):.0f}/100</b>",
                    f"CMP {_price(item.get('close'))}",
                    f"Planned entry: {_price(low)}–{_price(high)}",
                    f"Why it is here: {reason}",
                    "Next: Wait for a confirmed end-of-day signal.",
                ]
            )
        lines.extend(["", "🟢 Watch for entry • 🟡 Wait for confirmation • 🔵 Early watchlist • ⚪ No action yet"])

    return "\n".join(lines)
