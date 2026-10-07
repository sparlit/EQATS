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
Shared SMC + ICT Detection Engine
===================================
Reusable across NSE India, Gold (XAUUSD), and Bitcoin (BTCUSDT).
All functions operate on pandas DataFrames with OHLCV columns.

Function signatures follow the spec in PART 4 of the requirements.
"""

import numpy as np
import pandas as pd

# ══════════════════════════════════════════════════════════════════
# KILL ZONE TABLES  (all times in IST)
# ══════════════════════════════════════════════════════════════════

_NSE_KZ = [
    (900, 914, "PREP", 0),
    (915, 959, "KZ1", 15),
    (1000, 1114, "DEAD", 0),
    (1115, 1144, "KZ2", 15),
    (1145, 1329, "DEAD", 0),
    (1330, 1414, "KZ3", 15),
    (1415, 1529, "LATE", 0),
    (1530, 2359, "CLOSE", 0),
]

# Shared table for Gold and BTC (same hours, different labels)
_GLOBAL_KZ = [
    (530, 729, "KZ-A", 15),  # Asia open   — Gold:MEDIUM / BTC:MEDIUM
    (730, 1329, "DEAD", 0),  # Quiet        — Gold:SKIP / BTC:WATCH(0pts)
    (1330, 1529, "KZ-L", 15),  # London open  — Gold:HIGHEST / BTC:MEDIUM
    (1530, 1829, "WATCH", 0),  # Mid-session  — Caution (no KZ pts)
    (1830, 2029, "KZ-NY", 15),  # NY open      — Gold:HIGHEST / BTC:HIGHEST
    (2030, 2359, "NIGHT", 0),
    (0, 529, "NIGHT", 0),
]


def get_kill_zone(asset: str, hour: int, minute: int) -> tuple:
    """
    Returns (zone_name: str, score_pts: int).
    asset: 'NSE' | 'GOLD' | 'BTC'
    """
    t = hour * 100 + minute
    table = _NSE_KZ if asset == "NSE" else _GLOBAL_KZ
    for start, end, name, pts in table:
        if start <= t <= end:
            return name, pts
    return "OUTSIDE", 0


def minutes_until_next_kz(asset: str, hour: int, minute: int) -> int:
    """Minutes remaining in current kill zone, or -1 if not in one."""
    t = hour * 100 + minute
    mins = hour * 60 + minute
    table = _NSE_KZ if asset == "NSE" else _GLOBAL_KZ
    for start, end, _name, pts in table:
        if start <= t <= end and pts > 0:
            end_hour, end_min = divmod(end, 100)
            end_mins = end_hour * 60 + end_min
            return end_mins - mins
    return -1


# ══════════════════════════════════════════════════════════════════
# INDICATOR HELPERS
# ══════════════════════════════════════════════════════════════════


def add_vwap(df: pd.DataFrame) -> pd.DataFrame:
    tp = (df["high"] + df["low"] + df["close"]) / 3
    df = df.copy()
    df["vwap"] = (tp * df["volume"]).cumsum() / df["volume"].cumsum()
    return df


def add_vol_ma(df: pd.DataFrame, period: int = 20) -> pd.DataFrame:
    df = df.copy()
    df["vol_ma"] = df["volume"].rolling(period, min_periods=5).mean()
    return df


def add_rsi(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    d = df["close"].diff()
    gain = d.clip(lower=0).ewm(com=period - 1, adjust=False).mean()
    loss = (-d.clip(upper=0)).ewm(com=period - 1, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    df = df.copy()
    df["rsi"] = 100 - 100 / (1 + rs)
    return df


def add_ema(df: pd.DataFrame, periods=(9, 21)) -> pd.DataFrame:
    df = df.copy()
    for p in periods:
        df[f"ema{p}"] = df["close"].ewm(span=p, adjust=False).mean()
    return df


# ══════════════════════════════════════════════════════════════════
# SWING POINT DETECTION
# ══════════════════════════════════════════════════════════════════


def find_swings(df: pd.DataFrame, left: int = 3, right: int = 3) -> tuple:
    """
    Returns (swing_highs, swing_lows).
    Each is a list of (bar_index: int, price: float).
    """
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
# BOS / CHOCH
# ══════════════════════════════════════════════════════════════════


def detect_bos_choch(df: pd.DataFrame, left: int = 2, right: int = 2) -> dict:
    """
    Detects Break of Structure (continuation) or Change of Character (reversal).
    Works on any timeframe.
    Returns: {bos, choch, direction, swing_high, swing_low}
    """
    empty = {"bos": False, "choch": False, "direction": None, "swing_high": None, "swing_low": None}
    if len(df) < (left + right + 4):
        return empty

    highs, lows = find_swings(df, left, right)
    if not highs or not lows:
        return empty

    sh_idx, sh_px = highs[-1]
    sl_idx, sl_px = lows[-1]
    last_close = float(df["close"].iloc[-1])

    result = dict(empty)
    result["swing_high"] = sh_px
    result["swing_low"] = sl_px

    prior_bullish = sh_idx > sl_idx  # most recent swing is a high → up-trend

    if prior_bullish:
        if last_close > sh_px:
            result["bos"] = True
            result["direction"] = "LONG"
        elif last_close < sl_px:
            result["choch"] = True
            result["direction"] = "SHORT"
    else:
        if last_close < sl_px:
            result["bos"] = True
            result["direction"] = "SHORT"
        elif last_close > sh_px:
            result["choch"] = True
            result["direction"] = "LONG"

    return result


# ══════════════════════════════════════════════════════════════════
# ORDER BLOCK
# ══════════════════════════════════════════════════════════════════


def detect_order_block(df: pd.DataFrame, direction: str, lookback: int = 30) -> dict:
    """
    Bullish OB = last bearish candle before bullish BOS (unmitigated).
    Bearish OB = last bullish candle before bearish BOS (unmitigated).
    Returns: {valid, high, low, body_top, body_bot}
    """
    empty = {"valid": False, "high": None, "low": None, "body_top": None, "body_bot": None}
    n = len(df)
    if n < 6:
        return empty

    for i in range(n - 2, max(0, n - lookback), -1):
        row = df.iloc[i]
        o, c = float(row["open"]), float(row["close"])
        h, l = float(row["high"]), float(row["low"])

        if direction == "LONG" and c < o:  # bearish candle = bullish OB
            body_top, body_bot = o, c
            future_lows = df["low"].iloc[i + 1 : n - 1]
            if len(future_lows) == 0 or float(future_lows.min()) > body_bot:
                return {
                    "valid": True,
                    "high": h,
                    "low": l,
                    "body_top": body_top,
                    "body_bot": body_bot,
                }

        elif direction == "SHORT" and c > o:  # bullish candle = bearish OB
            body_top, body_bot = c, o
            future_highs = df["high"].iloc[i + 1 : n - 1]
            if len(future_highs) == 0 or float(future_highs.max()) < body_top:
                return {
                    "valid": True,
                    "high": h,
                    "low": l,
                    "body_top": body_top,
                    "body_bot": body_bot,
                }

    return empty


# ══════════════════════════════════════════════════════════════════
# FAIR VALUE GAP
# ══════════════════════════════════════════════════════════════════


def detect_fvg(df: pd.DataFrame, direction: str, lookback: int = 20) -> dict:
    """
    3-candle imbalance pattern.
    Returns: {exists/valid, upper/top, lower/bot, filled, direction}
    """
    empty = {
        "valid": False,
        "exists": False,
        "top": None,
        "bot": None,
        "filled": False,
        "direction": direction,
    }
    n = len(df)
    if n < 3:
        return empty

    for i in range(n - 3, max(0, n - lookback - 3), -1):
        c1_h = float(df["high"].iloc[i])
        c1_l = float(df["low"].iloc[i])
        c3_h = float(df["high"].iloc[i + 2])
        c3_l = float(df["low"].iloc[i + 2])

        if direction == "LONG":
            gap_bot, gap_top = c1_h, c3_l
            if gap_top > gap_bot:
                future_lows = df["low"].iloc[i + 2 :]
                filled = float(future_lows.min()) <= gap_bot
                if not filled:
                    return {
                        "valid": True,
                        "exists": True,
                        "top": round(gap_top, 4),
                        "bot": round(gap_bot, 4),
                        "filled": False,
                        "direction": direction,
                    }

        elif direction == "SHORT":
            gap_top, gap_bot = c1_l, c3_h
            if gap_top > gap_bot:
                future_highs = df["high"].iloc[i + 2 :]
                filled = float(future_highs.max()) >= gap_top
                if not filled:
                    return {
                        "valid": True,
                        "exists": True,
                        "top": round(gap_top, 4),
                        "bot": round(gap_bot, 4),
                        "filled": False,
                        "direction": direction,
                    }

    return empty


# ══════════════════════════════════════════════════════════════════
# LIQUIDITY SWEEP
# ══════════════════════════════════════════════════════════════════


def detect_liquidity_sweep(
    df: pd.DataFrame, direction: str, pdh=None, pdl=None, tol_pct: float = 0.0015
) -> tuple:
    """
    Buy  setup: wick below equal lows / PDL / swing low, close recovers above.
    Sell setup: wick above equal highs / PDH / swing high, close recovers below.
    Returns: (swept: bool, sweep_level: float | None)
    """
    if len(df) < 4:
        return False, None

    lookback = min(30, len(df) - 1)
    recent = df.iloc[-lookback - 1 : -1]
    prev = df.iloc[-2]
    last = df.iloc[-1]
    cur_close = float(last["close"])

    if direction == "LONG":
        if pdl and float(prev["low"]) < pdl and cur_close > pdl:
            return True, round(float(pdl), 4)
        lows = recent["low"].values
        for i in range(len(lows) - 1, max(0, len(lows) - 20), -1):
            for j in range(i - 1, max(-1, i - 8), -1):
                if abs(lows[i] - lows[j]) <= lows[j] * tol_pct:
                    level = min(lows[i], lows[j])
                    if float(prev["low"]) < level and cur_close > level:
                        return True, round(float(level), 4)
        swing_low = float(recent["low"].min())
        if float(prev["low"]) < swing_low and cur_close > swing_low:
            return True, round(swing_low, 4)

    else:
        if pdh and float(prev["high"]) > pdh and cur_close < pdh:
            return True, round(float(pdh), 4)
        highs = recent["high"].values
        for i in range(len(highs) - 1, max(0, len(highs) - 20), -1):
            for j in range(i - 1, max(-1, i - 8), -1):
                if abs(highs[i] - highs[j]) <= highs[j] * tol_pct:
                    level = max(highs[i], highs[j])
                    if float(prev["high"]) > level and cur_close < level:
                        return True, round(float(level), 4)
        swing_high = float(recent["high"].max())
        if float(prev["high"]) > swing_high and cur_close < swing_high:
            return True, round(swing_high, 4)

    return False, None


# ══════════════════════════════════════════════════════════════════
# OTE — FIBONACCI OPTIMAL TRADE ENTRY
# ══════════════════════════════════════════════════════════════════


def detect_ote(df: pd.DataFrame, direction: str) -> dict:
    """
    True when current price is in the 61.8–79 % retracement zone.
    Returns: {in_zone, fib_level, zone: {upper, lower}}
    """
    empty = {"in_zone": False, "fib_level": None, "zone": {"upper": None, "lower": None}}
    if len(df) < 10:
        return empty

    highs, lows = find_swings(df, left=2, right=2)
    if not highs or not lows:
        return empty

    close = float(df["close"].iloc[-1])

    if direction == "LONG":
        sh_idx, sh_px = highs[-1]
        sl_idx, sl_px = lows[-1]
        if sh_idx <= sl_idx or sh_px <= sl_px:
            return empty
        rng = sh_px - sl_px
        upper = sh_px - 0.618 * rng
        lower = sh_px - 0.790 * rng
        in_zone = lower <= close <= upper
        fib = round((sh_px - close) / rng * 100, 1) if rng else None
        return {
            "in_zone": in_zone,
            "fib_level": fib,
            "zone": {"upper": round(upper, 4), "lower": round(lower, 4)},
        }

    else:  # SHORT
        sh_idx, sh_px = highs[-1]
        sl_idx, sl_px = lows[-1]
        if sl_idx <= sh_idx or sh_px <= sl_px:
            return empty
        rng = sh_px - sl_px
        lower = sl_px + 0.618 * rng
        upper = sl_px + 0.790 * rng
        in_zone = lower <= close <= upper
        fib = round((close - sl_px) / rng * 100, 1) if rng else None
        return {
            "in_zone": in_zone,
            "fib_level": fib,
            "zone": {"upper": round(upper, 4), "lower": round(lower, 4)},
        }


# ══════════════════════════════════════════════════════════════════
# VWAP RECLAIM
# ══════════════════════════════════════════════════════════════════


def detect_vwap_reclaim(df: pd.DataFrame, direction: str) -> bool:
    """
    True only when price dipped below (LONG) or spiked above (SHORT) VWAP
    and then reclaimed — not just "price is above/below VWAP".
    """
    if len(df) < 5 or "vwap" not in df.columns:
        return False
    recent = df.iloc[-8:]
    if direction == "LONG":
        dipped = (recent["close"].iloc[:-1] < recent["vwap"].iloc[:-1]).any()
        reclaim = float(recent["close"].iloc[-1]) > float(recent["vwap"].iloc[-1])
        return dipped and reclaim
    else:
        spiked = (recent["close"].iloc[:-1] > recent["vwap"].iloc[:-1]).any()
        lost = float(recent["close"].iloc[-1]) < float(recent["vwap"].iloc[-1])
        return spiked and lost


# ══════════════════════════════════════════════════════════════════
# REJECTION CANDLE AT OB
# ══════════════════════════════════════════════════════════════════


def detect_rejection_candle(df: pd.DataFrame, direction: str, ob: dict) -> bool:
    """Strong wick-rejection at OB zone with body closing away."""
    if not ob.get("valid") or len(df) < 2:
        return False
    last = df.iloc[-1]
    o, c = float(last["open"]), float(last["close"])
    h, l = float(last["high"]), float(last["low"])
    rng = h - l
    if rng < 1e-9:
        return False
    ob_top = ob.get("body_top", ob.get("high", 0)) or 0
    ob_bot = ob.get("body_bot", ob.get("low", 0)) or 0
    if direction == "LONG":
        return l <= ob_top and c > ob_bot and c > o and (c - l) / rng > 0.55
    else:
        return h >= ob_bot and c < ob_top and c < o and (h - c) / rng > 0.55


# ══════════════════════════════════════════════════════════════════
# VOLUME SIGNATURE
# ══════════════════════════════════════════════════════════════════


def detect_volume_signature(df: pd.DataFrame, threshold: float = 1.5) -> tuple:
    """Returns (is_spike: bool, ratio: float)."""
    if "vol_ma" not in df.columns or len(df) == 0:
        return False, 1.0
    last = df.iloc[-1]
    vol = float(last["volume"])
    vol_ma = max(float(last["vol_ma"]) if not np.isnan(last["vol_ma"]) else 1.0, 1.0)
    ratio = vol / vol_ma
    return ratio >= threshold, round(ratio, 1)


# ══════════════════════════════════════════════════════════════════
# SCORE / VALIDATE HELPERS
# ══════════════════════════════════════════════════════════════════


def signal_strength_label(score: int) -> str:
    if score >= 100:
        return "EXCELLENT"
    if score >= 80:
        return "GOOD"
    return "WEAK"


def validate_trade_params(
    entry: float, sl: float, direction: str, min_rr_t1: float, min_rr_t2: float, max_sl_pct: float
) -> dict:
    """
    Returns {valid, sl_pct, rr_t1, rr_t2, blocked, reason}.
    Calculates T1 and T2 from SL distance and minimum RR.
    """
    risk = abs(entry - sl)
    if risk <= 0:
        return {"valid": False, "blocked": True, "reason": "Zero risk"}

    sl_pct = round(risk / entry * 100, 3)
    if sl_pct > max_sl_pct * 100:
        return {
            "valid": False,
            "blocked": True,
            "reason": f"SL {sl_pct:.2f}% > max {max_sl_pct * 100:.1f}%",
            "sl_pct": sl_pct,
        }

    t1 = (
        round(entry + risk * min_rr_t1, 4)
        if direction == "LONG"
        else round(entry - risk * min_rr_t1, 4)
    )
    t2 = (
        round(entry + risk * min_rr_t2, 4)
        if direction == "LONG"
        else round(entry - risk * min_rr_t2, 4)
    )
    rr_t1 = round(abs(t1 - entry) / risk, 2)
    rr_t2 = round(abs(t2 - entry) / risk, 2)

    return {
        "valid": True,
        "blocked": False,
        "reason": None,
        "sl_pct": sl_pct,
        "t1": t1,
        "t2": t2,
        "rr_t1": rr_t1,
        "rr_t2": rr_t2,
    }
