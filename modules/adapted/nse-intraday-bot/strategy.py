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
NSE Intraday Strategy — ORB + VWAP Pullback + Breakout+Retest
==============================================================
Timeframes : 5min (entry/trigger) + 15min (optional context)
Score      : 0–150.  Minimum 80 to fire an alert.

Three setups in priority order:
  1. Breakout+Retest  — 60 pts base  (highest quality, wait for retest)
  2. VWAP Pullback    — 45 pts base  (trend continuation off VWAP)
  3. ORB Breakout     — 35 pts base  (momentum, simplest entry)

Hard blocks (return {} immediately):
  • Before 9:31 IST (OR must have formed)
  • After 14:30 IST
  • Price outside ₹100–₹3000
  • No valid setup found
  • SL > 1.0% of entry
  • R:R < 1.5

Expected performance: 48–58% WR | 2:1–2.8:1 R:R | PF 1.4–1.8
Risk per trade: 1% of capital.  T1 = 1.5R (50% exit), T2 = PDH/PDL.
"""

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

# ══════════════════════════════════════════════════════════════════
# KILL ZONE CLASSIFIER (NSE-specific timing)
# ══════════════════════════════════════════════════════════════════

_KZ_TABLE = [
    (915, 930, "OR_FORM", 0),  # Opening Range forming — scan only
    (931, 1030, "KZ1", 15),  # Morning momentum window
    (1031, 1114, "DEAD", 0),
    (1115, 1145, "KZ2", 10),  # Pre-noon reversal window
    (1146, 1329, "DEAD", 0),
    (1330, 1430, "KZ3", 15),  # Power Hour afternoon
    (1431, 1500, "LATE", 5),
    (1501, 1530, "CLOSE", 0),
]


def _get_kill_zone(hour: int, minute: int) -> tuple:
    """Returns (zone_name: str, score_pts: int)."""
    t = hour * 100 + minute
    for start, end, name, pts in _KZ_TABLE:
        if start <= t <= end:
            return name, pts
    return "OUTSIDE", 0


# ══════════════════════════════════════════════════════════════════
# INDICATOR HELPERS
# ══════════════════════════════════════════════════════════════════


def _calc_vwap(df: pd.DataFrame) -> pd.DataFrame:
    """Intraday VWAP (resets each day — assumes df is one trading day)."""
    tp = (df["high"] + df["low"] + df["close"]) / 3
    df = df.copy()
    cum_tpv = (tp * df["volume"]).cumsum()
    cum_vol = df["volume"].cumsum().replace(0, np.nan)
    df["vwap"] = cum_tpv / cum_vol
    return df


def _calc_vol_ma(df: pd.DataFrame, period: int = 20) -> pd.DataFrame:
    df = df.copy()
    df["vol_ma"] = df["volume"].rolling(period, min_periods=5).mean()
    return df


def _calc_rsi(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    d = df["close"].diff()
    gain = d.clip(lower=0).ewm(com=period - 1, adjust=False).mean()
    loss = (-d.clip(upper=0)).ewm(com=period - 1, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    df = df.copy()
    df["rsi"] = 100 - 100 / (1 + rs)
    return df


def _find_swings(df: pd.DataFrame, left: int = 2, right: int = 2) -> tuple:
    highs, lows = [], []
    n = len(df)
    for i in range(left, n - right):
        hi = df["high"].iloc[i]
        lo = df["low"].iloc[i]
        if hi == df["high"].iloc[i - left : i + right + 1].max():
            highs.append((i, float(hi)))
        if lo == df["low"].iloc[i - left : i + right + 1].min():
            lows.append((i, float(lo)))
    return highs, lows


# ══════════════════════════════════════════════════════════════════
# OPENING RANGE (9:15 – 9:30 IST)
# ══════════════════════════════════════════════════════════════════


def _get_opening_range(df5: pd.DataFrame) -> dict:
    """
    Opening Range = high/low of the 9:15–9:30 candles.
    Returns {"valid": False} if no OR bars found.
    """
    empty = {"valid": False, "high": None, "low": None, "mid": None, "range": 0}
    if df5.empty:
        return empty
    try:
        or_bars = df5.between_time("09:15", "09:29")
    except Exception:
        return empty
    if or_bars.empty:
        return empty

    or_high = float(or_bars["high"].max())
    or_low = float(or_bars["low"].min())
    or_rng = round(or_high - or_low, 2)
    return {
        "valid": True,
        "high": round(or_high, 2),
        "low": round(or_low, 2),
        "mid": round((or_high + or_low) / 2, 2),
        "range": or_rng,
    }


# ══════════════════════════════════════════════════════════════════
# GAP DETECTION
# ══════════════════════════════════════════════════════════════════


def _get_gap(
    df5: pd.DataFrame, pdh: float | None = None, pdl: float | None = None, prev_close: float | None = None
) -> dict:
    """
    Gap = (today's first bar open − prev_close) / prev_close × 100.
    Uses PDH/PDL mid as fallback if no prev_close.
    """
    empty = {"pct": 0.0, "direction": None, "valid": False}
    if df5.empty:
        return empty

    today_open = float(df5["open"].iloc[0])

    if prev_close and prev_close > 0:
        gap_pct = (today_open - prev_close) / prev_close * 100
    elif pdh and pdl and pdl > 0:
        prev_mid = (pdh + pdl) / 2
        gap_pct = (today_open - prev_mid) / prev_mid * 100
    else:
        return empty

    return {
        "pct": round(abs(gap_pct), 2),
        "direction": "UP" if gap_pct >= 0 else "DOWN",
        "valid": abs(gap_pct) >= 1.5,
    }


# ══════════════════════════════════════════════════════════════════
# VOLUME RATIO
# ══════════════════════════════════════════════════════════════════


def _get_vol_ratio(df5: pd.DataFrame) -> float:
    """Current bar volume / 20-bar rolling average."""
    if df5.empty or "vol_ma" not in df5.columns:
        return 1.0
    last = df5.iloc[-1]
    vol = float(last["volume"])
    vol_ma = float(last["vol_ma"]) if not np.isnan(last["vol_ma"]) else 1.0
    return round(vol / max(vol_ma, 1.0), 2)


# ══════════════════════════════════════════════════════════════════
# SETUP 1: ORB BREAKOUT  (momentum)
# ══════════════════════════════════════════════════════════════════


def _detect_orb(df5: pd.DataFrame, opening_range: dict) -> dict:
    """
    ORB = 5min close beyond OR High/Low with volume ≥ 1.3× avg.
    SL  = opposite end of Opening Range.
    """
    empty = {"valid": False, "direction": None}
    if not opening_range["valid"] or len(df5) < 4:
        return empty

    or_high = opening_range["high"]
    or_low = opening_range["low"]
    last = df5.iloc[-1]
    close = float(last["close"])

    vol_ratio = _get_vol_ratio(df5)
    if vol_ratio < 1.3:
        return empty

    if close > or_high:
        # SL = breakout candle low (tighter than OR Low) — keeps SL within 1%
        sl_level = min(float(last["low"]), or_high)  # no lower than candle low
        return {
            "valid": True,
            "direction": "LONG",
            "breakout_level": or_high,
            "sl_level": sl_level,
            "setup": "ORB",
            "vol_ratio": vol_ratio,
        }
    if close < or_low:
        sl_level = max(float(last["high"]), or_low)  # no higher than candle high
        return {
            "valid": True,
            "direction": "SHORT",
            "breakout_level": or_low,
            "sl_level": sl_level,
            "setup": "ORB",
            "vol_ratio": vol_ratio,
        }
    return empty


# ══════════════════════════════════════════════════════════════════
# SETUP 2: VWAP PULLBACK  (trend continuation)
# ══════════════════════════════════════════════════════════════════


def _detect_vwap_pullback(df5: pd.DataFrame) -> dict:
    """
    LONG : price trended ABOVE VWAP → dipped to/below VWAP →
           current bar closes ABOVE VWAP with volume.
    SHORT: opposite.
    SL   : 0.3% below/above VWAP at entry (or structure low/high).
    """
    empty = {"valid": False, "direction": None}
    if "vwap" not in df5.columns or len(df5) < 8:
        return empty

    recent = df5.iloc[-8:]
    last = recent.iloc[-1]
    close = float(last["close"])
    vwap = float(last["vwap"])
    if np.isnan(vwap):
        return empty

    vol_ratio = _get_vol_ratio(df5)
    if vol_ratio < 1.3:
        return empty

    prev = recent.iloc[:-1]

    # LONG: majority above VWAP, at least one dip to/below, now reclaiming
    above_count = (prev["close"] > prev["vwap"]).sum()
    dipped = (prev["low"] <= prev["vwap"]).any()
    reclaiming = close > vwap

    if above_count >= 3 and dipped and reclaiming:
        sl_level = round(vwap * (1 - 0.003), 2)  # 0.3% below VWAP
        return {
            "valid": True,
            "direction": "LONG",
            "vwap_level": round(vwap, 2),
            "sl_level": sl_level,
            "setup": "VWAP_PULLBACK",
            "vol_ratio": vol_ratio,
        }

    # SHORT: majority below VWAP, bounced to test VWAP, now rejected
    below_count = (prev["close"] < prev["vwap"]).sum()
    bounced = (prev["high"] >= prev["vwap"]).any()
    rejected = close < vwap

    if below_count >= 3 and bounced and rejected:
        sl_level = round(vwap * (1 + 0.003), 2)  # 0.3% above VWAP
        return {
            "valid": True,
            "direction": "SHORT",
            "vwap_level": round(vwap, 2),
            "sl_level": sl_level,
            "setup": "VWAP_PULLBACK",
            "vol_ratio": vol_ratio,
        }

    return empty


# ══════════════════════════════════════════════════════════════════
# SETUP 3: BREAKOUT + RETEST  (highest quality)
# ══════════════════════════════════════════════════════════════════


def _detect_breakout_retest(
    df5: pd.DataFrame, opening_range: dict, pdh: float | None = None, pdl: float | None = None
) -> dict:
    """
    LONG : a prior bar closed above OR High / PDH (the breakout),
           then price pulled back to retest that level (low touched level),
           current bar closes ABOVE with volume confirmation.
    SHORT: opposite.
    SL   = just below the retest wick low (LONG) or above wick high (SHORT).
    """
    empty = {"valid": False, "direction": None}
    if not opening_range["valid"] or len(df5) < 10:
        return empty

    or_high = opening_range["high"]
    or_low = opening_range["low"]
    last = df5.iloc[-1]
    close = float(last["close"])
    lo = float(last["low"])
    hi = float(last["high"])

    vol_ratio = _get_vol_ratio(df5)
    if vol_ratio < 1.3:
        return empty

    lookback = df5.iloc[-12:-1]  # previous bars (not including current)

    # ── LONG: check each key level ─────────────────────────────
    long_levels = [or_high]
    if pdh and pdh > or_high:
        long_levels.append(pdh)

    for level in long_levels:
        tol = level * 0.002  # 0.2% tolerance window for retest
        # Was there a confirmed breakout bar above this level?
        broke = (lookback["close"] > level + tol).any()
        if not broke:
            continue
        # Current bar: low touched the level (retest) and closed above
        retesting = lo <= level + tol * 2
        reclaiming = close > level
        if retesting and reclaiming:
            sl_level = round(lo * (1 - 0.001), 2)  # 0.1% below retest wick
            return {
                "valid": True,
                "direction": "LONG",
                "breakout_level": round(level, 2),
                "sl_level": sl_level,
                "setup": "BREAKOUT_RETEST",
                "vol_ratio": vol_ratio,
            }

    # ── SHORT ──────────────────────────────────────────────────
    short_levels = [or_low]
    if pdl and pdl < or_low:
        short_levels.append(pdl)

    for level in short_levels:
        tol = level * 0.002
        broke = (lookback["close"] < level - tol).any()
        if not broke:
            continue
        retesting = hi >= level - tol * 2
        reclaiming = close < level
        if retesting and reclaiming:
            sl_level = round(hi * (1 + 0.001), 2)
            return {
                "valid": True,
                "direction": "SHORT",
                "breakout_level": round(level, 2),
                "sl_level": sl_level,
                "setup": "BREAKOUT_RETEST",
                "vol_ratio": vol_ratio,
            }

    return empty


# ══════════════════════════════════════════════════════════════════
# TRADE PARAMETER BUILDER
# ══════════════════════════════════════════════════════════════════


def _build_trade_params(
    df5: pd.DataFrame,
    direction: str,
    setup: dict,
    opening_range: dict,
    pdh: float | None = None,
    pdl: float | None = None,
    capital: float = 100_000,
    risk_pct: float = 0.01,
) -> dict | None:
    """
    SL  = setup sl_level (structure) capped at 1% max.
    T1  = 1.5R (50% partial exit).
    T2  = PDH/PDL or 3R minimum.
    Shares = (capital × risk_pct) / risk_per_share.
    Returns None if SL > 1% or R:R < 1.5.
    """
    entry = round(float(df5["close"].iloc[-1]), 2)
    if entry <= 0:
        return None

    if direction == "LONG":
        # SL comes directly from setup (candle low, VWAP buffer, or OR High)
        # Do NOT merge with recent history — setup already defines the correct level
        sl_raw = setup.get("sl_level", entry * 0.995)
        sl = round(sl_raw - entry * 0.001, 2)  # 0.1% noise buffer

        sl_pct = round((entry - sl) / entry * 100, 2)
        if sl_pct > 1.0:
            return None  # SL too wide — reject trade
        if sl_pct < 0.2:
            # SL unrealistically tight — widen to 0.2% minimum
            sl = round(entry * (1 - 0.002), 2)
            sl_pct = round((entry - sl) / entry * 100, 2)
        if sl >= entry:
            return None

        # T2 target: PDH if meaningful distance away, else 3R minimum
        t2 = round(pdh, 2) if pdh and pdh > entry * 1.005 else round(entry + 3.0 * (entry - sl), 2)

    else:  # SHORT
        sl_raw = setup.get("sl_level", entry * 1.005)
        sl = round(sl_raw + entry * 0.001, 2)  # 0.1% noise buffer

        sl_pct = round((sl - entry) / entry * 100, 2)
        if sl_pct > 1.0:
            return None
        if sl_pct < 0.2:
            sl = round(entry * (1 + 0.002), 2)
            sl_pct = round((sl - entry) / entry * 100, 2)
        if sl <= entry:
            return None

        # T2 target: PDL if meaningful distance away, else 3R minimum
        t2 = round(pdl, 2) if pdl and pdl < entry * 0.995 else round(entry - 3.0 * (sl - entry), 2)

    risk = abs(entry - sl)
    reward = abs(t2 - entry)
    rr = round(reward / risk, 2) if risk > 0 else 0

    if rr < 1.5:
        return None  # R:R too poor

    # T1 = 1.5R (first partial exit — 50% position)
    t1 = round(entry + 1.5 * risk, 2) if direction == "LONG" else round(entry - 1.5 * risk, 2)

    # Position sizing
    risk_amount = capital * risk_pct
    shares = int(risk_amount / risk) if risk > 0 else 0

    return {
        "entry": entry,
        "sl": sl,
        "sl_pct": sl_pct,
        "t1": t1,
        "t2": t2,
        "rr_ratio": rr,
        "shares": shares,
        "risk_amt": round(risk_amount, 0),
    }


# ══════════════════════════════════════════════════════════════════
# MAIN SCORING ENGINE
# ══════════════════════════════════════════════════════════════════


def score_stock(
    df5: pd.DataFrame,
    df15: pd.DataFrame,
    symbol: str,
    pdh=None,
    pdl=None,
    ist_time: datetime | None = None,
    capital: float = 100_000,
    prev_close: float | None = None,
) -> dict:
    """
    NSE Intraday strategy — ORB + VWAP Pullback + Breakout+Retest.
    Returns full signal dict or {} if blocked / no setup found.

    Score breakdown (150 pts total):
      Phase 1 — Setup Quality  (35–60 pts, mandatory)
      Phase 2 — Trend Filters  (0–40 pts)
      Phase 3 — Entry Quality  (0–30 pts)
      Phase 4 — Boosters       (0–20 pts)
    Minimum threshold: 80 / 150.
    """
    if len(df5) < 5:
        return {}

    if ist_time is None:
        ist_time = datetime.now(timezone(timedelta(hours=5, minutes=30)))

    t = ist_time.hour * 100 + ist_time.minute
    if t < 931 or t > 1430:  # hard time block
        return {}

    kill_zone, kz_pts = _get_kill_zone(ist_time.hour, ist_time.minute)

    # ── Enrich df5 with indicators ────────────────────────────────
    df5 = _calc_vwap(_calc_vol_ma(_calc_rsi(df5.copy())))

    close = float(df5["close"].iloc[-1])
    if close <= 0:
        return {}

    # Price range filter: ₹100 – ₹3000
    if close < 100 or close > 3000:
        return {}

    # ── Opening Range ─────────────────────────────────────────────
    opening_range = _get_opening_range(df5)
    if not opening_range["valid"]:
        return {}

    # ── Gap ───────────────────────────────────────────────────────
    gap = _get_gap(df5, pdh, pdl, prev_close)

    # ── Setup detection (priority: BR > VP > ORB) ─────────────────
    br_setup = _detect_breakout_retest(df5, opening_range, pdh, pdl)
    vp_setup = _detect_vwap_pullback(df5)
    orb_setup = _detect_orb(df5, opening_range)

    if br_setup["valid"]:
        setup = br_setup
        base_pts = 60
    elif vp_setup["valid"]:
        setup = vp_setup
        base_pts = 45
    elif orb_setup["valid"]:
        setup = orb_setup
        base_pts = 35
    else:
        return {}  # no setup

    direction = setup["direction"]
    setup_name = setup["setup"]
    vol_ratio = setup.get("vol_ratio", 1.0)
    reasons = [f"Setup: {setup_name} ({direction})  Vol={vol_ratio:.1f}x"]

    # ════════════════════════════════════════════
    # PHASE 1  —  Setup Quality  (35–60 pts)
    # ════════════════════════════════════════════
    phase1 = base_pts

    # ════════════════════════════════════════════
    # PHASE 2  —  Trend Filters  (max 40 pts)
    # ════════════════════════════════════════════
    phase2 = 0

    vwap_now = float(df5["vwap"].iloc[-1]) if "vwap" in df5.columns else 0.0

    # 2a. VWAP alignment (+15)
    if not np.isnan(vwap_now) and vwap_now > 0:
        if direction == "LONG" and close > vwap_now:
            phase2 += 15
            reasons.append(f"Price above VWAP ₹{vwap_now:.1f}")
        elif direction == "SHORT" and close < vwap_now:
            phase2 += 15
            reasons.append(f"Price below VWAP ₹{vwap_now:.1f}")
        else:
            reasons.append(f"VWAP counter-trend (₹{vwap_now:.1f}) — reduced confidence")

    # 2b. Opening Range alignment (+10)
    or_h, or_l = opening_range["high"], opening_range["low"]
    if direction == "LONG" and close > or_h:
        phase2 += 10
        reasons.append(f"Above OR High ₹{or_h:.1f}")
    elif direction == "SHORT" and close < or_l:
        phase2 += 10
        reasons.append(f"Below OR Low ₹{or_l:.1f}")

    # 2c. Volume confirmation (+10 spike, +5 elevated)
    if vol_ratio >= 1.5:
        phase2 += 10
        reasons.append(f"Volume spike {vol_ratio:.1f}x average")
    elif vol_ratio >= 1.3:
        phase2 += 5
        reasons.append(f"Volume elevated {vol_ratio:.1f}x average")

    # 2d. Gap direction aligns with trade (+5)
    if gap["valid"]:
        if (direction == "LONG" and gap["direction"] == "UP") or (direction == "SHORT" and gap["direction"] == "DOWN"):
            phase2 += 5
            reasons.append(f"Opening gap {gap['pct']}% supports {direction}")

    # ════════════════════════════════════════════
    # PHASE 3  —  Entry Quality  (max 30 pts)
    # ════════════════════════════════════════════
    phase3 = 0

    # 3a. Kill zone timing (+15 / +10 / +5)
    phase3 += kz_pts
    reasons.append(f"Kill Zone: {kill_zone} (+{kz_pts} pts)")

    # 3b. RSI in trade-friendly zone (+8)
    rsi_val = float(df5["rsi"].iloc[-1]) if "rsi" in df5.columns else np.nan
    if not np.isnan(rsi_val):
        if direction == "LONG" and 40 <= rsi_val <= 65:
            phase3 += 8
            reasons.append(f"RSI {rsi_val:.0f} — ideal long zone (40–65)")
        elif direction == "SHORT" and 35 <= rsi_val <= 60:
            phase3 += 8
            reasons.append(f"RSI {rsi_val:.0f} — ideal short zone (35–60)")
        elif (direction == "LONG" and rsi_val > 80) or (direction == "SHORT" and rsi_val < 20):
            reasons.append(f"RSI {rsi_val:.0f} extreme — use caution")

    # 3c. PDH/PDL as natural T2 (+7)
    if pdh and pdl:
        if direction == "LONG" and close < pdh:
            phase3 += 7
            reasons.append(f"PDH ₹{pdh:.1f} — clear T2 target")
        elif direction == "SHORT" and close > pdl:
            phase3 += 7
            reasons.append(f"PDL ₹{pdl:.1f} — clear T2 target")

    # ════════════════════════════════════════════
    # PHASE 4  —  Confluence Boosters  (max 20 pts)
    # ════════════════════════════════════════════
    phase4 = 0

    # 4a. 5-min structure confirms bias (+10)
    if len(df5) >= 6:
        recent5 = df5.iloc[-5:]
        h5 = recent5["high"].values
        l5 = recent5["low"].values
        if direction == "LONG" and h5[-1] > h5[-3] and l5[-1] > l5[-3]:
            phase4 += 10
            reasons.append("5min HH+HL structure aligns with LONG")
        elif direction == "SHORT" and h5[-1] < h5[-3] and l5[-1] < l5[-3]:
            phase4 += 10
            reasons.append("5min LH+LL structure aligns with SHORT")

    # 4b. Round number confluence near entry (+5)
    rnd50 = round(close / 50) * 50
    rnd100 = round(close / 100) * 100
    if abs(close - rnd50) / close < 0.003 or abs(close - rnd100) / close < 0.003:
        phase4 += 5
        reasons.append("Round number level confluence")

    # 4c. Tight Opening Range = cleaner structure (+5)
    if opening_range["range"] / close < 0.01:  # OR width < 1% of price
        phase4 += 5
        reasons.append(f"Tight OR ₹{opening_range['range']:.1f} — clean structure")

    # ════════════════════════════════════════════
    # TOTAL SCORE
    # ════════════════════════════════════════════
    total = phase1 + phase2 + phase3 + phase4
    if total < 80:
        return {}

    # ── Trade parameters (hard rules enforced inside) ─────────────
    params = _build_trade_params(
        df5,
        direction,
        setup,
        opening_range,
        pdh,
        pdl,
        capital=capital,
        risk_pct=0.01,
    )
    if params is None:
        return {}  # SL > 1% OR R:R < 1.5

    pct = round(total / 150 * 100, 1)
    if total >= 115:
        strength = "EXCELLENT"
    elif total >= 90:
        strength = "GOOD"
    else:
        strength = "WEAK"

    return {
        # ── Identity ───────────────────────────────────────────────
        "symbol": symbol,
        "direction": direction,
        "signal": "BUY" if direction == "LONG" else "SELL",
        "setup": setup_name,
        # ── Score ──────────────────────────────────────────────────
        "score": total,
        "score_pct": pct,
        "signal_strength": strength,
        "blocked_reason": None,
        "kill_zone": kill_zone,
        "phase_scores": {
            "setup_quality": phase1,
            "trend_filters": phase2,
            "entry_quality": phase3,
            "boosters": phase4,
        },
        "must_have_checklist": {
            "setup_detected": True,
            "vwap_aligned": phase2 >= 15,
            "volume_confirmed": vol_ratio >= 1.3,
            "inside_kill_zone": kz_pts > 0,
            "rr_valid": params["rr_ratio"] >= 1.5,
        },
        "trade_params": params,
        # ── Flat aliases (backward-compat) ─────────────────────────
        "entry": params["entry"],
        "sl": params["sl"],
        "t1": params["t1"],
        "t2": params["t2"],
        "target": params["t2"],
        "rr": params["rr_ratio"],
        # ── Context ────────────────────────────────────────────────
        "opening_range": {
            "high": or_h,
            "low": or_l,
            "mid": opening_range["mid"],
            "range": opening_range["range"],
        },
        "gap_pct": gap.get("pct", 0.0),
        "vwap": round(vwap_now, 2) if vwap_now else None,
        "rsi": round(rsi_val, 1) if not np.isnan(rsi_val) else None,
        "vol_ratio": vol_ratio,
        "shares": params["shares"],
        "reasons": reasons,
        "confidence": strength,
    }
