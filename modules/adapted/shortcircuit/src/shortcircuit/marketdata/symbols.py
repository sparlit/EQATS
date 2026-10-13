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
Central symbol registry for Fyers API
All symbols MUST use Fyers exact format
"""

# INDICES
NIFTY_50 = "NSE:NIFTY50-INDEX"
BANK_NIFTY = "NSE:NIFTYBANK-INDEX"
FIN_NIFTY = "NSE:FINNIFTY-INDEX"
MIDCAP_NIFTY = "NSE:NIFTYMID50-INDEX"

# Reference index
# Default index for market regime detection
DEFAULT_INDEX = NIFTY_50


# Symbol validation
def validate_symbol(symbol: str) -> bool:
    """
    Validate symbol format for Fyers API

    Args:
        symbol: Symbol string to validate

    Returns:
        True if valid Fyers symbol format

    Examples:
        >>> validate_symbol('NSE:SBIN-EQ')
        True
        >>> validate_symbol('SBIN')
        False
    """
    if not symbol:
        return False

    # Must contain exchange:symbol-type format
    parts = symbol.split(":")
    if len(parts) != 2:
        return False

    exchange, instrument = parts

    # Must have hyphen for instrument type
    # Actually Fyers format is EXCHANGE:SYMBOL-SERIES for Equities e.g. NSE:SBIN-EQ
    # For Indices: NSE:NIFTY50-INDEX
    # So hyphen check is good for most, but let's be lenient if needed.
    # The PRD says "Must have hyphen for instrument type"
    return "-" in instrument


import calendar
from datetime import datetime, timedelta


def _last_thursday(year: int, month: int) -> datetime:
    """Return the last Thursday of the given month."""
    last_day = calendar.monthrange(year, month)[1]
    d = datetime(year, month, last_day)
    while d.weekday() != 3:  # 3 = Thursday
        d -= timedelta(days=1)
    return d
