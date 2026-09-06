import pandas as pd
import numpy as np


def compute_indicators(df: pd.DataFrame) -> dict:
    """
    Compute all technical indicators from a price DataFrame.

    Expected columns: Close, High, Low, Volume
    Returns a flat dict of indicator values — used by both the screener
    (filters.py) and the technical analysis agent (technical.py).
    """
    close  = df["Close"].astype(float)
    high   = df["High"].astype(float)
    low    = df["Low"].astype(float)
    volume = df["Volume"].astype(float)

    current_price = float(close.iloc[-1])
    prev_close    = float(close.iloc[-2])

    # ── Moving averages ───────────────────────────────────────────────────────
    sma50  = close.rolling(50).mean().iloc[-1]
    sma200 = close.rolling(200).mean().iloc[-1]  # NaN if < 200 rows

    # ── ATR (14) ──────────────────────────────────────────────────────────────
    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low  - close.shift(1)).abs(),
    ], axis=1).max(axis=1)
    atr     = float(tr.rolling(14).mean().iloc[-1])
    atr_pct = atr / current_price * 100

    # ── Volume ────────────────────────────────────────────────────────────────
    avg_vol      = float(volume.iloc[-21:-1].mean())
    avg_price    = float(close.iloc[-21:-1].mean())
    today_vol    = float(volume.iloc[-1])
    volume_ratio = today_vol / avg_vol if avg_vol > 0 else 0
    avg_daily_value = avg_vol * avg_price   # ₹ liquidity proxy

    # ── RSI (14) ──────────────────────────────────────────────────────────────
    delta = close.diff()
    gain  = delta.clip(lower=0).rolling(14).mean()
    loss  = (-delta.clip(upper=0)).rolling(14).mean()
    rs    = gain / loss.replace(0, np.nan)
    rsi   = float((100 - 100 / (1 + rs)).iloc[-1])

    # ── MACD (12, 26, 9) ─────────────────────────────────────────────────────
    ema12       = close.ewm(span=12, adjust=False).mean()
    ema26       = close.ewm(span=26, adjust=False).mean()
    macd_line   = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    macd_hist   = macd_line - signal_line
    # Is histogram growing (momentum accelerating) or shrinking over last 3 bars?
    hist_vals = macd_hist.iloc[-3:].tolist()
    if hist_vals[-1] > hist_vals[-2] > hist_vals[-3]:
        macd_hist_trend = "expanding"
    elif hist_vals[-1] < hist_vals[-2] < hist_vals[-3]:
        macd_hist_trend = "contracting"
    else:
        macd_hist_trend = "mixed"

    # ── Bollinger Bands (20, 2σ) ──────────────────────────────────────────────
    sma20    = close.rolling(20).mean()
    std20    = close.rolling(20).std()
    bb_upper = float((sma20 + 2 * std20).iloc[-1])
    bb_mid   = float(sma20.iloc[-1])
    bb_lower = float((sma20 - 2 * std20).iloc[-1])

    # ── Momentum ──────────────────────────────────────────────────────────────
    momentum_5d  = (current_price - float(close.iloc[-6]))  / float(close.iloc[-6])  * 100
    momentum_20d = (current_price - float(close.iloc[-21])) / float(close.iloc[-21]) * 100
    day_change_pct = (current_price - prev_close) / prev_close * 100

    return {
        # Price
        "current_price":    round(current_price, 2),
        "day_change_pct":   round(day_change_pct, 2),
        # Moving averages
        "sma50":            round(float(sma50), 2),
        "sma200":           round(float(sma200), 2) if not pd.isna(sma200) else None,
        # ATR
        "atr_pct":          round(atr_pct, 2),
        # Volume
        "avg_vol":          round(avg_vol, 0),
        "today_vol":        round(today_vol, 0),
        "volume_ratio":     round(volume_ratio, 2),
        "avg_daily_value":  round(avg_daily_value, 0),
        # RSI
        "rsi":              round(rsi, 2),
        # MACD
        "macd":             round(float(macd_line.iloc[-1]), 4),
        "macd_signal":      round(float(signal_line.iloc[-1]), 4),
        "macd_hist":        round(float(macd_hist.iloc[-1]), 4),
        "macd_hist_prev":   round(float(macd_hist.iloc[-2]), 4),
        "macd_hist_trend":  macd_hist_trend,
        # Bollinger Bands
        "bb_upper":         round(bb_upper, 2),
        "bb_mid":           round(bb_mid, 2),
        "bb_lower":         round(bb_lower, 2),
        # Momentum
        "momentum_5d":      round(momentum_5d, 2),
        "momentum_20d":     round(momentum_20d, 2),
    }
