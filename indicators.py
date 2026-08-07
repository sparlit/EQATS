"""
Technical indicators and calculations implementation for EMA, RSI, and ATR.
This file operates completely autonomously of external libraries like pandas/ta to ensure maximum performance and minimal dependency overhead.
"""

def calculate_ema(prices, period):
    """
    Calculates Exponential Moving Average (EMA).
    Formula: EMA_today = Price_today * multiplier + EMA_yesterday * (1 - multiplier)
    multiplier = 2 / (period + 1)
    """
    if len(prices) < period:
        return None

    multiplier = 2.0 / (period + 1)
    # Start with simple moving average as first EMA value
    sma = sum(prices[:period]) / period
    ema = sma

    for price in prices[period:]:
        ema = (price * multiplier) + (ema * (1.0 - multiplier))

    return ema

def calculate_rsi(prices, period=14):
    """
    Calculates Relative Strength Index (RSI).
    """
    if len(prices) < period + 1:
        return None

    gains = []
    losses = []

    # Calculate differences
    for i in range(1, len(prices)):
        diff = prices[i] - prices[i-1]
        if diff > 0:
            gains.append(diff)
            losses.append(0.0)
        else:
            gains.append(0.0)
            losses.append(abs(diff))

    # First Average Gain & Loss
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    if avg_loss == 0:
        if avg_gain == 0:
            return 50.0
        return 100.0

    # Smoothed Wilder's method for remaining values
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return rsi

def calculate_atr(highs, lows, closes, period=14):
    """
    Calculates Average True Range (ATR).
    True Range (TR) is the maximum of:
    1. High - Low
    2. Absolute value of High - Previous Close
    3. Absolute value of Low - Previous Close
    """
    if len(closes) < period + 1:
        # Require previous close for calculating true range
        return None

    true_ranges = []
    for i in range(1, len(closes)):
        h = highs[i]
        l = lows[i]
        prev_c = closes[i-1]

        tr1 = h - l
        tr2 = abs(h - prev_c)
        tr3 = abs(l - prev_c)

        true_ranges.append(max(tr1, tr2, tr3))

    if len(true_ranges) < period:
        return None

    # Return the simple average of true ranges (standard ATR is smoothed, but SMA is widely accepted/sufficient)
    # We can smooth it using Wilder's technique
    atr = sum(true_ranges[:period]) / period
    for i in range(period, len(true_ranges)):
        atr = (atr * (period - 1) + true_ranges[i]) / period

    return atr
