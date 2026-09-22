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
Signal Generator
────────────────
Implements the three strategies from the Product Vision doc (§9):

  1. VWAP Momentum Breakout  – bullish breakout (Buy ATM Call)
  2. Bearish Momentum        – bearish breakdown (Buy ATM Put)
  3. Mean Reversion          – extreme RSI / Bollinger touch

Each strategy returns a Signal dict or None.
The regime detector determines which strategies are active per scan cycle.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("signal_generator")


@dataclass
class Signal:
    """Represents a raw trading signal before ML filtering."""

    strategy: str
    direction: str  # "CALL" or "PUT"
    symbol: str
    entry_price: float
    technical_strength: float  # 0.0 – 1.0, used in final trade score
    details: dict


# ═══════════════════════════════════════════════════════════════════════════════
# Strategy 1: VWAP Momentum Breakout
# ═══════════════════════════════════════════════════════════════════════════════


def vwap_momentum_breakout(row: dict, symbol: str = "") -> Signal | None:
    """
    Entry conditions (from docs):
      - price > VWAP
      - RSI > 55
      - volume spike
      - EMA20 > EMA50

    Trade: Buy ATM Call
    """
    required = ["close", "vwap", "rsi", "ema20", "ema50"]
    if not all(k in row and row[k] is not None for k in required):
        return None

    conditions = {
        "price_above_vwap": row["close"] > row.get("vwap", 0),
        "rsi_above_55": row["rsi"] > 55,
        "ema20_above_ema50": row["ema20"] > row["ema50"],
        "volume_spike": row.get("volume_spike", 0) == 1 or row.get("volume_ratio", 0) > 1.5,
    }

    met = sum(conditions.values())
    # Require at least 3 of 4 conditions (flexible for real markets)
    if met >= 3:
        strength = met / len(conditions)
        return Signal(
            strategy="vwap_momentum_breakout",
            direction="CALL",
            symbol=symbol,
            entry_price=row["close"],
            technical_strength=round(strength, 2),
            details=conditions,
        )
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# Strategy 2: Bearish Momentum
# ═══════════════════════════════════════════════════════════════════════════════


def bearish_momentum(row: dict, symbol: str = "") -> Signal | None:
    """
    Entry conditions (from docs):
      - price < VWAP
      - RSI < 45
      - EMA20 < EMA50
      - volume spike

    Trade: Buy ATM Put
    """
    required = ["close", "vwap", "rsi", "ema20", "ema50"]
    if not all(k in row and row[k] is not None for k in required):
        return None

    conditions = {
        "price_below_vwap": row["close"] < row.get("vwap", float("inf")),
        "rsi_below_45": row["rsi"] < 45,
        "ema20_below_ema50": row["ema20"] < row["ema50"],
        "volume_spike": row.get("volume_spike", 0) == 1 or row.get("volume_ratio", 0) > 1.5,
    }

    met = sum(conditions.values())
    if met >= 3:
        strength = met / len(conditions)
        return Signal(
            strategy="bearish_momentum",
            direction="PUT",
            symbol=symbol,
            entry_price=row["close"],
            technical_strength=round(strength, 2),
            details=conditions,
        )
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# Strategy 3: Mean Reversion
# ═══════════════════════════════════════════════════════════════════════════════


def mean_reversion(row: dict, symbol: str = "") -> Signal | None:
    """
    Entry conditions (from docs):
      - RSI extreme (oversold < 30 or overbought > 70)
      - price far from VWAP
      - Bollinger band touch

    Trade: Counter-trend
      - RSI < 30 → Buy CALL (expect bounce)
      - RSI > 70 → Buy PUT (expect pullback)
    """
    required = ["close", "rsi"]
    if not all(k in row and row[k] is not None for k in required):
        return None

    is_oversold = row["rsi"] < 30
    is_overbought = row["rsi"] > 70

    if not (is_oversold or is_overbought):
        return None

    # Check Bollinger band touch
    bb_lower = row.get("bollinger_lower")
    bb_upper = row.get("bollinger_upper")
    vwap_dist = abs(row.get("vwap_dist", 0))

    conditions = {}

    if is_oversold:
        conditions["rsi_extreme"] = True
        conditions["near_bb_lower"] = bb_lower is not None and row["close"] <= bb_lower * 1.002
        conditions["far_from_vwap"] = vwap_dist > 0.003
        direction = "CALL"
    else:
        conditions["rsi_extreme"] = True
        conditions["near_bb_upper"] = bb_upper is not None and row["close"] >= bb_upper * 0.998
        conditions["far_from_vwap"] = vwap_dist > 0.003
        direction = "PUT"

    met = sum(conditions.values())
    if met >= 2:
        strength = met / len(conditions)
        return Signal(
            strategy="mean_reversion",
            direction=direction,
            symbol=symbol,
            entry_price=row["close"],
            technical_strength=round(strength, 2),
            details=conditions,
        )
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# Strategy Registry
# ═══════════════════════════════════════════════════════════════════════════════

STRATEGY_MAP = {
    "vwap_momentum_breakout": vwap_momentum_breakout,
    "bearish_momentum": bearish_momentum,
    "mean_reversion": mean_reversion,
}


def generate_signals(
    row: dict,
    symbol: str = "",
    active_strategies: list[str] | None = None,
) -> list[Signal]:
    """
    Run all active strategies on the latest feature row.
    Returns list of Signal objects (may be empty).
    """
    if active_strategies is None:
        active_strategies = list(STRATEGY_MAP.keys())

    signals = []
    for name in active_strategies:
        func = STRATEGY_MAP.get(name)
        if func is None:
            continue
        sig = func(row, symbol)
        if sig is not None:
            signals.append(sig)
            logger.info(f"Signal: {name} → {sig.direction} for {symbol} (strength={sig.technical_strength})")

    return signals


def generate_signal(row: dict) -> str | None:
    """Legacy compatibility: returns 'CALL', 'PUT', or None."""
    signals = generate_signals(row)
    if signals:
        return signals[0].direction
    return None
