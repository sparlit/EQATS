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
Shoonya-specific mapping utilities for the WebSocket adapter
"""


class ShoonyaExchangeMapper:
    """Maps between OpenAlgo exchange names and Shoonya exchange codes"""

    # OpenAlgo to Shoonya exchange mapping
    EXCHANGE_MAP = {
        "NSE": "NSE",
        "BSE": "BSE",
        "NFO": "NFO",
        "BFO": "BFO",
        "MCX": "MCX",
        "CDS": "CDS",
        "NSE_INDEX": "NSE",  # Indices use base exchange
        "BSE_INDEX": "BSE",
    }

    # SM-R6-1 fix: Explicit reverse mapping to avoid lossy dict comprehension
    # (NSE_INDEX and BSE_INDEX both map to NSE/BSE in forward map, making
    # the auto-generated reverse map overwrite NSE→NSE with NSE→NSE_INDEX)
    SHOONYA_TO_OPENALGO = {
        "NSE": "NSE",
        "BSE": "BSE",
        "NFO": "NFO",
        "BFO": "BFO",
        "MCX": "MCX",
        "CDS": "CDS",
    }

    @classmethod
    def to_shoonya_exchange(cls, oa_exchange: str) -> str | None:
        """Convert OpenAlgo exchange to Shoonya exchange format"""
        return cls.EXCHANGE_MAP.get(oa_exchange.upper())

    @classmethod
    def to_oa_exchange(cls, shoonya_exchange: str) -> str | None:
        """Convert Shoonya exchange to OpenAlgo exchange format"""
        return cls.SHOONYA_TO_OPENALGO.get(shoonya_exchange.upper())
