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
abs_momentum_scorecard.py — Absolute Momentum Scorecard Module
===============================================================

Callable module for Stage 6 pipeline.
Exposes:
  score_momentum(df)                    -> df with 8 new columns appended.
  compute_fresh_signals(sym_df, as_of)  -> dict of 13 recomputed signal values.

Metrics (6 total, ROC excluded from scoring but applied as a gate):
  1. MA_Position      — Weinstein Stage 2 + dist_ema_50
  2. RSI_Strength     — rsi_14 + pct_pos_days
  3. Acceleration     — return horizon acceleration + smoothness + stpb_zscore_21d
  4. Hi52W_Proximity  — proximity_52w_high + bb_pct_b
  5. Trend_Strength   — rm_r2 + residual_momentum + smoothness (vs universe median)
  6. Volume_Confirm   — volume_price_pos_move_confirmed + mfi_14 + vol_ratio_21_252

ROC gate (post-scoring override):
  All three return horizons must be positive:
    ret_12m1m > 0 AND ret_6m1m > 0 AND ret_3m1m > 0
  If any horizon is negative:
    Score     → 0
    AbsMom_Tier → 'Skip (negative: <failed horizons>)'
  Individual metric columns are left intact (still show the structural score).

Output columns appended:
  MA_Position | RSI_Strength | Acceleration | Hi52W_Proximity |
  Trend_Strength | Volume_Confirm | Score | AbsMom_Tier

Tier logic (out of 6):
  6/6 → Tier1_Perfect
  4-5 → Tier2_Strong
  2-3 → Tier3_Moderate
  <2  → Skip
  ROC gate fails → Skip (negative: <ret_12m1m / ret_6m1m / ret_3m1m>)
"""

import numpy as np
import pandas as pd

# ── Metric definitions ────────────────────────────────────────────────────────


def _metric_ma(row):
    """MA Position: Weinstein Stage 2 confirmed + price above 50 EMA."""
    stage2 = row.get("weinstein_stage2", np.nan)
    dist_ema50 = row.get("dist_ema_50", np.nan)
    stage2_pass = (stage2 == 1) if pd.notna(stage2) else False
    ema50_pass = (dist_ema50 > 0) if pd.notna(dist_ema50) else False
    return "PASS" if (stage2_pass and ema50_pass) else "FAIL"


def _metric_rsi(row):
    """RSI Strength: rsi_14 > 50 AND pct_pos_days > 0.52 (scale 0-1)."""
    rsi14 = row.get("rsi_14", np.nan)
    pct_pos = row.get("pct_pos_days", np.nan)
    rsi_pass = (rsi14 > 50) if pd.notna(rsi14) else False
    pct_pass = (pct_pos > 0.52) if pd.notna(pct_pos) else False
    return "PASS" if (rsi_pass and pct_pass) else "FAIL"


def _metric_acceleration(row, smoothness_median):
    """
    Acceleration: at least 1 horizon acceleration test passes
    AND smoothness > 0.5
    AND stpb_zscore_21d > 0.
    """
    r3 = row.get("ret_3m1m", np.nan)
    r6 = row.get("ret_6m1m", np.nan)
    r12 = row.get("ret_12m1m", np.nan)

    accel_near = (r3 > r6 / 2) if (pd.notna(r3) and pd.notna(r6) and r6 != 0) else False
    accel_mid = (r6 > r12 / 2) if (pd.notna(r6) and pd.notna(r12) and r12 != 0) else False

    smooth = row.get("smoothness", np.nan)
    zscore_21d = row.get("stpb_zscore_21d", np.nan)

    smooth_pass = (smooth > 0.5) if pd.notna(smooth) else False
    zscore_pass = (zscore_21d > 0) if pd.notna(zscore_21d) else False

    return "PASS" if ((accel_near or accel_mid) and smooth_pass and zscore_pass) else "FAIL"


def _metric_52w(row):
    """52W High Proximity: proximity_52w_high > 0.75 AND bb_pct_b > 0.5."""
    prox = row.get("proximity_52w_high", np.nan)
    bb_pctb = row.get("bb_pct_b", np.nan)
    prox_pass = (prox > 0.75) if pd.notna(prox) else False
    bb_pass = (bb_pctb > 0.5) if pd.notna(bb_pctb) else False
    return "PASS" if (prox_pass and bb_pass) else "FAIL"


def _metric_trend_strength(row, smoothness_median):
    """
    Trend Strength (ADX proxy):
      rm_r2 > 0.3 AND residual_momentum > 0 AND smoothness > universe median.
    """
    r2 = row.get("rm_r2", np.nan)
    resid = row.get("residual_momentum", np.nan)
    smooth = row.get("smoothness", np.nan)

    r2_pass = (r2 > 0.3) if pd.notna(r2) else False
    resid_pass = (resid > 0) if pd.notna(resid) else False
    smooth_pass = (smooth > smoothness_median) if pd.notna(smooth) else False

    return "PASS" if (r2_pass and resid_pass and smooth_pass) else "FAIL"


def _metric_volume(row):
    """
    Volume Confirmation:
      volume_price_pos_move_confirmed == 1 AND mfi_14 > 50 AND vol_ratio_21_252 > 1.0.
    """
    vol_conf = row.get("volume_price_pos_move_confirmed", np.nan)
    mfi = row.get("mfi_14", np.nan)
    vol_rat = row.get("vol_ratio_21_252", np.nan)

    conf_pass = (vol_conf == 1) if pd.notna(vol_conf) else False
    mfi_pass = (mfi > 50) if pd.notna(mfi) else False
    vol_pass = (vol_rat > 1.0) if pd.notna(vol_rat) else False

    return "PASS" if (conf_pass and mfi_pass and vol_pass) else "FAIL"


# ── Tier assignment ───────────────────────────────────────────────────────────


def _assign_tier(score):
    if score == 6:
        return "Tier1_Perfect"
    elif score >= 4:
        return "Tier2_Strong"
    elif score >= 2:
        return "Tier3_Moderate"
    else:
        return "Skip"


# ── ROC gate helper ───────────────────────────────────────────────────────────


def _roc_skip_reason(row):
    """
    Returns a descriptive Skip string naming which return horizons failed.
    Called only for rows where at least one horizon is non-positive.
    NaN values are treated as failed (insufficient data = no positive return).
    """
    failed = []
    for col in ["ret_12m1m", "ret_6m1m", "ret_3m1m"]:
        val = row.get(col, np.nan)
        if pd.isna(val) or val <= 0:
            failed.append(col)
    return f"Skip (negative: {', '.join(failed)})" if failed else "Skip"


# ── Public API ────────────────────────────────────────────────────────────────

METRIC_COLS = [
    "MA_Position",
    "RSI_Strength",
    "Acceleration",
    "Hi52W_Proximity",
    "Trend_Strength",
    "Volume_Confirm",
]

# Signals recomputed fresh by compute_fresh_signals()
FRESH_SIGNAL_COLS = [
    "rsi_14",
    "ret_12m1m",
    "ret_6m1m",
    "ret_3m1m",
    "pct_pos_days",
    "proximity_52w_high",
    "dist_ema_20",
    "dist_ema_50",
    "weinstein_stage2",
    "bb_pct_b",
    "mfi_14",
    "vol_ratio_21_252",
    "volume_price_pos_move_confirmed",
]

# Signals NOT recomputable — left stale from last rebalance parquet
STALE_SIGNAL_COLS = ["smoothness", "rm_r2", "residual_momentum", "stpb_zscore_21d"]


def score_momentum(df: pd.DataFrame) -> pd.DataFrame:
    """
    Accept a dataframe (ranked/mid recommendations) and append 8 columns:
      MA_Position | RSI_Strength | Acceleration | Hi52W_Proximity |
      Trend_Strength | Volume_Confirm | Score | AbsMom_Tier

    Post-scoring ROC gate:
      If ret_12m1m <= 0 OR ret_6m1m <= 0 OR ret_3m1m <= 0:
        Score = 0, AbsMom_Tier = 'Skip (negative: <col names>)'
      Individual metric columns are left intact.

    Returns the dataframe with those columns added.
    Missing input columns are handled gracefully (metric returns FAIL).
    """
    if df.empty:
        for col in METRIC_COLS + ["Score", "AbsMom_Tier"]:
            df[col] = pd.NA
        return df

    # Universe-level stat needed by two metrics
    smoothness_median = (
        df["smoothness"].median()
        if "smoothness" in df.columns and df["smoothness"].notna().any()
        else 0.5  # safe fallback
    )

    df = df.copy()
    df["MA_Position"] = df.apply(_metric_ma, axis=1)
    df["RSI_Strength"] = df.apply(_metric_rsi, axis=1)
    df["Acceleration"] = df.apply(lambda r: _metric_acceleration(r, smoothness_median), axis=1)
    df["Hi52W_Proximity"] = df.apply(_metric_52w, axis=1)
    df["Trend_Strength"] = df.apply(lambda r: _metric_trend_strength(r, smoothness_median), axis=1)
    df["Volume_Confirm"] = df.apply(_metric_volume, axis=1)

    df["Score"] = df[METRIC_COLS].apply(lambda r: (r == "PASS").sum(), axis=1)
    df["AbsMom_Tier"] = df["Score"].apply(_assign_tier)

    # ── ROC gate — all three return horizons must be positive ─────────────────
    # Stocks with any negative return horizon are overridden to Skip
    # regardless of their structural metric score.
    # NaN return values are treated as failed (no data = no positive return).
    roc_cols_present = all(c in df.columns for c in ["ret_12m1m", "ret_6m1m", "ret_3m1m"])
    if roc_cols_present:
        roc_pass = (
            df["ret_12m1m"].fillna(0).gt(0)
            & df["ret_6m1m"].fillna(0).gt(0)
            & df["ret_3m1m"].fillna(0).gt(0)
        )
        if (~roc_pass).any():
            df.loc[~roc_pass, "AbsMom_Tier"] = df.loc[~roc_pass].apply(_roc_skip_reason, axis=1)
            df.loc[~roc_pass, "Score"] = 0

    return df


def compute_fresh_signals(sym_df, as_of_date):
    """
    Recompute 13 signal inputs from raw OHLCV data for a single symbol.

    Parameters:
        sym_df     : DataFrame with columns [date, open, high, low, close, volume]
                     sorted ascending by date.
        as_of_date : Compute signals as of this date (today for mid-month).

    Returns:
        dict with keys matching FRESH_SIGNAL_COLS.
        Any signal with insufficient data returns np.nan.

    Not recomputed (left stale from last rebalance parquet):
        smoothness, rm_r2, residual_momentum, stpb_zscore_21d
    """
    result = dict.fromkeys(FRESH_SIGNAL_COLS, np.nan)

    df = sym_df[sym_df["date"] <= pd.Timestamp(as_of_date)].copy()
    df = df.sort_values("date").reset_index(drop=True)

    n = len(df)
    if n < 22:
        return result

    close = df["close"]
    high = df["high"]
    low = df["low"]
    volume = df["volume"]

    # ── RSI 14 (Wilder EMA) ───────────────────────────────────────────────────
    if n >= 15:
        delta = close.diff()
        gain = delta.clip(lower=0)
        loss = (-delta).clip(lower=0)
        avg_g = gain.ewm(com=13, min_periods=14).mean()
        avg_l = loss.ewm(com=13, min_periods=14).mean()
        rs = avg_g / avg_l.replace(0, np.nan)
        rsi = 100 - (100 / (1 + rs))
        val = rsi.iloc[-1]
        result["rsi_14"] = round(float(val), 2) if pd.notna(val) else np.nan

    # ── Returns (skip last month = last 21 trading days) ──────────────────────
    if n >= 22:
        p_1m = float(close.iloc[-21])

        if n >= 273:
            p_12m = float(close.iloc[-252])
            result["ret_12m1m"] = round((p_1m / p_12m) - 1, 6) if p_12m != 0 else np.nan

        if n >= 147:
            p_6m = float(close.iloc[-126])
            result["ret_6m1m"] = round((p_1m / p_6m) - 1, 6) if p_6m != 0 else np.nan

        if n >= 84:
            p_3m = float(close.iloc[-63])
            result["ret_3m1m"] = round((p_1m / p_3m) - 1, 6) if p_3m != 0 else np.nan

    # ── pct_pos_days (252 day window) ─────────────────────────────────────────
    if n >= 2:
        window = min(252, n)
        daily_rets = close.iloc[-window:].pct_change().dropna()
        if len(daily_rets) > 0:
            result["pct_pos_days"] = round(float((daily_rets > 0).mean()), 6)

    # ── proximity_52w_high ────────────────────────────────────────────────────
    if n >= 2:
        window = min(252, n)
        high_52w = float(high.iloc[-window:].max())
        curr_close = float(close.iloc[-1])
        result["proximity_52w_high"] = round(curr_close / high_52w, 6) if high_52w != 0 else np.nan

    # ── dist_ema_20 = (close - EMA20) / EMA20 * 100  (percentage points) ─────
    if n >= 20:
        ema20 = close.ewm(span=20, adjust=False).mean()
        curr_close = float(close.iloc[-1])
        e20 = float(ema20.iloc[-1])
        result["dist_ema_20"] = round((curr_close - e20) / e20 * 100, 4) if e20 != 0 else np.nan

    # ── dist_ema_50 = (close - EMA50) / EMA50 * 100  (percentage points) ─────
    if n >= 50:
        ema50 = close.ewm(span=50, adjust=False).mean()
        curr_close = float(close.iloc[-1])
        e50 = float(ema50.iloc[-1])
        result["dist_ema_50"] = round((curr_close - e50) / e50 * 100, 4) if e50 != 0 else np.nan

    # ── weinstein_stage2: price > 30W MA AND 30W MA rising ───────────────────
    if n >= 151:
        ma30w = close.rolling(150).mean()
        curr_ma = float(ma30w.iloc[-1])
        prev_ma = float(ma30w.iloc[-2])
        curr_close = float(close.iloc[-1])
        result["weinstein_stage2"] = 1 if (curr_close > curr_ma and curr_ma > prev_ma) else 0

    # ── bb_pct_b: Bollinger Band %B (20 day, 2 std) ───────────────────────────
    if n >= 20:
        bb_mid = close.rolling(20).mean()
        bb_std = close.rolling(20).std(ddof=1)
        bb_upper = bb_mid + 2 * bb_std
        bb_lower = bb_mid - 2 * bb_std
        bu = float(bb_upper.iloc[-1])
        bl = float(bb_lower.iloc[-1])
        curr_close = float(close.iloc[-1])
        bandwidth = bu - bl
        result["bb_pct_b"] = round((curr_close - bl) / bandwidth, 6) if bandwidth != 0 else np.nan

    # ── mfi_14: Money Flow Index ──────────────────────────────────────────────
    if n >= 15:
        tp = (high + low + close) / 3
        rmf = tp * volume
        tp_diff = tp.diff()
        pos_mf = rmf.where(tp_diff > 0, 0.0)
        neg_mf = rmf.where(tp_diff <= 0, 0.0)
        pos_sum = pos_mf.rolling(14).sum()
        neg_sum = neg_mf.rolling(14).sum()
        mfr = pos_sum / neg_sum.replace(0, np.nan)
        mfi = 100 - (100 / (1 + mfr))
        val = mfi.iloc[-1]
        result["mfi_14"] = round(float(val), 2) if pd.notna(val) else np.nan

    # ── vol_ratio_21_252 ──────────────────────────────────────────────────────
    if n >= 22:
        vol_21 = float(volume.iloc[-21:].mean())
        vol_252 = float(volume.iloc[-min(252, n) :].mean())
        result["vol_ratio_21_252"] = round(vol_21 / vol_252, 6) if vol_252 != 0 else np.nan

    # ── volume_price_pos_move_confirmed ───────────────────────────────────────
    if n >= 22:
        price_up = float(close.iloc[-1]) > float(close.iloc[-2])
        avg_vol_20 = float(volume.iloc[-21:-1].mean())
        vol_today = float(volume.iloc[-1])
        result["volume_price_pos_move_confirmed"] = (
            1 if (price_up and vol_today > avg_vol_20) else 0
        )

    return result
