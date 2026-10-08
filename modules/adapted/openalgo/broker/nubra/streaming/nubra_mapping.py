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
Nubra exchange mapping and capability registry for WebSocket streaming.
"""

from utils.logging import get_logger

logger = get_logger(__name__)


class NubraExchangeMapper:
    """Maps OpenAlgo exchange codes to Nubra-specific exchanges."""

    # OpenAlgo exchange -> Nubra WebSocket exchange.
    # Nubra sends the exchange at the message level and accepts exactly
    # NSE, BSE and MCX (SDK ExchangeEnum). NSE/BSE derivatives ride on their
    # cash exchange; MCX is its own message-level exchange and must NOT be
    # folded into NSE, or the subscribe is silently accepted and never ticks.
    EXCHANGE_MAP = {
        "NSE": "NSE",
        "BSE": "BSE",
        "NFO": "NSE",
        "BFO": "BSE",
        "MCX": "MCX",
        "NSE_INDEX": "NSE",
        "BSE_INDEX": "BSE",
    }

    @staticmethod
    def to_nubra_exchange(exchange: str) -> str:
        """
        Convert OpenAlgo exchange to Nubra exchange.

        Unmapped exchanges still fall back to NSE so a subscribe never hard
        fails, but the fallback is logged: Nubra accepts an unknown-for-that-
        exchange symbol without an error and simply never sends a tick, so a
        silent fallback surfaces only as "connected but no data".
        """
        nubra_exchange = NubraExchangeMapper.EXCHANGE_MAP.get(exchange)
        if nubra_exchange is None:
            logger.warning(
                f"Exchange {exchange!r} is not mapped for Nubra streaming; "
                f"falling back to NSE. Nubra supports NSE, BSE and MCX only, "
                f"so ticks for this symbol will likely never arrive."
            )
            return "NSE"
        return nubra_exchange

    @staticmethod
    def is_index_exchange(exchange: str) -> bool:
        """Check if the exchange is an index exchange."""
        return exchange in ("NSE_INDEX", "BSE_INDEX")


class NubraCapabilityRegistry:
    """Registry of Nubra broker's streaming capabilities."""

    exchanges = ["NSE", "BSE", "NFO", "BFO", "MCX"]
    subscription_modes = [1, 2, 3]  # 1: LTP, 2: Quote, 3: Depth
    depth_support = {
        "NSE": [5],
        "BSE": [5],
        "NFO": [5],
        "BFO": [5],
        "MCX": [5],
    }

    @classmethod
    def get_supported_depth_levels(cls, exchange: str) -> list:
        return cls.depth_support.get(exchange, [5])

    @classmethod
    def is_depth_level_supported(cls, exchange: str, depth_level: int) -> bool:
        return depth_level in cls.get_supported_depth_levels(exchange)

    @classmethod
    def get_fallback_depth_level(cls, exchange: str, requested_depth: int) -> int:
        supported = cls.get_supported_depth_levels(exchange)
        fallbacks = [d for d in supported if d <= requested_depth]
        return max(fallbacks) if fallbacks else 5
