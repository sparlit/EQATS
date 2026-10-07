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


"""Mean reversion (ported from the legacy SignalEngine): Bollinger-band extremes with RSI."""


from dataclasses import dataclass, field

from src.domain.types import Side
from src.features.technical import Features
from src.strategies.base import Detection, StrategyParams, reason


@dataclass(frozen=True)
class MeanReversion:
    """BUY: close at/below the lower band (stronger when RSI is oversold). SELL: the mirror."""

    params: StrategyParams = field(default_factory=StrategyParams)
    name: str = "mean_reversion"
    rsi_contrarian: bool = True  # a low RSI supports the BUY

    def detect(self, f: Features) -> Detection | None:
        lower, upper, rsi = f.bb_lower, f.bb_upper, f.rsi_14
        if lower is None or upper is None or rsi is None:
            return None
        p = self.params
        if f.close <= lower:
            oversold = rsi < p.rsi_oversold
            return Detection(Side.BUY, 0.75 if oversold else 0.5, (
                reason("close_vs_bb_lower", f.close - lower, "at/below the lower band"),
                reason("rsi_14", rsi, "oversold" if oversold else ""),
            ))  # fmt: skip
        if f.close >= upper:
            overbought = rsi > p.rsi_overbought
            return Detection(Side.SELL, 0.75 if overbought else 0.5, (
                reason("close_vs_bb_upper", f.close - upper, "at/above the upper band"),
                reason("rsi_14", rsi, "overbought" if overbought else ""),
            ))  # fmt: skip
        return None
