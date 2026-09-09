from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Any

import pytz


def is_ist_market_session_active(dt: datetime.datetime | None = None) -> bool:
    """Checks whether current or provided time falls within NSE/BSE IST market session (09:15 to 15:30 IST Mon-Fri)."""
    ist = pytz.timezone("Asia/Kolkata")
    if dt is None:
        now = datetime.datetime.now(ist)
    else:
        if dt.tzinfo is None:
            # Assume naive datetime is in IST
            now = ist.localize(dt)
        else:
            now = dt.astimezone(ist)
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


@dataclass(frozen=True)
class StrategyConfig:
    """Immutable parameter set for a strategy.

    Subclass to declare typed parameters::

        @dataclass(frozen=True)
        class SmaCrossConfig(StrategyConfig):
            fast_period: int = 10
            slow_period: int = 30

    ``params`` is a free-form escape hatch for callers that parameterize
    strategies generically (e.g. parameter sweeps) without declaring a
    config subclass.
    """

    params: dict[str, Any] = field(default_factory=dict)

    #: Prefix for auto-generated client order ids (``"{tag}-{seq}"``).
    order_id_tag: str = "O"