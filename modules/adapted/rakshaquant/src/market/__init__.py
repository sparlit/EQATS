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


"""Market data module for real-time data ingestion and processing.

Provides:
- Market data feeds (YFinance, simulated, live)
- Technical indicator calculations
- Signal generation engine
- Position sizing calculations
"""

from .data_feed import MarketDataFeed
from .indicators import calculate_indicators
from .signals import SignalEngine
from .sizing import (
    PositionSizer,
    PositionSizeResult,
    calculate_portfolio_heat,
    calculate_position_size,
)

__all__ = [
    "MarketDataFeed",
    "PositionSizeResult",
    # Position sizing
    "PositionSizer",
    "SignalEngine",
    "calculate_indicators",
    "calculate_portfolio_heat",
    "calculate_position_size",
]
