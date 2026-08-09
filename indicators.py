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

def calculate_macd(prices, fast_period=12, slow_period=26, signal_period=9):
    """
    Calculates MACD (Moving Average Convergence Divergence).
    Returns a dict: { 'macd': float, 'signal': float, 'histogram': float } or None.
    """
    if len(prices) < slow_period + signal_period:
        return None

    # Step 1: Calculate Fast EMA and Slow EMA for all points starting from slow_period
    fast_emas = []
    slow_emas = []

    # Calculate for each point starting where we have enough history
    for i in range(slow_period, len(prices) + 1):
        window = prices[:i]
        fast_ema = calculate_ema(window, fast_period)
        slow_ema = calculate_ema(window, slow_period)
        if fast_ema is not None and slow_ema is not None:
            fast_emas.append(fast_ema)
            slow_emas.append(slow_ema)

    # Step 2: MACD line = Fast EMA - Slow EMA
    macd_line = [f - s for f, s in zip(fast_emas, slow_emas)]

    if len(macd_line) < signal_period:
        return None

    # Step 3: Signal line = EMA of MACD line
    signal_line = calculate_ema(macd_line, signal_period)

    if signal_line is None:
        return None

    # Step 4: Histogram = MACD - Signal
    current_macd = macd_line[-1]
    current_signal = signal_line
    current_histogram = current_macd - current_signal

    return {
        'macd': current_macd,
        'signal': current_signal,
        'histogram': current_histogram
    }

def calculate_bollinger_bands(prices, period=20, num_std=2.0):
    """
    Calculates Bollinger Bands.
    Returns dict: { 'upper': float, 'middle': float, 'lower': float } or None.
    """
    if len(prices) < period:
        return None

    # Standard SMA (Middle band)
    window = prices[-period:]
    middle = sum(window) / period

    # Variance and standard deviation calculation
    variance = sum((x - middle) ** 2 for x in window) / period
    std_dev = variance ** 0.5

    upper = middle + (num_std * std_dev)
    lower = middle - (num_std * std_dev)

    return {
        'upper': upper,
        'middle': middle,
        'lower': lower
    }

def calculate_pivot_points(high, low, close):
    """
    Calculates classic floor support and resistance pivot points.
    Returns dict: { 'pivot': float, 'r1': float, 's1': float, 'r2': float, 's2': float }
    """
    pivot = (high + low + close) / 3.0
    r1 = (2.0 * pivot) - low
    s1 = (2.0 * pivot) - high
    r2 = pivot + (high - low)
    s2 = pivot - (high - low)
    return {
        'pivot': pivot,
        'r1': r1,
        's1': s1,
        'r2': r2,
        's2': s2
    }

def calculate_donchian_channels(highs, lows, period=20):
    """
    Calculates Donchian Channels (highest high and lowest low over the lookback period).
    Returns dict: { 'upper': float, 'lower': float } or None.
    """
    if len(highs) < period or len(lows) < period:
        return None

    upper = max(highs[-period:])
    lower = min(lows[-period:])
    return {
        'upper': upper,
        'lower': lower
    }

def calculate_bollinger_squeeze(prices, period=20, num_std=2.0):
    """
    Calculates Bollinger Band Width as a ratio to evaluate squeeze conditions.
    Formula: (Upper Band - Lower Band) / Middle Band
    Returns float or None.
    """
    bb = calculate_bollinger_bands(prices, period, num_std)
    if bb is None or bb['middle'] == 0:
        return None
    return (bb['upper'] - bb['lower']) / bb['middle']

def classify_market_regime(highs, lows, closes, period=20):
    """
    Statistically classifies the current market regime.
    Returns a dict: {
        'regime': 'TRENDING' | 'RANGING',
        'volatility': 'HIGH' | 'LOW',
        'trend_intensity': float,
        'squeeze_ratio': float
    }
    """
    if len(closes) < 200:
        return {
            'regime': 'RANGING',
            'volatility': 'LOW',
            'trend_intensity': 0.0,
            'squeeze_ratio': 0.0
        }

    ema_long = calculate_ema(closes, 200) or closes[-1]
    ema_short = calculate_ema(closes, 20) or closes[-1]
    atr_val = calculate_atr(highs, lows, closes, 14) or (closes[-1] * 0.001)

    # Trend Intensity = Abs distance between Short and Long EMA normalized by ATR
    trend_intensity = abs(ema_short - ema_long) / atr_val if atr_val > 0 else 0.0
    regime = "TRENDING" if trend_intensity > 1.2 else "RANGING"

    # Squeeze / Volatility Regime
    squeeze = calculate_bollinger_squeeze(closes, period, 2.0) or 0.0

    # Calculate historical average squeeze over previous 20 periods to establish a benchmark
    historical_squeezes = []
    for i in range(max(0, len(closes) - 40), len(closes)):
        sq = calculate_bollinger_squeeze(closes[:i], period, 2.0)
        if sq is not None:
            historical_squeezes.append(sq)

    avg_squeeze = sum(historical_squeezes) / len(historical_squeezes) if len(historical_squeezes) > 0 else squeeze
    volatility = "HIGH" if squeeze > avg_squeeze else "LOW"

    return {
        'regime': regime,
        'volatility': volatility,
        'trend_intensity': round(trend_intensity, 4),
        'squeeze_ratio': round(squeeze, 4)
    }
