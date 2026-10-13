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


# sandbox/__init__.py
"""
Sandbox Mode - API Analyzer Environment

OpenAlgo is an open-source application that provides Sandbox Mode (API Analyzer)
to make it easier for traders to test strategies in a realistic simulated
environment without executing real trades through a broker.

Key Features:
- ₹10,000,000 (1 Crore) starting sandbox capital (configurable)
- Auto reset every Sunday at midnight IST (configurable)
- Real market data integration
- Realistic order execution simulation
- Position and holdings management
- Leverage-based margin calculations
- Auto square-off for MIS positions
- T+1 settlement for CNC holdings
- Self-hosted, transparent, open-source testing environment
"""

__version__ = "1.0.0"
