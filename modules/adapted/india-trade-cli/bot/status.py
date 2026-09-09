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


"""
bot/status.py
─────────────
Thread-safe shared state for Telegram bot activity.

The REPL prompt reads `get_badge()` on every iteration to show a
persistent indicator when a Telegram command is being processed.
"""


import threading
from typing import Optional

_lock = threading.Lock()
_active_command: str | None = None  # e.g. "/analyze RELIANCE"
_pending_count: int = 0  # how many commands in flight


def set_active(command: str) -> None:
    """Mark a Telegram command as in-flight."""
    global _active_command, _pending_count
    with _lock:
        _active_command = command
        _pending_count += 1


def clear_active() -> None:
    """Mark a Telegram command as finished."""
    global _active_command, _pending_count
    with _lock:
        _pending_count = max(0, _pending_count - 1)
        if _pending_count == 0:
            _active_command = None


def get_badge() -> str:
    """
    Return a short status string for the REPL prompt.

    Returns "" when idle, or something like "📩 /analyze" when busy.
    """
    with _lock:
        if _pending_count == 0:
            return ""
        cmd = _active_command or "cmd"
        # Truncate long commands
        if len(cmd) > 20:
            cmd = cmd[:20] + "…"
        if _pending_count > 1:
            return f" 📩 {cmd} (+{_pending_count - 1})"
        return f" 📩 {cmd}"
