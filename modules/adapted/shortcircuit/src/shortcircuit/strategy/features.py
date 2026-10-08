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
features.py — Pure stateless feature extraction.

All functions are pure: data in, value out. No broker calls, no side effects.
Extracted from god_mode_logic.py and analyzer.py during the BackToVWAPShort collapse.
"""


import numpy as np
import pandas as pd

# VWAP


def compute_vwap_sd(df: pd.DataFrame, window: int = 20) -> float:
    """
    Returns distance from VWAP in standard deviations.
    Uses the last *window* candles to compute σ of (close - VWAP).
    """
    if "vwap" not in df.columns or len(df) < window:
        return 0.0

    recent = df.iloc[-window:]
    diffs = recent["close"] - recent["vwap"]
    std_dev = diffs.std()

    if std_dev == 0:
        return 0.0

    current_diff = df.iloc[-1]["close"] - df.iloc[-1]["vwap"]
    return current_diff / std_dev


def compute_vwap_slope(df: pd.DataFrame, window: int = 30) -> tuple[float, str]:
    """
    Slope of the VWAP curve over the last *window* candles.
    Returns (slope_bps_per_min, status).
    status: "FLAT" if |slope| < 5 bps/min, "TRENDING" otherwise.
    """
    if df.empty or len(df) < window:
        return 0.0, "INSUFFICIENT_DATA"

    if "vwap" not in df.columns:
        v = df["volume"].values
        tp = (df["high"] + df["low"] + df["close"]) / 3
        vwap = (tp * v).cumsum() / v.cumsum()
    else:
        vwap = df["vwap"]

    y = vwap.iloc[-window:].values
    x = np.arange(len(y))

    if len(y) < 2:
        return 0.0, "INSUFFICIENT_DATA"

    slope, _ = np.polyfit(x, y, 1)
    pct_slope = (slope / df["close"].iloc[-1]) * 10000

    status = "FLAT" if abs(pct_slope) < 5 else "TRENDING"
    return pct_slope, status


def enrich_dataframe(df: pd.DataFrame) -> None:
    """Calculates VWAP in-place on the dataframe."""
    v = df["volume"].values
    tp = (df["high"] + df["low"] + df["close"]) / 3
    df["vwap"] = (tp * v).cumsum() / v.cumsum()


# RSI


def compute_rsi_wilder(closes, period: int = 14) -> float:
    """
    Latest RSI of a close series, Wilder-smoothed — the RSI TradingView and most
    broker charts draw, and so the one the operator reads off the screen.

    Returns float('nan') when there are too few closes to say anything. Callers
    should also demand a warm-up well beyond `period`: Wilder smoothing starts
    from the first bar, so the first few dozen readings are not yet stable.
    """
    s = pd.Series(list(closes), dtype=float)
    if len(s) < period + 1:
        return float("nan")
    d = s.diff()
    avg_up = d.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean().iloc[-1]
    avg_dn = (-d.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean().iloc[-1]
    if not np.isfinite(avg_up) or not np.isfinite(avg_dn):
        return float("nan")
    if avg_dn == 0:
        return 100.0 if avg_up > 0 else 50.0
    return float(100 - 100 / (1 + avg_up / avg_dn))


def compute_rsi_divergence(df: pd.DataFrame, window: int = 25) -> bool:
    """
    Swing-based bearish RSI divergence.

    Returns True only when price makes a higher (or equal) swing high
    while RSI makes a lower swing high over the last *window* candles.

    A swing high is a bar whose high is greater than both its neighbors,
    with a minimum separation of 3 bars between swings to avoid noise.

    This replaces the old endpoint-comparison approach per PRD doctrine:
    "divergence is a relationship between comparable swings, not just
    two arbitrary endpoints."
    """
    try:
        if len(df) < window:
            return False

        # Compute RSI series
        delta = df["close"].diff()
        gain = delta.where(delta > 0, 0).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        rsi_series = 100 - (100 / (1 + rs))

        recent_price = df["high"].iloc[-window:].values
        recent_rsi = rsi_series.iloc[-window:].values

        # Find swing highs: bar[i] > bar[i-1] AND bar[i] > bar[i+1]
        price_swings = []  # list of (index, price_high, rsi_value)
        for i in range(1, len(recent_price) - 1):
            if recent_price[i] > recent_price[i - 1] and recent_price[i] > recent_price[i + 1]:
                if not np.isnan(recent_rsi[i]):
                    price_swings.append((i, recent_price[i], recent_rsi[i]))

        # Filter: enforce minimum separation of 3 bars between swings
        filtered_swings = []
        for swing in price_swings:
            if not filtered_swings or (swing[0] - filtered_swings[-1][0]) >= 3:
                filtered_swings.append(swing)

        # Need at least 2 swing highs to compare
        if len(filtered_swings) < 2:
            return False

        # Compare the last two swing highs
        prev_swing = filtered_swings[-2]
        curr_swing = filtered_swings[-1]

        price_higher_high = curr_swing[1] >= prev_swing[1]
        rsi_lower_high = curr_swing[2] < prev_swing[2]

        return bool(price_higher_high and rsi_lower_high)
    except Exception:
        return False


# ATR


def compute_atr(df: pd.DataFrame, period: int = 14) -> float:
    """
    Average True Range.

    IMPORTANT: Returns float('nan') on error or insufficient data.
    Callers MUST guard with: `if not np.isfinite(atr) or atr <= 0: ...`
    DO NOT use a sentinel like 1.0 — it feeds the stop-loss engine.
    """
    try:
        if len(df) < period + 1:
            return float("nan")
        high = df["high"]
        low = df["low"]
        close = df["close"]

        prev_close = close.shift(1)
        tr1 = high - low
        tr2 = (high - prev_close).abs()
        tr3 = (low - prev_close).abs()

        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(window=period).mean()
        result = atr.iloc[-1]
        if not isinstance(result, float) or not np.isfinite(result):
            return float("nan")
        return float(result)
    except Exception:
        return float("nan")


# Volume


def compute_volume_fade_ratio(
    candles: list, lookback: int = 15, drop_forming: bool = True
) -> float:
    """
    Ratio of current volume (avg of last 2 COMPLETED candles) to prior average.
    < 0.65 = fading (exhaustion). > 1.0 = acceleration.

    FIXED:
    - drop_forming=True drops the last (developing) candle so its partial
      volume doesn't create a false 'fading' signal early in the bar's life.
    - Prior and current windows are now disjoint (bar -2 was previously
      double-counted in both, biasing the ratio toward 1.0).
    """
    data = candles[:-1] if drop_forming else candles  # completed bars only
    if len(data) < lookback + 2:
        return 1.0

    # Prior window: lookback bars, strictly before the last 2 completed bars
    prior_vols = [c["volume"] for c in data[-(lookback + 2) : -2]]
    avg_prior = sum(prior_vols) / len(prior_vols) if prior_vols else 0
    if avg_prior == 0:
        return 1.0

    # Current: last 2 COMPLETED bars (disjoint from prior window)
    current_avg = sum(c["volume"] for c in data[-2:]) / 2
    return round(current_avg / avg_prior, 3)


# Stretch & Gain


def compute_stretch_score(gain_pct: float, scanner_min: float) -> float:
    """
    Relative stretch above scanner minimum.
    0.0 at scanner floor, 1.0 at 2× scanner floor.
    """
    if scanner_min == 0:
        return 0.0
    return round((gain_pct - scanner_min) / scanner_min, 3)


# Pattern Detection


def detect_pattern(df: pd.DataFrame, vah: float = None) -> tuple[str, float]:
    """
    Multi-candle reversal pattern detection.
    Returns (pattern_name, volume_z_score).
    pattern_name is one of: VAH_REJECTION, BEARISH_ENGULFING, EVENING_STAR,
    SHOOTING_STAR, ABSORPTION_DOJI, MOMENTUM_BREAKDOWN, VOLUME_TRAP, NORMAL.
    """
    if df.empty or len(df) < 3:
        return "NORMAL", 0.0

    c1 = df.iloc[-3]  # 2 candles ago
    c2 = df.iloc[-2]  # prev candle
    c3 = df.iloc[-1]  # current candle

    # Pattern 0: VAH_REJECTION (Look Above & Fail)
    if vah and vah > 0:
        poked_above = df["high"].iloc[-3:].max() > (vah * 1.0005)
        closed_back_in = c3["close"] < (vah * 0.9995)
        if poked_above and closed_back_in:
            return "VAH_REJECTION", 0.0

    def _stats(row):
        body = abs(row["close"] - row["open"])
        direction = 1 if row["close"] > row["open"] else -1
        upper_wick = row["high"] - max(row["open"], row["close"])
        total_range = row["high"] - row["low"]
        if total_range == 0:
            total_range = 0.05
        return body, direction, upper_wick, total_range

    b1, d1, uw1, r1 = _stats(c1)
    b2, d2, uw2, r2 = _stats(c2)
    b3, d3, uw3, r3 = _stats(c3)

    # Vol Z-Score
    recent_vol = df["volume"].iloc[-20:-1]
    avg_vol = recent_vol.mean()
    std_vol = recent_vol.std()
    current_vol = c3["volume"]
    z_score = (current_vol - avg_vol) / std_vol if std_vol > 0 else 0

    # Pattern 1: Bearish Engulfing
    if d2 == 1 and d3 == -1 and b3 > b2 and c3["close"] < c2["open"] and z_score > 0:
        return "BEARISH_ENGULFING", z_score

    # Pattern 2: Evening Star
    if d2 == 1 and b2 < (r2 * 0.3) and d3 == -1:
        if c3["close"] < (c1["open"] + c1["close"]) / 2:
            return "EVENING_STAR", z_score

    # Pattern 3: Shooting Star
    if uw3 > (2 * b3) and z_score > 1.5:
        return "SHOOTING_STAR", z_score

    # Pattern 4: Absorption Doji
    if z_score > 2.0 and b3 < (c3["close"] * 0.0005):
        return "ABSORPTION_DOJI", z_score

    # Pattern 5: Momentum Breakdown
    avg_body = df["high"].iloc[-20:-1].sub(df["low"].iloc[-20:-1]).abs().mean()
    if avg_body == 0:
        avg_body = 0.1

    is_big_red = d3 == -1 and b3 > (1.2 * avg_body)
    is_high_vol = z_score > 2.0 or (b3 > 1.5 * avg_body and z_score > 1.2) or (b3 > 3.0 * avg_body)
    closes_at_low = (c3["close"] - c3["low"]) < (r3 * 0.35)

    if is_big_red and is_high_vol and closes_at_low:
        return "MOMENTUM_BREAKDOWN", z_score

    # Pattern 6: Volume Trap
    prev_vol = c2["volume"]
    prev_z = (prev_vol - avg_vol) / std_vol if std_vol > 0 else 0

    if d2 == 1 and prev_z > 1.5 and d3 == -1 and c3["close"] < c2["low"]:
        return "VOLUME_TRAP", z_score

    return "NORMAL", z_score


# Structure Checks


def is_narrowing_highs(df: pd.DataFrame, n: int = 3) -> bool:
    """
    Returns True if the last *n* completed candles each have a lower high.
    Murphy: "staircase down" preceding institutional selling.
    """
    if len(df) < (n + 1):
        return False
    highs = [df["high"].iloc[-(i + 2)] for i in range(n)]
    # highs[0] = most recent completed, highs[-1] = oldest
    return all(highs[i] < highs[i + 1] for i in range(len(highs) - 1))
