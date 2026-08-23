"""
Technical indicators, analytics, and market regime classification implementation.
Operates completely autonomously with dynamic parameter adaptation and optional
Rust CFFI acceleration for maximum institutional execution performance.
"""

import math


def calculate_ema(prices, period):
    """
    Calculates Exponential Moving Average (EMA) with Rust CFFI acceleration when available.
    Formula: EMA_today = Price_today * multiplier + EMA_yesterday * (1 - multiplier)
    multiplier = 2 / (period + 1)
    """
    if not prices or period <= 0 or len(prices) < period:
        return None

    try:
        from institutional_integrations.rust_bridge import is_rust_available, rust_accelerated_ema
        if is_rust_available():
            ema_series = rust_accelerated_ema(prices, period)
            if ema_series and len(ema_series) == len(prices):
                return ema_series[-1]
    except Exception:
        pass

    multiplier = 2.0 / (period + 1)
    # Start with simple moving average as first EMA value
    sma = sum(prices[:period]) / float(period)
    ema = sma

    for price in prices[period:]:
        ema = (price * multiplier) + (ema * (1.0 - multiplier))

    return ema


def calculate_rsi(prices, period=14):
    """
    Calculates Relative Strength Index (RSI).
    """
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
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return round(rsi, 4)


def calculate_atr(highs, lows, closes, period=14):
    """
    Calculates Average True Range (ATR) with Wilder's smoothing.
    """
    if not closes or len(closes) < period + 1 or period <= 0:
        return None

    true_ranges = []
    for i in range(1, len(closes)):
        h = highs[i]
        l = lows[i]
        prev_c = closes[i - 1]

        tr1 = h - l
        tr2 = abs(h - prev_c)
        tr3 = abs(l - prev_c)

        true_ranges.append(max(tr1, tr2, tr3))

    if len(true_ranges) < period:
        return None

    atr = sum(true_ranges[:period]) / float(period)
    for i in range(period, len(true_ranges)):
        atr = (atr * (period - 1) + true_ranges[i]) / float(period)

    return atr


def calculate_macd(prices, fast_period=12, slow_period=26, signal_period=9):
    """
    Calculates MACD (Moving Average Convergence Divergence).
    Returns dict: { 'macd': float, 'signal': float, 'histogram': float } or None.
    """
    if not prices or len(prices) < slow_period + signal_period:
        return None

    fast_emas = []
    slow_emas = []

    for i in range(slow_period, len(prices) + 1):
        window = prices[:i]
        fast_ema = calculate_ema(window, fast_period)
        slow_ema = calculate_ema(window, slow_period)
        if fast_ema is not None and slow_ema is not None:
            fast_emas.append(fast_ema)
            slow_emas.append(slow_ema)

    macd_line = [f - s for f, s in zip(fast_emas, slow_emas)]

    if len(macd_line) < signal_period:
        return None

    signal_line = calculate_ema(macd_line, signal_period)
    if signal_line is None:
        return None

    current_macd = macd_line[-1]
    current_signal = signal_line
    current_histogram = current_macd - current_signal

    return {
        "macd": current_macd,
        "signal": current_signal,
        "histogram": current_histogram,
    }


def calculate_bollinger_bands(prices, period=20, num_std=2.0):
    """
    Calculates Bollinger Bands.
    Returns dict: { 'upper': float, 'middle': float, 'lower': float, 'bandwidth': float } or None.
    """
    if not prices or len(prices) < period or period <= 0:
        return None

    window = prices[-period:]
    middle = sum(window) / float(period)

    variance = sum((x - middle) ** 2 for x in window) / float(period)
    std_dev = math.sqrt(max(0.0, variance))
    if std_dev == 0.0:
        std_dev = 1e-9

    upper = middle + (num_std * std_dev)
    lower = middle - (num_std * std_dev)
    bandwidth = (upper - lower) / middle if middle != 0 else 0.0

    return {
        "upper": upper,
        "middle": middle,
        "lower": lower,
        "bandwidth": bandwidth,
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
    return {"pivot": pivot, "r1": r1, "s1": s1, "r2": r2, "s2": s2}


def calculate_donchian_channels(highs, lows, period=20):
    """
    Calculates Donchian Channels (highest high and lowest low over lookback).
    Returns dict: { 'upper': float, 'lower': float, 'middle': float } or None.
    """
    if not highs or not lows or len(highs) < period or len(lows) < period or period <= 0:
        return None

    upper = max(highs[-period:])
    lower = min(lows[-period:])
    middle = (upper + lower) / 2.0
    return {"upper": upper, "lower": lower, "middle": middle}


def calculate_bollinger_squeeze(prices, period=20, num_std=2.0):
    """
    Calculates Bollinger Band Width ratio to evaluate volatility squeeze conditions.
    Formula: (Upper Band - Lower Band) / Middle Band
    Returns float or None.
    """
    bb = calculate_bollinger_bands(prices, period, num_std)
    if bb is None or bb["middle"] == 0:
        return None
    return bb["bandwidth"]


def calculate_adx(highs, lows, closes, period=14):
    """
    Average Directional Index (ADX) measuring trend strength.
    Range [0, 100]. Values > 22-25 indicate strong trend.
    """
    if not closes or len(closes) < period * 2 or len(highs) < period * 2 or len(lows) < period * 2:
        return 20.0

    tr_list = []
    dm_plus = []
    dm_minus = []

    for i in range(1, len(closes)):
        h_diff = highs[i] - highs[i - 1]
        l_diff = lows[i - 1] - lows[i]

        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        tr_list.append(tr)

        if h_diff > l_diff and h_diff > 0:
            dm_plus.append(h_diff)
        else:
            dm_plus.append(0.0)

        if l_diff > h_diff and l_diff > 0:
            dm_minus.append(l_diff)
        else:
            dm_minus.append(0.0)

    if len(tr_list) < period:
        return 20.0

    tr_smooth = [sum(tr_list[:period])]
    dm_plus_smooth = [sum(dm_plus[:period])]
    dm_minus_smooth = [sum(dm_minus[:period])]

    for i in range(period, len(tr_list)):
        tr_smooth.append(tr_smooth[-1] - (tr_smooth[-1] / float(period)) + tr_list[i])
        dm_plus_smooth.append(
            dm_plus_smooth[-1] - (dm_plus_smooth[-1] / float(period)) + dm_plus[i]
        )
        dm_minus_smooth.append(
            dm_minus_smooth[-1] - (dm_minus_smooth[-1] / float(period)) + dm_minus[i]
        )

    dx_list = []
    for i in range(len(tr_smooth)):
        tr_val = tr_smooth[i] if tr_smooth[i] > 0 else 1e-5
        di_p = (dm_plus_smooth[i] / tr_val) * 100.0
        di_m = (dm_minus_smooth[i] / tr_val) * 100.0

        diff = abs(di_p - di_m)
        total = di_p + di_m if (di_p + di_m) > 0 else 1e-5
        dx_list.append((diff / total) * 100.0)

    if len(dx_list) < period:
        return 20.0

    adx = sum(dx_list[:period]) / float(period)
    for i in range(period, len(dx_list)):
        adx = ((adx * (period - 1)) + dx_list[i]) / float(period)

    return round(adx, 2)


def calculate_stochastic(highs, lows, closes, period=14, d_period=3):
    """
    Stochastic Oscillator (%K and %D).
    Returns dict: {'k': float, 'd': float}
    """
    if not closes or len(closes) < period:
        return {"k": 50.0, "d": 50.0}

    k_values = []
    for i in range(len(closes) - d_period, len(closes)):
        sub_highs = highs[max(0, i - period + 1) : i + 1]
        sub_lows = lows[max(0, i - period + 1) : i + 1]
        if not sub_highs or not sub_lows:
            continue
        h_high = max(sub_highs)
        l_low = min(sub_lows)
        denom = h_high - l_low
        k = 50.0 if denom == 0 else ((closes[i] - l_low) / float(denom)) * 100.0
        k_values.append(k)

    k_curr = k_values[-1] if k_values else 50.0
    d_curr = sum(k_values) / float(len(k_values)) if k_values else 50.0
    return {"k": round(k_curr, 2), "d": round(d_curr, 2)}


def calculate_ichimoku(highs, lows, closes):
    """
    Ichimoku Cloud key parameters (Tenkan-sen and Kijun-sen).
    Returns dict: {'tenkan': float, 'kijun': float}
    """
    if not closes or len(closes) < 26:
        curr = closes[-1] if closes else 0.0
        return {"tenkan": curr, "kijun": curr}

    high_9 = max(highs[-9:])
    low_9 = min(lows[-9:])
    tenkan = (high_9 + low_9) / 2.0

    high_26 = max(highs[-26:])
    low_26 = min(lows[-26:])
    kijun = (high_26 + low_26) / 2.0

    return {"tenkan": round(tenkan, 5), "kijun": round(kijun, 5)}


def calculate_swing_points(highs, lows, window=2):
    """
    Detects Williams Fractal Swing Highs and Swing Lows.
    A Swing High at bar i requires: High[i] > High[i-k] and High[i] > High[i+k] for k in 1..window.
    A Swing Low at bar i requires: Low[i] < Low[i-k] and Low[i] < Low[i+k] for k in 1..window.
    """
    if not highs or not lows or len(highs) < (2 * window + 1):
        return {
            "swing_highs": [],
            "swing_lows": [],
            "last_swing_high": highs[-1] if highs else None,
            "last_swing_low": lows[-1] if lows else None,
        }

    swing_highs = []
    swing_lows = []

    for i in range(window, len(highs) - window):
        is_sh = True
        is_sl = True
        for w in range(1, window + 1):
            if highs[i] <= highs[i - w] or highs[i] <= highs[i + w]:
                is_sh = False
            if lows[i] >= lows[i - w] or lows[i] >= lows[i + w]:
                is_sl = False

        if is_sh:
            swing_highs.append({"price": highs[i], "idx": i})
        if is_sl:
            swing_lows.append({"price": lows[i], "idx": i})

    last_sh = swing_highs[-1]["price"] if swing_highs else max(highs[-10:])
    last_sl = swing_lows[-1]["price"] if swing_lows else min(lows[-10:])

    return {
        "swing_highs": swing_highs,
        "swing_lows": swing_lows,
        "last_swing_high": last_sh,
        "last_swing_low": last_sl,
    }


def calculate_vsa_metrics(highs, lows, closes, volumes=None):
    """
    Calculates Volume Spread Analysis (VSA) metrics.
    If real tick volumes are available, uses real volumes; otherwise uses ATR-normalized candle range.
    Returns dict with spread, relative volume, effort vs result, and accumulation/distribution flags.
    """
    if not closes or len(closes) < 10:
        return {
            "relative_volume": 1.0,
            "relative_spread": 1.0,
            "is_ultra_high_vol": False,
            "is_narrow_spread": False,
            "effort_result_divergence": False,
            "vsa_bias": "NEUTRAL",
        }

    ranges = [highs[i] - lows[i] for i in range(len(closes))]
    curr_range = ranges[-1]
    avg_range = sum(ranges[-10:]) / 10.0 if sum(ranges[-10:]) > 0 else 1e-5
    relative_spread = curr_range / avg_range

    if volumes and len(volumes) >= 10 and sum(volumes[-10:]) > 0:
        curr_vol = volumes[-1]
        avg_vol = sum(volumes[-10:]) / 10.0
    else:
        # ATR-normalized proxy volume
        curr_vol = curr_range * 10000.0
        avg_vol = avg_range * 10000.0

    avg_vol = max(1e-5, avg_vol)
    relative_volume = curr_vol / avg_vol

    is_ultra_high_vol = relative_volume >= 1.4
    is_narrow_spread = relative_spread <= 0.65
    effort_result_divergence = is_ultra_high_vol and is_narrow_spread

    vsa_bias = "NEUTRAL"
    if effort_result_divergence:
        # High volume but price didn't move -> absorption
        if closes[-1] > closes[-2]:
            vsa_bias = "ACCUMULATION"  # Buying effort absorbed at resistance / support
        else:
            vsa_bias = "DISTRIBUTION"

    return {
        "relative_volume": round(relative_volume, 2),
        "relative_spread": round(relative_spread, 2),
        "is_ultra_high_vol": is_ultra_high_vol,
        "is_narrow_spread": is_narrow_spread,
        "effort_result_divergence": effort_result_divergence,
        "vsa_bias": vsa_bias,
    }


def classify_market_regime(highs, lows, closes, period=20):
    """
    Statistically classifies the current market regime using ADX trend strength,
    EMA separation, and Bollinger Squeeze ratios.
    Returns a dict with complete regime analytics.
    """
    if not closes or len(closes) < 30:
        return {
            "regime": "RANGING",
            "detailed_regime": "RANGING_COMPRESSED",
            "volatility": "LOW",
            "trend_intensity": 0.0,
            "squeeze_ratio": 0.0,
            "adx": 20.0,
            "direction": "NEUTRAL",
        }

    ema_long_period = min(200, len(closes) - 1)
    ema_short_period = min(20, len(closes) - 1)

    ema_long = calculate_ema(closes, ema_long_period) or closes[-1]
    ema_short = calculate_ema(closes, ema_short_period) or closes[-1]
    atr_val = calculate_atr(highs, lows, closes, 14) or (closes[-1] * 0.001)

    adx_val = calculate_adx(highs, lows, closes, 14)

    # Trend Intensity = Abs distance between Short and Long EMA normalized by ATR
    trend_intensity = abs(ema_short - ema_long) / atr_val if atr_val > 0 else 0.0

    # Multi-factor trend decision: ADX > 22 AND (trend_intensity > 1.0 or EMA separation)
    is_trending = (adx_val >= 22.0 and trend_intensity >= 0.8) or (trend_intensity >= 1.5)
    regime = "TRENDING" if is_trending else "RANGING"

    direction = "BULLISH" if ema_short >= ema_long else "BEARISH"

    squeeze = calculate_bollinger_squeeze(closes, period, 2.0) or 0.0

    # Historical squeeze benchmark
    historical_squeezes = []
    lookback = min(40, len(closes))
    for i in range(len(closes) - lookback, len(closes)):
        sq = calculate_bollinger_squeeze(closes[:i], period, 2.0)
        if sq is not None:
            historical_squeezes.append(sq)

    avg_squeeze = (
        sum(historical_squeezes) / float(len(historical_squeezes))
        if historical_squeezes
        else squeeze
    )
    volatility = "HIGH" if squeeze > avg_squeeze else "LOW"

    if regime == "TRENDING":
        detailed_regime = f"TRENDING_{direction}"
    else:
        detailed_regime = "RANGING_EXPANDED" if volatility == "HIGH" else "RANGING_COMPRESSED"

    return {
        "regime": regime,
        "detailed_regime": detailed_regime,
        "volatility": volatility,
        "trend_intensity": round(trend_intensity, 4),
        "squeeze_ratio": round(squeeze, 4),
        "adx": round(adx_val, 2),
        "direction": direction,
    }


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
            "confluence_score": 50.0,
        }


def calculate_order_flow_metrics(history_bars, order_book=None):
    """
    Computes microstructure order flow signals combining VPIN flow toxicity,
    DOM level 2 depth imbalances, and short-term book pressure.
    """
    try:
        import institutional_integrations.order_flow_imbalance as ofi

        # Build proxy buy/sell volume buckets from price action and tick volumes
        vol_buys = []
        vol_sells = []
        for bar in history_bars[-20:]:
            high = bar.get("high", 0.0)
            low = bar.get("low", 0.0)
            close = bar.get("close", 0.0)
            open_p = bar.get("open", close)
            vol = bar.get("vol", bar.get("volume", (high - low) * 10000.0))

            rng = max(1e-5, high - low)
            body_ratio = (close - open_p) / rng if rng > 0 else 0.0

            # Estimate buy vs sell volume based on close relative to bar range
            buy_vol = vol * max(0.05, min(0.95, (close - low) / rng))
            sell_vol = vol - buy_vol
            vol_buys.append(buy_vol)
            vol_sells.append(sell_vol)

        avg_bucket = sum(vol_buys + vol_sells) / max(1.0, len(vol_buys) * 2.0)
        vpin = ofi.calculate_vpin(vol_buys, vol_sells, bucket_size=max(1.0, avg_bucket))

        dom_metrics = {"imbalance_ratio": 0.0, "dominant_side": "NEUTRAL"}
        pressure_metrics = {"pressure_score": 0.0, "expected_direction": "BALANCED"}

        if order_book and isinstance(order_book, dict):
            dom_metrics = ofi.detect_bid_ask_imbalance(order_book)
            pressure_metrics = ofi.predict_short_term_book_pressure(
                dom_metrics.get("total_bid_qty", 0.0),
                dom_metrics.get("total_ask_qty", 0.0),
            )

        return {
            "vpin": vpin,
            "is_toxic_flow": vpin >= 0.65,
            "dom_imbalance": dom_metrics.get("imbalance_ratio", 0.0),
            "dominant_side": dom_metrics.get("dominant_side", "NEUTRAL"),
            "pressure_score": pressure_metrics.get("pressure_score", 0.0),
            "expected_direction": pressure_metrics.get("expected_direction", "BALANCED"),
        }
    except Exception:
        return {
            "vpin": 0.15,
            "is_toxic_flow": False,
            "dom_imbalance": 0.0,
            "dominant_side": "NEUTRAL",
            "pressure_score": 0.0,
            "expected_direction": "BALANCED",
        }
