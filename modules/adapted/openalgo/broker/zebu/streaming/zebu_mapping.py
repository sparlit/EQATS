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
Zebu-specific mapping utilities for the WebSocket adapter
"""


class ZebuExchangeMapper:
    """Maps between OpenAlgo exchange names and Zebu exchange codes"""

    # OpenAlgo to Zebu exchange mapping (same as Flattrade/Noren)
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

    # Reverse mapping
    ZEBU_TO_OPENALGO = {v: k for k, v in EXCHANGE_MAP.items()}

    @classmethod
    def to_zebu_exchange(cls, oa_exchange: str) -> str | None:
        """Convert OpenAlgo exchange to Zebu exchange format"""
        return cls.EXCHANGE_MAP.get(oa_exchange.upper())

    @classmethod
    def to_oa_exchange(cls, zebu_exchange: str) -> str | None:
        """Convert Zebu exchange to OpenAlgo exchange format"""
        return cls.ZEBU_TO_OPENALGO.get(zebu_exchange.upper())


class ZebuCapabilityRegistry:
    """Registry for Zebu-specific capabilities and limits"""

    # Supported subscription modes
    SUPPORTED_MODES = {1, 2, 3}  # LTP, Quote, Depth

    # Depth level support (Zebu only supports 5-level depth)
    SUPPORTED_DEPTH_LEVELS = {5}

    # Maximum subscriptions per connection
    MAX_SUBSCRIPTIONS = 5000  # Conservative limit

    # Maximum instruments per request
    MAX_INSTRUMENTS_PER_REQUEST = 50

    @classmethod
    def is_mode_supported(cls, mode: int) -> bool:
        """Check if a subscription mode is supported"""
        return mode in cls.SUPPORTED_MODES

    @classmethod
    def is_depth_level_supported(cls, depth_level: int) -> bool:
        """Check if a depth level is supported"""
        return depth_level in cls.SUPPORTED_DEPTH_LEVELS

    @classmethod
    def get_fallback_depth_level(cls, requested_depth: int) -> int:
        """Get the fallback depth level (always 5 for Zebu)"""
        return 5

    @classmethod
    def get_capabilities(cls) -> dict[str, any]:
        """Get all capabilities"""
        return {
            "supported_modes": list(cls.SUPPORTED_MODES),
            "supported_depth_levels": list(cls.SUPPORTED_DEPTH_LEVELS),
            "max_subscriptions": cls.MAX_SUBSCRIPTIONS,
            "max_instruments_per_request": cls.MAX_INSTRUMENTS_PER_REQUEST,
        }
