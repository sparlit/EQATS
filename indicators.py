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
    if period <= 0 or len(prices) < period:
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
    avg_gain = sum(gains[:period]) / period if period > 0 else 0.0
    avg_loss = sum(losses[:period]) / period if period > 0 else 0.0

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
    atr = sum(true_ranges[:period]) / period if period > 0 else 0.0
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
    middle = sum(window) / period if period > 0 else 0.0

    # Variance and standard deviation calculation
    variance = sum((x - middle) ** 2 for x in window) / period if period > 0 else 0.0
    std_dev = variance ** 0.5
    if std_dev == 0.0:
        std_dev = 1e-9  # Avoid division by zero downstream

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

def calculate_adx(highs, lows, closes, period=14):
    """
    Average Directional Index (ADX) measuring trend strength.
    Range [0, 100]. Values > 25 indicate strong trends.
    """
    if len(closes) < period * 2 or len(highs) < period * 2 or len(lows) < period * 2:
        return 20.0 # Default fallback

    tr_list = []
    dm_plus = []
    dm_minus = []

    for i in range(1, len(closes)):
        h_diff = highs[i] - highs[i-1]
        l_diff = lows[i-1] - lows[i]

        # True Range
        tr = max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1]))
        tr_list.append(tr)

        # DM plus / minus
        if h_diff > l_diff and h_diff > 0:
            dm_plus.append(h_diff)
        else:
            dm_plus.append(0.0)

        if l_diff > h_diff and l_diff > 0:
            dm_minus.append(l_diff)
        else:
            dm_minus.append(0.0)

    # Smooth using Wilder's Smoothing
    tr_smooth = [sum(tr_list[:period])]
    dm_plus_smooth = [sum(dm_plus[:period])]
    dm_minus_smooth = [sum(dm_minus[:period])]

    for i in range(period, len(tr_list)):
        tr_smooth.append(tr_smooth[-1] - (tr_smooth[-1] / period) + tr_list[i])
        dm_plus_smooth.append(dm_plus_smooth[-1] - (dm_plus_smooth[-1] / period) + dm_plus[i])
        dm_minus_smooth.append(dm_minus_smooth[-1] - (dm_minus_smooth[-1] / period) + dm_minus[i])

    # Calculate DI+ and DI-
    di_plus = []
    di_minus = []
    dx_list = []

    for i in range(len(tr_smooth)):
        tr_val = tr_smooth[i] if tr_smooth[i] > 0 else 0.00001
        di_p = (dm_plus_smooth[i] / tr_val) * 100.0
        di_m = (dm_minus_smooth[i] / tr_val) * 100.0
        di_plus.append(di_p)
        di_minus.append(di_m)

        diff = abs(di_p - di_m)
        total = di_p + di_m if (di_p + di_m) > 0 else 0.00001
        dx_list.append((diff / total) * 100.0)

    # ADX smoothing
    if len(dx_list) < period:
        return 20.0
    adx = sum(dx_list[:period]) / period
    for i in range(period, len(dx_list)):
        adx = ((adx * (period - 1)) + dx_list[i]) / period

    return round(adx, 2)

def calculate_stochastic(highs, lows, closes, period=14, d_period=3):
    """
    Stochastic Oscillator (%K and %D).
    Returns a dict: {'k': float, 'd': float}
    """
    if len(closes) < period:
        return {'k': 50.0, 'd': 50.0}

    k_values = []
    # Calculate %K for recent bars to enable %D smoothing
    for i in range(len(closes) - d_period, len(closes)):
        sub_highs = highs[max(0, i - period + 1): i + 1]
        sub_lows = lows[max(0, i - period + 1): i + 1]
        if not sub_highs or not sub_lows:
            continue
        h_high = max(sub_highs)
        l_low = min(sub_lows)
        denom = h_high - l_low
        if denom == 0:
            k = 50.0
        else:
            k = ((closes[i] - l_low) / denom) * 100.0
        k_values.append(k)

    k_curr = k_values[-1] if k_values else 50.0
    d_curr = sum(k_values) / len(k_values) if k_values else 50.0
    return {'k': round(k_curr, 2), 'd': round(d_curr, 2)}

def calculate_ichimoku(highs, lows, closes):
    """
    Ichimoku Cloud parameters (Tenkan-sen and Kijun-sen).
    Returns a dict: {'tenkan': float, 'kijun': float}
    """
    if len(closes) < 26:
        return {'tenkan': closes[-1], 'kijun': closes[-1]}

    # 9-period High/Low
    high_9 = max(highs[-9:])
    low_9 = min(lows[-9:])
    tenkan = (high_9 + low_9) / 2.0

    # 26-period High/Low
    high_26 = max(highs[-26:])
    low_26 = min(lows[-26:])
    kijun = (high_26 + low_26) / 2.0

    return {'tenkan': round(tenkan, 5), 'kijun': round(kijun, 5)}

def get_smc_analysis(history_bars):
    """Returns institutional Smart Money Concepts (SMC) & ICT market structure analysis."""
    try:
        import institutional_integrations.smc_ict_engine as smc
        return smc.global_smc_engine.analyze(history_bars)
    except Exception:
        return {
            "order_blocks": {"bullish_ob": None, "bearish_ob": None},
            "fvgs": {"bullish_fvgs": [], "bearish_fvgs": []},
            "mss": {"mss_status": "NEUTRAL", "break_level": None},
            "liquidity_sweeps": {"bsl_sweep": False, "ssl_sweep": False},
            "bias": "NEUTRAL",
            "confluence_score": 50.0
        }
