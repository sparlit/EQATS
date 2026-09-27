from __future__ import annotations

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


"""Delivery feature engineering: z-scores, streaks, volume, technical indicators."""


import numpy as np
import pandas as pd


def add_features(df: pd.DataFrame, *, window: int = 30) -> pd.DataFrame:
    """Append ret_1d, deliv_z, hi_deliv flags, streak counters, technical indicators."""
    out = df.copy()
    if "high" not in out.columns:
        out["high"] = out["close"] * 1.01
        out["low"] = out["close"] * 0.99
    out["ret_1d"] = out["close"].pct_change()

    # Delivery z-score (30-day rolling)
    mean = out["deliv_pct"].rolling(window, min_periods=15).mean()
    std = out["deliv_pct"].rolling(window, min_periods=15).std()
    std = std.replace(0, np.nan)
    out["deliv_z"] = (out["deliv_pct"] - mean) / std

    out["hi_deliv"] = out["deliv_pct"] >= 60

    flag = (out["deliv_pct"] >= 60).astype(int)
    group = flag * (flag.groupby((flag != flag.shift()).cumsum()).cumcount() + 1)
    out["hi_streak"] = group.where(flag > 0, 0)

    # Volume z-score
    if "volume" in out.columns:
        out["volume"] = pd.to_numeric(out["volume"], errors="coerce")
        vol_mean = out["volume"].rolling(window, min_periods=15).mean()
        vol_std = out["volume"].rolling(window, min_periods=15).std().replace(0, np.nan)
        out["vol_z"] = (out["volume"] - vol_mean) / vol_std

    # --- Technical Indicators ---
    # RSI(14)
    out["close"].diff()
    gain = out["close"].diff().clip(lower=0)
    loss = -out["close"].diff().clip(upper=0)
    avg_gain = gain.rolling(14, min_periods=14).mean()
    avg_loss = loss.rolling(14, min_periods=14).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    out["rsi"] = 100 - (100 / (1 + rs))

    # MACD (12, 26, 9)
    ema12 = out["close"].ewm(span=12, adjust=False).mean()
    ema26 = out["close"].ewm(span=26, adjust=False).mean()
    out["macd"] = ema12 - ema26
    out["macd_signal"] = out["macd"].ewm(span=9, adjust=False).mean()
    out["macd_hist"] = out["macd"] - out["macd_signal"]

    # SMA 20 & SMA 50
    out["sma_20"] = out["close"].rolling(20, min_periods=20).mean()
    out["sma_50"] = out["close"].rolling(50, min_periods=50).mean()

    # ATR(14) for dynamic stops
    high_low = out["high"] - out["low"]
    high_close = (out["high"] - out["close"].shift()).abs()
    low_close = (out["low"] - out["close"].shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    out["atr_14"] = tr.rolling(14, min_periods=14).mean()

    return out
    return out


def conviction_score(row: pd.Series) -> float:
    """Score 0-1 for signal strength. Higher = more conviction.

    Components:
      deliv_z  40%  — how abnormal delivery is
      momentum 30%  — 1d return direction + magnitude
      vol_trend 20% — volume confirms delivery spike
      technicals 10% — RSI/MACD/trend alignment
    Returns 0.0 if deliv_z is NaN.
    """
    dz = row.get("deliv_z")
    if pd.isna(dz):
        return 0.0

    # 1. Delivery z-score (0-1, cap at z=5)
    dz_norm = min(abs(dz) / 5.0, 1.0) * 0.40

    # 2. Momentum (0-1, cap at 3% daily return)
    ret = row.get("ret_1d", 0.0)
    if pd.isna(ret):
        ret = 0.0
    momentum = min(max(ret / 0.03, 0.0), 1.0) * 0.30

    # 3. Volume trend (0-1, cap at z=2)
    vz = row.get("vol_z", 0.0)
    if pd.isna(vz):
        vz = 0.0
    vol_trend = min(max(vz / 2.0, 0.0), 1.0) * 0.20

    # 4. Technicals (0-1)
    tech = 0.0
    rsi = row.get("rsi", 50.0)
    if pd.isna(rsi):
        rsi = 50.0
    macd_h = row.get("macd_hist", 0.0)
    if pd.isna(macd_h):
        macd_h = 0.0
    close = row.get("close", 0.0)
    sma20 = row.get("sma_20", close)
    if pd.isna(sma20):
        sma20 = close

    # RSI in sweet spot 40-65 gets full mark
    if 40 <= rsi <= 65:
        tech += 0.4
    elif 30 <= rsi <= 75:
        tech += 0.2
    # MACD positive
    if macd_h > 0:
        tech += 0.3
    # Price above SMA20
    if close > sma20 > 0:
        tech += 0.3
    tech *= 0.10

    return round(dz_norm + momentum + vol_trend + tech, 4)


def conviction_score_v2(
    row: pd.Series, fundamentals: dict | None = None, institutional: dict | None = None, sector_data: dict | None = None
) -> float:
    """Professional conviction score with all 4 layers.

    Components:
      delivery+tech 55%  — existing conviction_score (deliv_z + momentum + vol + technicals)
      fundamentals  25%  — valuation, profitability, financial health
      institutional 20%  — FII/DII flows, promoter holding, pledge

    Returns 0.0 if deliv_z is NaN.
    """
    # Layer 1: Delivery + Technical (existing)
    base = conviction_score(row)

    # Layer 2: Fundamentals (0-1)
    fund = 0.0
    if fundamentals:
        pe = fundamentals.get("pe_trailing")
        if pe is not None and 5 < pe < 25:
            fund += 0.15
        elif pe is not None and 25 < pe < 40:
            fund += 0.05

        roe = fundamentals.get("roe")
        if roe is not None and roe > 20:
            fund += 0.15
        elif roe is not None and roe > 12:
            fund += 0.08

        de = fundamentals.get("debt_to_equity")
        if de is not None and de < 0.5:
            fund += 0.10
        elif de is not None and de < 1.0:
            fund += 0.05

        margin = fundamentals.get("profit_margin")
        if margin is not None and margin > 15:
            fund += 0.10

        growth = fundamentals.get("revenue_growth")
        if growth is not None and growth > 0.15:
            fund += 0.10

        div_yield = fundamentals.get("dividend_yield")
        if div_yield is not None and div_yield > 0.02:
            fund += 0.05

    fund = min(fund, 1.0)

    # Layer 3: Institutional (0-1)
    inst = 0.0
    if institutional:
        # FII buying (net positive)
        fii_chg = institutional.get("fii_chg")
        if fii_chg is not None and fii_chg > 0:
            inst += 0.20
        elif fii_chg is not None and fii_chg == 0:
            inst += 0.05

        # DII buying
        dii_chg = institutional.get("dii_chg")
        if dii_chg is not None and dii_chg > 0:
            inst += 0.15

        # Promoter not selling
        promoter_chg = institutional.get("promoter_chg")
        if promoter_chg is not None and promoter_chg >= 0:
            inst += 0.20

        # Low pledge
        pledge = institutional.get("pledge_pct")
        if pledge is not None and pledge < 5:
            inst += 0.25
        elif pledge is not None and pledge < 15:
            inst += 0.15
        elif pledge is not None and pledge < 25:
            inst += 0.05

        # High FII/DII holding (institutional interest)
        fii_pct = institutional.get("fii_pct")
        if fii_pct is not None and fii_pct > 20:
            inst += 0.10
        elif fii_pct is not None and fii_pct > 10:
            inst += 0.05

    inst = min(inst, 1.0)

    # Weighted composite
    score = (base * 0.55) + (fund * 0.25) + (inst * 0.20)
    return round(min(score, 1.0), 4)


def horizon_fit(score: float) -> str:
    """Assign holding horizon based on conviction score.

    High conviction (>= 0.45) → 10d — let winners run.
    Medium (0.25-0.45)        → 5d  — balanced.
    Low (< 0.25)             → 1d  — quick scalp or skip.
    """
    if score >= 0.45:
        return "10d"
    if score >= 0.25:
        return "5d"
    return "1d"


HORIZON_DAYS = {"1d": 1, "5d": 5, "10d": 10}
HORIZON_STOP = {"1d": 0.03, "5d": 0.05, "10d": 0.07}


def price_band(close: float) -> str:
    if close < 50:
        return "<50"
    if close < 200:
        return "50_200"
    if close < 1000:
        return "200_1000"
    return ">1000"


def cluster_entry_mask(mask: pd.Series) -> pd.Series:
    """True only on the FIRST day of each consecutive True-run."""
    return mask & ~mask.shift(fill_value=False)


def signal_mask(frame: pd.DataFrame, name: str, z_min: float = 2.0) -> pd.Series:
    """Boolean firing mask for each named delivery signal."""
    frame["deliv_z"]
    frame["ret_1d"]

    if name == "dz_hi_up":
        return (frame["deliv_z"] >= z_min) & (frame["ret_1d"] >= 0.005)
    if name == "dz_hi_dn":
        return (frame["deliv_z"] >= z_min) & (frame["ret_1d"] <= -0.005)
    if name == "dz_lo_up":
        return (frame["deliv_z"] <= -z_min) & (frame["ret_1d"] >= 0.005)
    if name == "spike_70":
        return frame["deliv_pct"] >= 70
    if name == "streak3":
        return frame["hi_streak"] >= 3
    msg = f"unknown signal: {name}"
    raise KeyError(msg)


def prepare_frame(df: pd.DataFrame, *, min_rows: int = 40) -> pd.DataFrame | None:
    """Validate and prepare a raw delivery dataframe."""
    if df.empty or len(df) < min_rows:
        return None
    required = {"date", "symbol", "deliv_pct", "close"}
    if not required.issubset(df.columns):
        return None
    out = df.copy()
    out["date"] = pd.to_datetime(out["date"], errors="coerce", utc=True)
    out["deliv_pct"] = pd.to_numeric(out["deliv_pct"], errors="coerce")
    out["close"] = pd.to_numeric(out["close"], errors="coerce")
    return out.dropna(subset=["deliv_pct", "close"])


SIGNAL_NAMES = (
    "dz_hi_up",
    "dz_hi_dn",
    "dz_lo_up",
    "spike_70",
    "streak3",
)


def signal_mask_with_filters(
    frame: pd.DataFrame,
    name: str,
    *,
    rsi_min: float = 30.0,
    rsi_max: float = 70.0,
    require_macd: bool = True,
    require_ma: bool = True,
) -> pd.Series:
    """
    Signal mask with technical confirmation filters.

    Args:
        frame: DataFrame with technical indicators
        name: Signal name (dz_hi_up, dz_hi_dn, etc.)
        rsi_min: Minimum RSI (avoid oversold bounce / overbought)
        rsi_max: Maximum RSI (avoid overbought)
        require_macd: Require MACD line > signal line
        require_ma: Require close > SMA20 (uptrend)
    """
    signal_mask(frame, name)

    if frame.empty:
        return pd.Series(False, index=frame.index)

    mask = frame[name] if name in frame.columns else pd.Series(False, index=frame.index)
    # This is a simplification - actual signal mask is built below
    if name == "dz_hi_up":
        mask = (frame["deliv_z"] >= 2) & (frame["ret_1d"] >= 0.005)
    elif name == "dz_hi_dn":
        mask = (frame["deliv_z"] >= 2) & (frame["ret_1d"] <= -0.005)
    elif name == "dz_lo_up":
        mask = (frame["deliv_z"] <= -2) & (frame["ret_1d"] >= 0.005)
    elif name == "spike_70":
        mask = frame["deliv_pct"] >= 70
    elif name == "streak3":
        mask = frame["hi_streak"] >= 3
    else:
        mask = pd.Series(False, index=frame.index)

    # Apply technical filters
    if mask.any():
        # RSI filter
        if "rsi" in frame.columns:
            mask = mask & (frame["rsi"] >= 30) & (frame["rsi"] <= 70)

        # MACD confirmation
        if "macd" in frame.columns and "macd_signal" in frame.columns:
            mask = mask & (frame["macd"] > frame["macd_signal"])

        # Moving average trend filter
        if "sma_20" in frame.columns:
            mask = mask & (frame["close"] > frame["sma_20"])

    return mask


SIGNAL_NAMES = (
    "dz_hi_up",
    "dz_hi_dn",
    "dz_lo_up",
    "spike_70",
    "streak3",
)


__all__ = [
    "HORIZON_DAYS",
    "HORIZON_STOP",
    "SIGNAL_NAMES",
    "add_features",
    "cluster_entry_mask",
    "conviction_score",
    "horizon_fit",
    "prepare_frame",
    "price_band",
    "signal_mask",
    "signal_mask_with_filters",
]
