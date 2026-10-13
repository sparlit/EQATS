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
TradeSmart-specific mapping utilities for the WebSocket adapter
"""


class TradeSmartExchangeMapper:
    """Maps between OpenAlgo exchange names and TradeSmart (Noren) exchange codes."""

    EXCHANGE_MAP = {
        "NSE": "NSE",
        "BSE": "BSE",
        "NFO": "NFO",
        "BFO": "BFO",
        "MCX": "MCX",
        "CDS": "CDS",
        "NSE_INDEX": "NSE",  # Indices stream on the parent cash exchange
        "BSE_INDEX": "BSE",
    }

    FROM_TRADESMART = {v: k for k, v in EXCHANGE_MAP.items()}

    @classmethod
    def to_tradesmart_exchange(cls, oa_exchange: str) -> str | None:
        return cls.EXCHANGE_MAP.get(oa_exchange.upper())

    @classmethod
    def to_oa_exchange(cls, ts_exchange: str) -> str | None:
        return cls.FROM_TRADESMART.get(ts_exchange.upper())


class TradeSmartCapabilityRegistry:
    """Registry for TradeSmart streaming capabilities and limits."""

    SUPPORTED_MODES = {1, 2, 3}  # LTP, Quote, Depth
    SUPPORTED_DEPTH_LEVELS = {5}  # Noren feed is 5-level
    MAX_SUBSCRIPTIONS = 5000
    MAX_INSTRUMENTS_PER_REQUEST = 50

    @classmethod
    def is_mode_supported(cls, mode: int) -> bool:
        return mode in cls.SUPPORTED_MODES

    @classmethod
    def is_depth_level_supported(cls, depth_level: int) -> bool:
        return depth_level in cls.SUPPORTED_DEPTH_LEVELS

    @classmethod
    def get_supported_depth_levels(cls) -> list:
        return list(cls.SUPPORTED_DEPTH_LEVELS)

    @classmethod
    def get_fallback_depth_level(cls, requested_depth: int) -> int:
        return 5

    @classmethod
    def get_capabilities(cls) -> dict:
        return {
            "supported_modes": list(cls.SUPPORTED_MODES),
            "supported_depth_levels": list(cls.SUPPORTED_DEPTH_LEVELS),
            "max_subscriptions": cls.MAX_SUBSCRIPTIONS,
            "max_instruments_per_request": cls.MAX_INSTRUMENTS_PER_REQUEST,
        }
