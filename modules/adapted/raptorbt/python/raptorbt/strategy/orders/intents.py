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


"""Order intents emitted by strategies.

Intents describe what the strategy wants; the engine decides fills, sizing
against available capital, lot rounding, and fees.
"""


from dataclasses import dataclass


@dataclass(frozen=True)
class MarketOrder:
    """Open a position at the next fill price in the session's direction.

    Attributes:
        size_frac: Fraction of available capital to deploy (0, 1]. ``None``
            deploys all available capital.
        stop_price: Explicit stop price for the new position, overriding any
            configured stop model.
        target_price: Explicit target price for the new position, overriding
            any configured target model.
    """

    size_frac: float | None = None
    stop_price: float | None = None
    target_price: float | None = None


@dataclass(frozen=True)
class ClosePosition:
    """Close the open position at the next fill price."""
