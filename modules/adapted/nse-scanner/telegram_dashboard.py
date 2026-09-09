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


"""Shared Telegram dashboard links and plain-language status labels."""

import os
from urllib.parse import urlencode

DEFAULT_DASHBOARD_URL = "https://jayeshsrathod.github.io/nse-scanner/"

STATUS_LABELS = {
    "EARLY": "Early watchlist",
    "EARLY_RADAR": "Early watchlist",
    "CONFIRMING": "Watchlist—wait for confirmation",
    "READY": "Watch for entry",
    "NEW_TRIGGER": "New simulated position",
    "NEWLY_QUALIFIED": "New simulated position",
    "OPEN": "Open simulated position",
    "EXTENDED": "Wait for pullback",
    "CIRCUIT_LOCKED": "No entry—circuit risk",
    "WAIT": "No action yet",
    "WEAK": "No action yet",
}

STATUS_ICONS = {
    "EARLY": "🔵",
    "EARLY_RADAR": "🔵",
    "CONFIRMING": "🟡",
    "READY": "🟢",
    "NEW_TRIGGER": "🟢",
    "NEWLY_QUALIFIED": "🟢",
    "OPEN": "🟢",
    "EXTENDED": "🟠",
    "CIRCUIT_LOCKED": "🔴",
    "WAIT": "⚪",
    "WEAK": "⚪",
}


def status_label(state: object, default: str = "No action yet") -> str:
    return STATUS_LABELS.get(str(state or "").upper(), default)


def status_icon(state: object, default: str = "⚪") -> str:
    return STATUS_ICONS.get(str(state or "").upper(), default)


def dashboard_url(scanner: str) -> str:
    base = os.getenv("NSE_MINI_APP_URL", DEFAULT_DASHBOARD_URL).strip() or DEFAULT_DASHBOARD_URL
    separator = "&" if "?" in base else "?"
    return f"{base}{separator}{urlencode({'startapp': scanner})}"


def dashboard_keyboard(scanner: str) -> dict:
    return {
        "inline_keyboard": [
            [
                {"text": "📊 Open Scanner Dashboard", "url": dashboard_url(scanner)},
            ]
        ]
    }
