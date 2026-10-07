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


"""Trend following (ported from the legacy SignalEngine; shadow-only in month 1, plan D8)."""


from dataclasses import dataclass, field

from src.domain.types import Side
from src.features.technical import Features
from src.strategies.base import Detection, StrategyParams, reason


@dataclass(frozen=True)
class TrendFollowing:
    """ADX above the trend threshold, DI in the direction, close beyond EMA 21."""

    params: StrategyParams = field(default_factory=StrategyParams)
    name: str = "trend_following"
    rsi_contrarian: bool = False

    def detect(self, f: Features) -> Detection | None:
        adx, plus, minus, ema21 = f.adx_14, f.plus_di_14, f.minus_di_14, f.ema.get(21)
        if adx is None or plus is None or minus is None or ema21 is None:
            return None
        p = self.params
        if adx <= p.adx_trend:
            return None
        base = 0.8 if adx > p.adx_strong else 0.6
        facts = (reason("adx_14", adx, "trending"), reason("plus_di_14", plus),
                 reason("minus_di_14", minus), reason("ema_21", ema21))  # fmt: skip
        if plus > minus and f.close > ema21:
            return Detection(Side.BUY, base, facts)
        if minus > plus and f.close < ema21:
            return Detection(Side.SELL, base, facts)
        return None
