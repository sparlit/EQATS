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
Regime Spectrum — 5 levels, not binary.
Authorized 2026-09-12 (Feature C, per BACKLOG ID3).

Levels:
  STRONG_BULL  — close > EMA10 by >=2%, EMA10 rising, breadth >= 0.60
  BULL         — close > EMA10 AND EMA20, EMA10 rising
  NEUTRAL      — close > EMA10 (but slope flat/falling) OR above EMA20 only
  WEAK         — close < EMA10 but still > EMA20
  CAPITULATION — close < EMA10 AND < EMA20

Position size multiplier (applied by sizing.py):
  STRONG_BULL  = 1.00
  BULL         = 1.00
  NEUTRAL      = 0.75
  WEAK         = 0.50
  CAPITULATION = 0.25

Strategy allowance:
  STRONG_BULL / BULL  — normal swing + AW + value
  NEUTRAL             — normal swing + AW + value (0.75 size)
  WEAK                — AW only + value (0.50 size)
  CAPITULATION        — AW only + value (0.25 size)
"""
from dataclasses import dataclass

LEVELS = ["STRONG_BULL", "BULL", "NEUTRAL", "WEAK", "CAPITULATION"]

SIZE_MULT = {
    "STRONG_BULL": 1.00,
    "BULL": 1.00,
    "NEUTRAL": 0.75,
    "WEAK": 0.50,
    "CAPITULATION": 0.25,
}

ALLOWS_NORMAL_SWING = {
    "STRONG_BULL": True,
    "BULL": True,
    "NEUTRAL": True,
    "WEAK": False,
    "CAPITULATION": False,
}

ALLOWS_AW = {
    "STRONG_BULL": True,
    "BULL": True,
    "NEUTRAL": True,
    "WEAK": True,
    "CAPITULATION": True,
}


@dataclass
class SpectrumState:
    level: str
    size_mult: float
    allows_swing: bool
    allows_aw: bool
    index_close: float
    ema10: float
    ema20: float
    ema10_slope_pct: float
    symbol: str


def classify(close, ema10, ema20, ema10_slope_pct, breadth_above50=None):
    """Return one of the 5 levels based on price + slope."""
    above10 = close > ema10
    above20 = close > ema20
    rising = ema10_slope_pct > 0
    strong_extra = rising and (close / ema10 - 1) >= 0.02
    if breadth_above50 is not None:
        strong_extra = strong_extra and breadth_above50 >= 0.60

    if above10 and above20 and rising and strong_extra:
        return "STRONG_BULL"
    if above10 and above20 and rising:
        return "BULL"
    if above10 and not above20:
        return "NEUTRAL"
    if above20 and not above10:
        return "WEAK"
    if not above10 and not above20:
        return "CAPITULATION"
    return "NEUTRAL"


def describe(level):
    return {
        "STRONG_BULL": "🟢🟢 STRONG BULL — full size, all strategies",
        "BULL": "🟢 BULL — full size, all strategies",
        "NEUTRAL": "🟡 NEUTRAL — 0.75x size, all strategies",
        "WEAK": "🟠 WEAK — 0.5x size, AW + value only",
        "CAPITULATION": "🔴 CAPITULATION — 0.25x size, AW + value only",
    }.get(level, "⚪ UNKNOWN")
