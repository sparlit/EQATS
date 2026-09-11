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
skills/example_skill.py
────────────────────────
EXAMPLE: How to write a custom skill plugin for india-trade-cli.

This file is intentionally prefixed with "example_" so it is NOT
auto-loaded at startup. Rename or copy it (without the "example_" prefix)
to a new file in this directory to register it automatically.

Steps:
1. Copy this file:   cp skills/example_skill.py skills/my_skill.py
2. Edit SKILL dict:  update name, description, parameters, fn
3. Restart the CLI:  the skill will be auto-discovered and registered.
"""


def _get_sector_news(symbol: str, count: int = 3) -> dict:
    """
    Example implementation: return placeholder sector news.
    Replace with your own data source or API call.
    """
    return {
        "symbol": symbol.upper(),
        "headlines": [f"[Placeholder] Headline {i + 1} for {symbol.upper()}" for i in range(count)],
        "count": count,
    }


# ── SKILL descriptor ──────────────��──────────────────────────
# This is the only export that skill_loader.py looks for.

SKILL = {
    "name": "example_sector_news",
    "description": "Fetch the latest sector news headlines for a symbol (example plugin).",
    "parameters": {
        "type": "object",
        "properties": {
            "symbol": {
                "type": "string",
                "description": "NSE/BSE ticker symbol, e.g. INFY",
            },
            "count": {
                "type": "integer",
                "description": "Number of headlines to return (default: 3)",
                "default": 3,
            },
        },
        "required": ["symbol"],
    },
    "fn": _get_sector_news,
    "is_read_only": True,
    "is_destructive": False,
}
