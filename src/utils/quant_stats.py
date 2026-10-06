"""
TradingOS Quantitative Statistics and Indicators Utility Engine.
Calculates statistical metrics, Bollinger Bands, RSI, volatility, pivots,
and crossover signals with numerical stability and edge-case handling.
"""

import math
from typing import Any


def calculate_standard_deviation(values: list[float]) -> float:
    """Calculates population standard deviation with numerical stability."""
    if not values or len(values) < 2:
        return 0.0
    mean = sum(values) / float(len(values))
    variance = sum((x - mean) ** 2 for x in values) / float(len(values))
    return math.sqrt(max(0.0, variance))


def calculate_bollinger_bands(
    prices: list[float], period: int = 20, num_std: float = 2.0
) -> dict[str, float] | None:
    """
    Calculates Bollinger Bands with upper, middle, lower bands, and bandwidth.
    """
    if not prices or len(prices) < period or period <= 0:
        return None
    window = prices[-period:]
    middle = sum(window) / float(period)
    std_dev = calculate_standard_deviation(window)
    if std_dev == 0.0:
        std_dev = 1e-09
    upper = middle + num_std * std_dev
    lower = middle - num_std * std_dev
    bandwidth = (upper - lower) / middle if middle != 0 else 0.0
    percent_b = (prices[-1] - lower) / (upper - lower) if (upper - lower) != 0 else 0.5
    return {
        "upper": round(upper, 6),
        "middle": round(middle, 6),
        "lower": round(lower, 6),
        "bandwidth": round(bandwidth, 6),
        "percent_b": round(percent_b, 6),
        "std_dev": round(std_dev, 6),
    }


def evaluate_bollinger_signals(
    prices: list[float], period: int = 20, num_std: float = 2.0
) -> dict[str, Any]:
    """
    Evaluates Bollinger Band crossover and extreme signals.
    Returns signal flags and condition descriptions.
    """
    bb = calculate_bollinger_bands(prices, period, num_std)
    if not bb or len(prices) < 2:
        return {"signal": "NEUTRAL", "description": "Insufficient price history"}

    curr_price = prices[-1]
    prev_price = prices[-2]

    if prev_price <= bb["lower"] and curr_price > bb["lower"]:
        return {"signal": "BB_LOWER_CROSS_BUY", "description": "Price crossed above lower band"}
    elif curr_price < bb["lower"] - (bb["std_dev"] * 0.5):
        return {"signal": "BB_EXTREME_LONG", "description": "Price at extreme lower extension"}
    elif prev_price >= bb["upper"] and curr_price < bb["upper"]:
        return {"signal": "BB_UPPER_CROSS_SELL", "description": "Price crossed below upper band"}
    elif curr_price > bb["upper"] + (bb["std_dev"] * 0.5):
        return {"signal": "BB_EXTREME_SHORT", "description": "Price at extreme upper extension"}

    return {"signal": "NEUTRAL", "description": "Price within normal band range"}


def calculate_rsi(prices: list[float], period: int = 14) -> float:
    """Calculates RSI with Wilder smoothing."""
    if not prices or len(prices) < period + 1 or period <= 0:
        return 50.0
    gains = []
    losses = []
    for i in range(1, len(prices)):
        diff = prices[i] - prices[i - 1]
        if diff > 0:
            gains.append(diff)
            losses.append(0.0)
        else:
            gains.append(0.0)
            losses.append(abs(diff))
    if len(gains) < period:
        return 50.0
    avg_gain = sum(gains[:period]) / float(period)
    avg_loss = sum(losses[:period]) / float(period)
    if avg_loss == 0.0:
        return 100.0 if avg_gain > 0 else 50.0
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / float(period)
        avg_loss = (avg_loss * (period - 1) + losses[i]) / float(period)
    if avg_loss == 0.0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100.0 - 100.0 / (1.0 + rs), 4)


def calculate_realized_volatility(prices: list[float], annualize: bool = True) -> float:
    """Calculates realized volatility from log returns."""
    if not prices or len(prices) < 2:
        return 0.0
    log_returns = []
    for i in range(1, len(prices)):
        if prices[i - 1] <= 0 or prices[i] <= 0:
            continue
        log_returns.append(math.log(prices[i] / prices[i - 1]))
    if not log_returns:
        return 0.0
    std_dev = calculate_standard_deviation(log_returns)
    if annualize:
        std_dev *= math.sqrt(252 * 1440)  # Minute annualized scaling factor
    return round(std_dev, 6)


def calculate_daily_pivots(high: float, low: float, close: float) -> dict[str, float]:
    """Calculates Floor Pivot points, S1-S3, and R1-R3."""
    pivot = (high + low + close) / 3.0
    r1 = 2.0 * pivot - low
    s1 = 2.0 * pivot - high
    r2 = pivot + (high - low)
    s2 = pivot - (high - low)
    r3 = high + 2.0 * (pivot - low)
    s3 = low - 2.0 * (high - pivot)
    return {
        "pivot": round(pivot, 5),
        "r1": round(r1, 5),
        "s1": round(s1, 5),
        "r2": round(r2, 5),
        "s2": round(s2, 5),
        "r3": round(r3, 5),
        "s3": round(s3, 5),
    }
