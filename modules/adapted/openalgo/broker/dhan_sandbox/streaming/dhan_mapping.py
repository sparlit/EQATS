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
Mapping utilities for Dhan broker integration.
Provides exchange code mappings between OpenAlgo and Dhan formats.
"""


# Exchange code mappings
# OpenAlgo exchange code -> Dhan exchange code
OPENALGO_TO_DHAN_EXCHANGE = {
    "NSE": "NSE_EQ",
    "BSE": "BSE_EQ",
    "NFO": "NSE_FNO",
    "BFO": "BSE_FNO",
    "CDS": "NSE_CURRENCY",
    "BCD": "BSE_CURRENCY",
    "MCX": "MCX_COMM",
    "NCO": "NSE_COMM",  # NSE Commodity (undocumented but API-accepted)
    "NSE_INDEX": "IDX_I",
    "BSE_INDEX": "IDX_I",
}

# Dhan exchange code -> OpenAlgo exchange code
DHAN_TO_OPENALGO_EXCHANGE = {v: k for k, v in OPENALGO_TO_DHAN_EXCHANGE.items()}


def get_dhan_exchange(openalgo_exchange: str) -> str:
    """
    Convert OpenAlgo exchange code to Dhan exchange code.

    Args:
        openalgo_exchange (str): Exchange code in OpenAlgo format

    Returns:
        str: Exchange code in Dhan format
    """
    return OPENALGO_TO_DHAN_EXCHANGE.get(openalgo_exchange, openalgo_exchange)


def get_openalgo_exchange(dhan_exchange: str) -> str:
    """
    Convert Dhan exchange code to OpenAlgo exchange code.

    Args:
        dhan_exchange (str): Exchange code in Dhan format

    Returns:
        str: Exchange code in OpenAlgo format
    """
    return DHAN_TO_OPENALGO_EXCHANGE.get(dhan_exchange, dhan_exchange)
