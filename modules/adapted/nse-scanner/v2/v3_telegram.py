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


"""Safe, presentation-only primitives for V3 Telegram reports."""

import hashlib
from html import escape
from urllib.parse import quote

MAX_MESSAGE_CHARS = 3400


def text(value: object | None) -> str:
    return "N/A" if value is None or str(value).strip() == "" else escape(str(value))


def currency(value: float | None, decimals: int = 2) -> str:
    return "N/A" if value is None else f"₹{value:,.{decimals}f}"


def percent(value: float | None) -> str:
    return "N/A" if value is None else f"{value:+.2f}%"


def ticker(symbol: object) -> str:
    label = text(symbol).upper()
    raw = str(symbol).strip().upper()
    if not raw or any(char not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789&-" for char in raw):
        return f"<b>{label}</b>"
    return f'<a href="https://www.tradingview.com/chart/?symbol={quote("NSE:" + raw, safe="")}"><b>{label}</b></a>'


def fingerprint(scan_date: str, message_type: str, topic_id: int | None, page: int, body: str) -> str:
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]
    return f"{scan_date}:{message_type}:{topic_id or 'general'}:{page}:{digest}"


def paginate_cards(header: str, cards: list[str], footer: str = "") -> list[str]:
    if not cards:
        return [header + ("\n\n" + footer if footer else "")]
    pages, current = [], header
    for card in cards:
        candidate = f"{current}\n\n{card}"
        if len(candidate) > MAX_MESSAGE_CHARS and current != header:
            pages.append(current)
            current = f"{header}\n\n{card}"
        else:
            current = candidate
    pages.append(current + ("\n\n" + footer if footer else ""))
    if len(pages) == 1:
        return pages
    return [page.replace(header, f"{header} ({index}/{len(pages)})", 1) for index, page in enumerate(pages, 1)]
