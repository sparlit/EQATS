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


"""Breakout (ported from the legacy SignalEngine; shadow-only in month 1, plan D8)."""


from dataclasses import dataclass, field

from src.domain.types import Side
from src.features.technical import Features
from src.strategies.base import Detection, StrategyParams, reason


@dataclass(frozen=True)
class Breakout:
    """A Bollinger squeeze (narrow bands) with the close outside a band."""

    params: StrategyParams = field(default_factory=StrategyParams)
    name: str = "breakout"
    rsi_contrarian: bool = False

    def detect(self, f: Features) -> Detection | None:
        width, upper, lower = f.bb_width, f.bb_upper, f.bb_lower
        if width is None or upper is None or lower is None or width >= self.params.bb_squeeze:
            return None
        squeeze = reason("bb_width", width, "squeeze")
        if f.close > upper:
            return Detection(Side.BUY, 0.7, (squeeze, reason("bb_upper", upper, "closed above")))
        if f.close < lower:
            return Detection(Side.SELL, 0.7, (squeeze, reason("bb_lower", lower, "closed below")))
        return None
