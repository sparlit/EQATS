import datetime
from typing import Any, Dict, List

try:
    import numpy as np
    import pandas as pd

    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False


def evaluate_wyckoff_master(history_bars: list[dict[str, Any]]) -> str:
    """
    Wyckoff Theory Accumulation/Distribution & Spring/Upthrust strategy.
    Magic: 20601
    """
    if not history_bars or len(history_bars) < 40:
        return "HOLD"
    if PANDAS_AVAILABLE:
        df = pd.DataFrame(history_bars)
        low_col = "low" if "low" in df else "l" if "l" in df else None
        high_col = "high" if "high" in df else "h" if "h" in df else None
        close_col = "close" if "close" in df else "c" if "c" in df else None
        if not (low_col and high_col and close_col):
            return "HOLD"
        rolling_min = df[low_col].rolling(30).min().iloc[-2]
        rolling_max = df[high_col].rolling(30).max().iloc[-2]
        last_low = df[low_col].iloc[-1]
        last_high = df[high_col].iloc[-1]
        last_close = df[close_col].iloc[-1]
        if last_low < rolling_min and last_close > rolling_min:
            return "BUY"
        if last_high > rolling_max and last_close < rolling_max:
            return "SELL"
    else:
        lows = [b.get("low", b.get("l", 0.0)) for b in history_bars]
        highs = [b.get("high", b.get("h", 0.0)) for b in history_bars]
        closes = [b.get("close", b.get("c", 0.0)) for b in history_bars]
        rolling_min = min(lows[-32:-2])
        rolling_max = max(highs[-32:-2])
        if lows[-1] < rolling_min and closes[-1] > rolling_min:
            return "BUY"
        if highs[-1] > rolling_max and closes[-1] < rolling_max:
            return "SELL"
    return "HOLD"


def evaluate_supertrend(history_bars: list[dict[str, Any]], multiplier: float = 3.0, period: int = 10) -> str:
    """
    Supertrend trend-following indicator.
    Magic: 20007
    """
    if not history_bars or len(history_bars) < period + 5:
        return "HOLD"
    if PANDAS_AVAILABLE:
        df = pd.DataFrame(history_bars)
        high_col = "high" if "high" in df else "h" if "h" in df else None
        low_col = "low" if "low" in df else "l" if "l" in df else None
        close_col = "close" if "close" in df else "c" if "c" in df else None
        if not (high_col and low_col and close_col):
            return "HOLD"
        high = df[high_col]
        low = df[low_col]
        close = df[close_col]
        tr = np.maximum(high - low, np.maximum(np.abs(high - close.shift(1)), np.abs(low - close.shift(1))))
        atr = tr.rolling(period).mean()
        hl2 = (high + low) / 2.0
        upperband = hl2 + multiplier * atr
        lowerband = hl2 - multiplier * atr
        last_close = close.iloc[-1]
        last_upper = upperband.iloc[-1]
        last_lower = lowerband.iloc[-1]
        if last_close > last_upper:
            return "BUY"
        if last_close < last_lower:
            return "SELL"
    else:
        closes = [b.get("close", b.get("c", 0.0)) for b in history_bars]
        if closes[-1] > closes[-period]:
            return "BUY"
        if closes[-1] < closes[-period]:
            return "SELL"
    return "HOLD"


def evaluate_donchian_breakout(history_bars: list[dict[str, Any]], period: int = 20) -> str:
    """
    Donchian Channel breakout strategy.
    Magic: 20008
    """
    if not history_bars or len(history_bars) < period + 1:
        return "HOLD"
    highs = [b.get("high", b.get("h", 0.0)) for b in history_bars]
    lows = [b.get("low", b.get("l", 0.0)) for b in history_bars]
    closes = [b.get("close", b.get("c", 0.0)) for b in history_bars]
    upper = max(highs[-(period + 1) : -1])
    lower = min(lows[-(period + 1) : -1])
    last_close = closes[-1]
    if last_close > upper:
        return "BUY"
    if last_close < lower:
        return "SELL"
    return "HOLD"


def evaluate_turtle_breakout(history_bars: list[dict[str, Any]], period: int = 20) -> str:
    """
    Turtle Trading 20-bar breakout system.
    Magic: 20009
    """
    return evaluate_donchian_breakout(history_bars, period=period)


def evaluate_rsi_momentum(history_bars: list[dict[str, Any]], period: int = 14) -> str:
    """
    RSI Momentum trend confirmation strategy.
    Magic: 20010
    """
    if not history_bars or len(history_bars) < period + 5:
        return "HOLD"
    closes = [b.get("close", b.get("c", 0.0)) for b in history_bars]
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [d if d > 0 else 0.0 for d in deltas[-period:]]
    losses = [-d if d < 0 else 0.0 for d in deltas[-period:]]
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    rs = avg_gain / (avg_loss if avg_loss > 0 else 1e-08)
    rsi = 100 - 100 / (1 + rs)
    if rsi > 60:
        return "BUY"
    if rsi < 40:
        return "SELL"
    return "HOLD"


def evaluate_ict_killzone(history_bars: list[dict[str, Any]]) -> str:
    """
    ICT London/NY Session Killzone & Session Extreme Reversal Strategy.
    Magic: 20004
    """
    if not history_bars or len(history_bars) < 20:
        return "HOLD"
    highs = [b.get("high", b.get("h", 0.0)) for b in history_bars]
    lows = [b.get("low", b.get("l", 0.0)) for b in history_bars]
    closes = [b.get("close", b.get("c", 0.0)) for b in history_bars]
    recent_high = max(highs[-20:])
    recent_low = min(lows[-20:])
    last_close = closes[-1]
    if last_close >= recent_high:
        return "SELL"
    if last_close <= recent_low:
        return "BUY"
    return "HOLD"
