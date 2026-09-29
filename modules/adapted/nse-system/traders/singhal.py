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
Aseem Singhal — 51 Trading Strategies.
Classified: MULTI (Swing + Positional, long-only, daily-bar only).

18 methods implemented per owner instruction I75:
  Ch 1 (Swing, 7): BB+9EMA, Williams+MACD+SMA, MACD+Fib,
                   Triangle BO, Gap Retracement, BB Width,
                   Ichimoku Cloud
  Ch 4 (Positional, 4): Macro Trend Pivot, Supertrend+RSI,
                        Sector RS, M&W RSI
  Ch 7 (More, 7): 9/21 EMA, Positional BO, Pin Bar,
                  Pullback-Retest, Repo Rate, VCP, Two-Leg

Skipped (documented in extraction, out of scope):
  Ch 2 (Intraday 5-30m, 7), Ch 3 (SMC/Elliott/Gann/Fractal/
  Renko/Donchian, 7), Ch 5 (Scalping 1-5m, 6), Ch 6 (Options, 13)

R42 — no proxies. Every indicator computed inline with the book's
exact parameters. Method 49 (Repo Rate) returns zero signals until
DR-23 (RBI repo rate) is supplied by the owner.

R35 safety: _fmt_num + _try_emit from day one.
R40 exits: every signal carries raw.exits (thesis + hard_number +
condition).
R41 overlap marking: signals carry overlaps_with where applicable.
"""
import db
import numpy as np
import pandas as pd
from log_utils import get_logger
from universe_helper import band_universe

log = get_logger("trader.singhal")

SLUG = "singhal"
NAME = "Aseem Singhal"
PILLAR = "multi"
SOURCE = "51 Trading Strategies (India)"


# ----------------------------------------------------------------
# Tunables — book-cited parameters
# ----------------------------------------------------------------
TICK = 0.05
MIN_PRICE = 100
MIN_BARS = 200
DEFAULT_LIMIT = 800

VOL_MIN = 0.5
VOL_CONFIRM = 1.2
VOL_BREAKOUT = 1.5
VOL_STRONG = 2.0

# Bollinger
BB_PERIOD = 20
BB_STD = 2.0
BB_WIDTH_FLAT_LOOKBACK = 20

# Williams %R
WR_PERIOD = 14
WR_PULLBACK = -50.0
WR_OVERBOUGHT = -20.0

# MACD
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9

# Fibonacci retracement
FIB_LEVELS = [0.382, 0.500, 0.618]
FIB_TOLERANCE = 0.015

# Ichimoku
ICH_TENKAN = 9
ICH_KIJUN = 26
ICH_SENKOU_B = 52

# Supertrend
ST_PERIOD = 10
ST_MULT = 3.0

# Pivot Points (classic)
PIVOT_TOLERANCE = 0.01

# Repo Rate (external, owner-supplied — DR-23)
REPO_RATE_CURRENT = None  # owner sets; None = method silent
REPO_RATE_PRIOR = None


# ----------------------------------------------------------------
# METHODS registry — 18 total
# ----------------------------------------------------------------
METHODS = [
    # ---- Ch 1: Swing (7) ----
    {
        "id": "bb_9ema_swing",
        "name": "BB + 9 EMA Swing",
        "description": "Rejection at BB lower band + bullish candle above 9 EMA.",
        "direction": "long",
        "scan": True,
        "confidence": "MED",
    },
    {
        "id": "williams_macd_sma_swing",
        "name": "Williams %R + MACD + 14 SMA",
        "description": "Williams %R pullback to -50 + MACD + price > 14 SMA.",
        "direction": "long",
        "scan": True,
        "confidence": "MED",
    },
    {
        "id": "macd_fib_swing",
        "name": "MACD + Fibonacci Swing",
        "description": "Pullback to Fib 38.2/50/61.8 + MACD confirmation.",
        "direction": "long",
        "scan": True,
        "confidence": "MED",
    },
    {
        "id": "triangle_breakout_swing",
        "name": "Triangle Breakout",
        "description": "Triangle + volume squeeze + breakout above resistance on volume.",
        "direction": "long",
        "scan": True,
        "confidence": "HIGH",
    },
    {
        "id": "institutional_gap_retracement",
        "name": "Institutional Gap Retracement",
        "description": "Breakaway gap + first retracement + reversal.",
        "direction": "long",
        "scan": True,
        "confidence": "MED",
    },
    {
        "id": "bb_width_breakout",
        "name": "BB Width Breakout",
        "description": "BB squeeze → width expansion → breakout.",
        "direction": "long",
        "scan": True,
        "confidence": "HIGH",
    },
    {
        "id": "ichimoku_cloud_swing",
        "name": "Ichimoku Cloud Swing",
        "description": "Tenkan > Kijun + close above cloud.",
        "direction": "long",
        "scan": True,
        "confidence": "HIGH",
    },
    # ---- Ch 4: Positional (4) ----
    {
        "id": "macro_trend_pivot",
        "name": "Macro Trend Pivot (Positional)",
        "description": "Uptrend + price at support (P, S1, S2) + bullish candle.",
        "direction": "long",
        "scan": True,
        "confidence": "MED",
    },
    {
        "id": "supertrend_rsi_positional",
        "name": "Supertrend + RSI (Positional)",
        "description": "Supertrend below + RSI > 60.",
        "direction": "long",
        "scan": True,
        "confidence": "HIGH",
    },
    {
        "id": "sector_rs_positional",
        "name": "Sector RS (Positional)",
        "description": "Top-decile sector RS + leading stock.",
        "direction": "long",
        "scan": True,
        "confidence": "MED",
    },
    {
        "id": "mw_rsi_positional",
        "name": "M&W RSI (Positional)",
        "description": "RSI W at oversold.",
        "direction": "long",
        "scan": True,
        "confidence": "MED",
    },
    # ---- Ch 7: More (7) ----
    {
        "id": "ema9_21_support",
        "name": "9 & 21 EMA Support",
        "description": "Fresh 9>21 EMA cross + breakout.",
        "direction": "long",
        "scan": True,
        "confidence": "HIGH",
    },
    {
        "id": "positional_breakout_volume",
        "name": "Positional Breakout + Volume",
        "description": "15-20% rally + consolidation + volume breakout.",
        "direction": "long",
        "scan": True,
        "confidence": "HIGH",
    },
    {
        "id": "pin_bar_reversal",
        "name": "Pin Bar Reversal",
        "description": "Pin Bar at range support + confirmation.",
        "direction": "long",
        "scan": True,
        "confidence": "MED",
    },
    {
        "id": "pullback_retest",
        "name": "Pullback and Retest",
        "description": "Breakout + retest of resistance + reversal candle.",
        "direction": "long",
        "scan": True,
        "confidence": "HIGH",
    },
    {
        "id": "repo_rate_trading",
        "name": "Repo Rate Trading",
        "description": "Buy on RBI cut, sell on hike. Silent until DR-23.",
        "direction": "long",
        "scan": True,
        "confidence": "MED",
    },
    {
        "id": "vcp_breakout",
        "name": "VCP Breakout",
        "description": "3+ successively shorter pullbacks + volume breakout.",
        "direction": "long",
        "scan": True,
        "confidence": "HIGH",
    },
    {
        "id": "two_legged_pullback",
        "name": "Two-Legged Pullback",
        "description": "Uptrend + two consecutive pullbacks + breakout.",
        "direction": "long",
        "scan": True,
        "confidence": "MED",
    },
]


# ----------------------------------------------------------------
# R35 helpers
# ----------------------------------------------------------------
def _safe_f(v):
    if v is None:
        return None
    try:
        f = float(v)
        if np.isnan(f) or np.isinf(f):
            return None
        return f
    except (TypeError, ValueError):
        return None


def _fmt_num(v, dp=2):
    if v is None:
        return "—"
    try:
        f = float(v)
        if np.isnan(f) or np.isinf(f):
            return "—"
        return f"{f:.{dp}f}"
    except (TypeError, ValueError):
        return "—"


def _try_emit(sigs, fn):
    try:
        s = fn()
        if s is None:
            return
        if isinstance(s, list):
            sigs.extend(s)
        else:
            sigs.append(s)
    except Exception as e:
        log.warning(f"signal emit skipped: {e}")


# ----------------------------------------------------------------
# Data loader
# ----------------------------------------------------------------
def _load_df(conn, sym, limit=500):
    rows = conn.execute(
        "SELECT date, open, high, low, close, volume FROM prices_daily WHERE symbol=? ORDER BY date DESC LIMIT ?",
        (sym, limit),
    ).fetchall()
    if not rows or len(rows) < MIN_BARS:
        return None
    rows = list(reversed(rows))
    df = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "volume"])
    for c in ["open", "high", "low", "close", "volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["close"]).reset_index(drop=True)
    if len(df) < MIN_BARS:
        return None
    return df


# ----------------------------------------------------------------
# Inline indicators
# ----------------------------------------------------------------
def _sma(arr, period):
    if len(arr) < period:
        return None
    return float(np.mean(arr[-period:]))


def _ema(arr, span):
    return pd.Series(arr).ewm(span=span, adjust=False).mean().values


def _atr(df, period=14):
    h = df["high"].values.astype(float)
    l = df["low"].values.astype(float)
    c = df["close"].values.astype(float)
    n = len(c)
    if n < period + 1:
        return None
    tr = np.zeros(n)
    tr[0] = h[0] - l[0]
    for i in range(1, n):
        tr[i] = max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
    alpha = 2.0 / (period + 1)
    atr = tr[0]
    for i in range(1, n):
        atr = alpha * tr[i] + (1 - alpha) * atr
    return float(atr)


def _bollinger(closes, period=BB_PERIOD, num_std=BB_STD):
    """Return (upper, lower, baseline, width) for latest bar."""
    if len(closes) < period:
        return None, None, None, None
    window = closes[-period:]
    mid = float(np.mean(window))
    std = float(np.std(window))
    upper = mid + num_std * std
    lower = mid - num_std * std
    width = (upper - lower) / mid if mid > 0 else 0.0
    return upper, lower, mid, width


def _bb_width_series(closes, period=BB_PERIOD, num_std=BB_STD, n=25):
    """Return list of BB widths over the last n bars."""
    if len(closes) < period + n:
        return []
    out = []
    for i in range(len(closes) - n, len(closes)):
        w = _bollinger(closes[: i + 1], period, num_std)[3]
        if w is not None:
            out.append(w)
    return out


def _williams_r(highs, lows, closes, period=WR_PERIOD):
    if len(closes) < period:
        return None
    hh = float(np.max(highs[-period:]))
    ll = float(np.min(lows[-period:]))
    if hh == ll:
        return -50.0
    return -100.0 * (hh - closes[-1]) / (hh - ll)


def _macd(closes, fast=MACD_FAST, slow=MACD_SLOW, signal=MACD_SIGNAL):
    if len(closes) < slow + signal:
        return None, None
    ef = _ema(closes, fast)
    es = _ema(closes, slow)
    line = ef - es
    sig = _ema(line, signal)
    return line, sig


def _fib_levels(high, low):
    if high <= low or low <= 0:
        return {}
    rng = high - low
    return {level: high - level * rng for level in FIB_LEVELS}


def _at_fib(price, fib_dict, tol=FIB_TOLERANCE):
    for level, lvl_price in fib_dict.items():
        if lvl_price <= 0:
            continue
        if abs(price - lvl_price) / lvl_price <= tol:
            return level
    return None


def _ichimoku(highs, lows, closes):
    """Return dict with tenkan, kijun, span_a, span_b, cloud_top, cloud_bottom."""
    if len(closes) < ICH_SENKOU_B + 26:
        return None

    def _mid(h, l, n):
        if len(h) < n:
            return None
        return (float(np.max(h[-n:])) + float(np.min(l[-n:]))) / 2.0

    tenkan = _mid(highs, lows, ICH_TENKAN)
    kijun = _mid(highs, lows, ICH_KIJUN)
    span_a_raw = (tenkan + kijun) / 2.0 if (tenkan and kijun) else None
    span_b_raw = _mid(highs, lows, ICH_SENKOU_B)
    # Shift back by Kijun to get current-visible cloud
    if span_a_raw is None or span_b_raw is None:
        return None
    if len(closes) < ICH_KIJUN:
        return None
    tenkan_prev = (
        float(np.max(highs[-ICH_KIJUN - ICH_TENKAN : -ICH_KIJUN]))
        + float(np.min(lows[-ICH_KIJUN - ICH_TENKAN : -ICH_KIJUN]))
    ) / 2.0
    kijun_prev = (
        float(np.max(highs[-2 * ICH_KIJUN : -ICH_KIJUN])) + float(np.min(lows[-2 * ICH_KIJUN : -ICH_KIJUN]))
    ) / 2.0
    span_a = (tenkan_prev + kijun_prev) / 2.0
    span_b = (
        float(np.max(highs[-ICH_KIJUN - ICH_SENKOU_B : -ICH_KIJUN]))
        + float(np.min(lows[-ICH_KIJUN - ICH_SENKOU_B : -ICH_KIJUN]))
    ) / 2.0
    top = max(span_a, span_b)
    bot = min(span_a, span_b)
    return {"tenkan": tenkan, "kijun": kijun, "span_a": span_a, "span_b": span_b, "cloud_top": top, "cloud_bottom": bot}


def _supertrend(df, period=ST_PERIOD, mult=ST_MULT):
    """Return (line, direction) for latest bar. direction 1=up, -1=down."""
    h = df["high"].values.astype(float)
    l = df["low"].values.astype(float)
    c = df["close"].values.astype(float)
    n = len(c)
    if n < period + 5:
        return None, None
    tr = np.zeros(n)
    tr[0] = h[0] - l[0]
    for i in range(1, n):
        tr[i] = max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
    atr = np.zeros(n)
    atr[period - 1] = np.mean(tr[:period])
    for i in range(period, n):
        atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period
    hl2 = (h + l) / 2.0
    upper = hl2 + mult * atr
    lower = hl2 - mult * atr
    st = np.zeros(n)
    dir_ = np.ones(n, dtype=int)
    st[period - 1] = upper[period - 1]
    for i in range(period, n):
        if c[i] > st[i - 1]:
            dir_[i] = 1
            st[i] = max(lower[i], st[i - 1]) if dir_[i - 1] == 1 else lower[i]
        else:
            dir_[i] = -1
            st[i] = min(upper[i], st[i - 1]) if dir_[i - 1] == -1 else upper[i]
    return float(st[-1]), int(dir_[-1])


def _pivot_points(prev_high, prev_low, prev_close):
    if None in (prev_high, prev_low, prev_close):
        return None
    p = (prev_high + prev_low + prev_close) / 3.0
    r1 = 2 * p - prev_low
    s1 = 2 * p - prev_high
    r2 = p + (prev_high - prev_low)
    s2 = p - (prev_high - prev_low)
    return {"P": p, "R1": r1, "R2": r2, "S1": s1, "S2": s2}


def _candle_shape(df, i):
    o = float(df["open"].iloc[i])
    h = float(df["high"].iloc[i])
    l = float(df["low"].iloc[i])
    c = float(df["close"].iloc[i])
    rng = h - l
    if rng <= 0:
        return None
    body = abs(c - o)
    upper = h - max(o, c)
    lower = min(o, c) - l
    return {
        "open": o,
        "high": h,
        "low": l,
        "close": c,
        "rng": rng,
        "body": body,
        "upper": upper,
        "lower": lower,
        "close_pos": (c - l) / rng,
        "is_bull": c > o,
    }


def _is_pin_bar(s):
    """Small body, one dominant wick."""
    if s is None:
        return None
    body_ratio = s["body"] / s["rng"] if s["rng"] > 0 else 1.0
    if body_ratio > 0.35:
        return None
    if s["lower"] >= 2.0 * s["body"] and s["lower"] >= 0.5 * s["rng"]:
        return "bull"
    if s["upper"] >= 2.0 * s["body"] and s["upper"] >= 0.5 * s["rng"]:
        return "bear"
    return None


def _pivots(values, k=3, lookback=120, kind="low"):
    n = len(values)
    start = max(k, n - lookback)
    out = []
    for i in range(start, n - k):
        win = values[i - k : i + k + 1]
        if (kind == "low" and values[i] == win.min()) or (kind == "high" and values[i] == win.max()):
            out.append((i, float(values[i])))
    return out


def _vol_ratio(df, period=20):
    v = df["volume"].values.astype(float)
    avg = _sma(v, period)
    if avg is None or avg <= 0:
        return None
    return float(v[-1]) / avg


def _consolidation(df, n=20):
    """Return (range_pct, vol_ratio) for last n bars excluding today."""
    if len(df) < n + 1:
        return None, None
    h = df["high"].values.astype(float)[-n - 1 : -1]
    l = df["low"].values.astype(float)[-n - 1 : -1]
    v = df["volume"].values.astype(float)[-n - 1 : -1]
    avg_price = float(np.mean(df["close"].values[-n - 1 : -1]))
    if avg_price <= 0:
        return None, None
    rng = (float(np.max(h)) - float(np.min(l))) / avg_price
    avg_v = float(np.mean(v)) if len(v) else 0
    today_v = float(df["volume"].iloc[-1])
    vr = today_v / avg_v if avg_v > 0 else None
    return rng, vr


def _vcp_pattern(df, min_pullbacks=3):
    """Return dict {pullback_count, ranges, range_pct} or None.
    (2026-09-25: renamed from _detect_vcp - the method wrapper of the
    same name further down shadowed it, so VCP never emitted.)"""
    n = len(df)
    if n < 60:
        return None
    h = df["high"].values.astype(float)
    l = df["low"].values.astype(float)
    df["close"].values.astype(float)
    piv_h = _pivots(h, k=3, lookback=60, kind="high")
    piv_l = _pivots(l, k=3, lookback=60, kind="low")
    if len(piv_l) < min_pullbacks or len(piv_h) < min_pullbacks:
        return None
    # Pair up successive swing highs and lows, compute pullback depth
    ranges = []
    for i in range(min(len(piv_h), len(piv_l), 4)):
        hi = piv_h[-(i + 1)][1]
        lo = piv_l[-(i + 1)][1]
        if hi <= 0:
            continue
        ranges.append((hi - lo) / hi)
    if len(ranges) < min_pullbacks:
        return None
    # Successively shorter?
    for i in range(1, len(ranges)):
        if ranges[i - 1] <= ranges[i]:
            return None
    return {"pullback_count": len(ranges), "ranges": [round(r, 4) for r in ranges], "range_pct": round(ranges[-1], 4)}


def _detect_two_leg_pullback(df):
    """Higher highs + higher lows + two consecutive pullbacks."""
    n = len(df)
    if n < 60:
        return None
    h = df["high"].values.astype(float)
    l = df["low"].values.astype(float)
    piv_h = _pivots(h, k=3, lookback=60, kind="high")
    piv_l = _pivots(l, k=3, lookback=60, kind="low")
    if len(piv_h) < 3 or len(piv_l) < 3:
        return None
    highs = [p[1] for p in piv_h[-3:]]
    lows = [p[1] for p in piv_l[-3:]]
    if not (highs[0] < highs[1] < highs[2]):
        return None
    if not (lows[0] < lows[1] < lows[2]):
        return None
    return {"highs": highs, "lows": lows}


# ----------------------------------------------------------------
# Exit block builder (R40)
# ----------------------------------------------------------------
def _mk_exits(
    stop_hard,
    stop_thesis,
    stop_condition,
    target_hard,
    target_thesis,
    target_condition,
    offset_thesis,
    offset_trigger,
    invalidation_thesis,
    invalidation_condition,
    time_exit_sessions=None,
    time_exit_thesis=None,
):
    return {
        "stop_out": {
            "thesis": stop_thesis,
            "hard_number": (round(float(stop_hard), 2) if stop_hard is not None else None),
            "condition": stop_condition,
        },
        "target": {
            "thesis": target_thesis,
            "hard_number": (round(float(target_hard), 2) if target_hard is not None else None),
            "condition": target_condition,
        },
        "offset": {"thesis": offset_thesis, "trigger": offset_trigger},
        "invalidation": {"thesis": invalidation_thesis, "condition": invalidation_condition},
        "exhaustion": None,
        "time_exit": ({"thesis": time_exit_thesis, "sessions": time_exit_sessions} if time_exit_sessions else None),
    }


def _signal(sym, method_id, entry, stop, target, confidence, notes, raw, overlaps_with=None):
    sig = {
        "symbol": sym,
        "trader": SLUG,
        "method": method_id,
        "direction": "BULLISH",
        "signal_type": "LONG_SETUP",
        "entry": round(float(entry), 2) if entry is not None else None,
        "stop": round(float(stop), 2) if stop is not None else None,
        "target": round(float(target), 2) if target is not None else None,
        "confidence": confidence,
        "notes": notes,
        "raw": raw,
    }
    if overlaps_with:
        sig["overlaps_with"] = overlaps_with
    return sig


def _default_stop(entry, df):
    """Structural stop: 2× ATR below entry."""
    atr = _atr(df, 14)
    if atr is None or atr <= 0:
        return entry * 0.95
    return entry - 2.0 * atr


# ============================================================
# Ch 1 — Swing methods (7)
# ============================================================
def _detect_bb_9ema(sym, df):
    closes = df["close"].values.astype(float)
    if len(closes) < BB_PERIOD + 10:
        return []
    upper, lower, mid, width = _bollinger(closes, BB_PERIOD, BB_STD)
    if lower is None:
        return []
    ema9 = _ema(closes, 9)
    if closes[-1] <= ema9[-1]:
        return []
    # Setup: prior candle touched/broke lower band, today bullish
    prior = _candle_shape(df, len(df) - 2)
    cur = _candle_shape(df, len(df) - 1)
    if prior is None or cur is None:
        return []
    if prior["low"] > lower:
        return []
    if not cur["is_bull"]:
        return []
    entry = closes[-1]
    stop = cur["low"]
    target = entry + 2.0 * (entry - stop)
    vr = _vol_ratio(df)
    if vr is None or vr < VOL_CONFIRM:
        return []
    notes = f"BB lower rejection + bull candle above 9EMA {_fmt_num(ema9[-1])}"
    raw = {
        "bb_upper": upper,
        "bb_lower": lower,
        "bb_mid": mid,
        "bb_width": width,
        "ema9": float(ema9[-1]),
        "vol_ratio": vr,
        "exits": _mk_exits(
            stop_hard=stop,
            stop_thesis="Book: stop below bullish candle low.",
            stop_condition=f"close below ₹{_fmt_num(stop)}",
            target_hard=target,
            target_thesis="Book: 1:2 R/R minimum.",
            target_condition=f"close ≥ ₹{_fmt_num(target)}",
            offset_thesis="Book: exit on close back below 9 EMA.",
            offset_trigger="close below 9 EMA",
            invalidation_thesis="Book: close below lower BB voids setup.",
            invalidation_condition="close < bb_lower",
            time_exit_sessions=5,
            time_exit_thesis="Standard swing window.",
        ),
        "overlap_note": "BB family — no existing detector.",
    }
    return [_signal(sym, "bb_9ema_swing", entry, stop, target, "MED", notes, raw)]


def _detect_williams_macd_sma(sym, df):
    closes = df["close"].values.astype(float)
    highs = df["high"].values.astype(float)
    lows = df["low"].values.astype(float)
    if len(closes) < 30:
        return []
    dma14 = _sma(closes, 14)
    if dma14 is None or closes[-1] <= dma14:
        return []
    wr_now = _williams_r(highs, lows, closes, WR_PERIOD)
    wr_prior = _williams_r(highs[:-1], lows[:-1], closes[:-1], WR_PERIOD)
    if wr_now is None or wr_prior is None:
        return []
    if not (wr_now <= WR_PULLBACK and wr_prior >= WR_OVERBOUGHT):
        return []
    macd_line, macd_sig = _macd(closes)
    if macd_line is None:
        return []
    macd_bull = macd_line[-1] > macd_sig[-1] and macd_line[-2] <= macd_sig[-2]
    vr = _vol_ratio(df)
    if not (macd_bull or (vr and vr >= VOL_CONFIRM)):
        return []
    cur = _candle_shape(df, len(df) - 1)
    if cur is None or not cur["is_bull"]:
        return []
    entry = closes[-1]
    stop = cur["low"]
    target = entry + 2.0 * (entry - stop)
    notes = f"Williams %R {_fmt_num(wr_now, 1)} (pulled to -50) + price above 14 SMA"
    raw = {
        "williams_r_now": wr_now,
        "williams_r_prior": wr_prior,
        "dma14": dma14,
        "macd_bull_cross": macd_bull,
        "vol_ratio": vr,
        "exits": _mk_exits(
            stop_hard=stop,
            stop_thesis="Book: stop below setup candle low.",
            stop_condition=f"close below ₹{_fmt_num(stop)}",
            target_hard=target,
            target_thesis="1:2 R/R.",
            target_condition=f"close ≥ ₹{_fmt_num(target)}",
            offset_thesis="Book: exit on Williams %R re-entering overbought.",
            offset_trigger="Williams %R ≥ -20",
            invalidation_thesis="Close below 14 SMA.",
            invalidation_condition="close < dma14",
            time_exit_sessions=3,
            time_exit_thesis="Standard.",
        ),
    }
    return [_signal(sym, "williams_macd_sma_swing", entry, stop, target, "MED", notes, raw)]


def _detect_macd_fib(sym, df):
    closes = df["close"].values.astype(float)
    highs = df["high"].values.astype(float)
    lows = df["low"].values.astype(float)
    if len(closes) < 80:
        return []
    dma50 = _sma(closes, 50)
    if dma50 is None or closes[-1] <= dma50:
        return []
    # Find recent swing high/low for Fib
    win = 60
    sh_idx = int(np.argmax(highs[-win:])) + (len(highs) - win)
    sl_idx = int(np.argmin(lows[-win:])) + (len(lows) - win)
    if sh_idx >= len(closes) - 3:
        return []
    swing_high = float(highs[sh_idx])
    swing_low = float(lows[sl_idx])
    if swing_high <= swing_low:
        return []
    fib = _fib_levels(swing_high, swing_low)
    level = _at_fib(closes[-1], fib)
    if level is None:
        return []
    macd_line, macd_sig = _macd(closes)
    if macd_line is None:
        return []
    macd_bull = macd_line[-1] > macd_sig[-1]
    cur = _candle_shape(df, len(df) - 1)
    if cur is None:
        return []
    if not (macd_bull or cur["is_bull"]):
        return []
    entry = closes[-1]
    stop = cur["low"]
    target = entry + 2.0 * (entry - stop)
    notes = f"MACD + Fib {level * 100:.1f}% retracement ₹{_fmt_num(fib[level])}"
    raw = {
        "fib_level": level,
        "fib_levels": fib,
        "swing_high": swing_high,
        "swing_low": swing_low,
        "macd_bull": macd_bull,
        "exits": _mk_exits(
            stop_hard=stop,
            stop_thesis="Book: stop below setup candle.",
            stop_condition=f"close below ₹{_fmt_num(stop)}",
            target_hard=target,
            target_thesis="1:2 R/R.",
            target_condition=f"close ≥ ₹{_fmt_num(target)}",
            offset_thesis="Book: exit if MACD flips bearish.",
            offset_trigger="MACD bearish cross",
            invalidation_thesis="Close below 61.8% Fib.",
            invalidation_condition=f"close < {_fmt_num(fib.get(0.618))}",
            time_exit_sessions=3,
            time_exit_thesis="Standard.",
        ),
    }
    return [_signal(sym, "macd_fib_swing", entry, stop, target, "MED", notes, raw)]


def _detect_triangle_breakout(sym, df):
    """Use pattern detector already available as pat_tri.
    But per R42 no proxies — implement triangle directly via pivots."""
    closes = df["close"].values.astype(float)
    highs = df["high"].values.astype(float)
    lows = df["low"].values.astype(float)
    if len(closes) < 80:
        return []
    dma50 = _sma(closes, 50)
    if dma50 is None or closes[-1] <= dma50:
        return []
    piv_h = _pivots(highs, k=3, lookback=50, kind="high")
    piv_l = _pivots(lows, k=3, lookback=50, kind="low")
    if len(piv_h) < 2 or len(piv_l) < 2:
        return []
    # Flat resistance: last two pivot highs within 3%
    h1, h2 = piv_h[-2][1], piv_h[-1][1]
    if h1 <= 0:
        return []
    if abs(h2 - h1) / h1 > 0.03:
        return []
    resistance = (h1 + h2) / 2.0
    # Rising lows: last two pivot lows rising
    l1, l2 = piv_l[-2][1], piv_l[-1][1]
    if l2 <= l1:
        return []
    # Consolidation range <= 15%
    rng, _ = _consolidation(df, 20)
    if rng is None or rng > 0.15:
        return []
    vr = _vol_ratio(df)
    if closes[-1] <= resistance + TICK:
        return []
    if vr is None or vr < VOL_BREAKOUT:
        return []
    entry = closes[-1]
    stop = l2 * 0.99
    target = entry + 2.0 * (entry - stop)
    notes = f"Triangle breakout above ₹{_fmt_num(resistance)}, vol {_fmt_num(vr, 2)}x"
    raw = {
        "resistance": resistance,
        "rising_lows": [l1, l2],
        "vol_ratio": vr,
        "consolidation_range_pct": rng,
        "exits": _mk_exits(
            stop_hard=stop,
            stop_thesis="Book: stop below triangle low.",
            stop_condition=f"close below ₹{_fmt_num(stop)}",
            target_hard=target,
            target_thesis="1:2 R/R.",
            target_condition=f"close ≥ ₹{_fmt_num(target)}",
            offset_thesis="Book: exit if price re-enters triangle.",
            offset_trigger="close below resistance",
            invalidation_thesis="Close below lower trendline.",
            invalidation_condition=f"close < {_fmt_num(l2)}",
            time_exit_sessions=5,
            time_exit_thesis="Standard.",
        ),
        "overlap_note": "Overlaps patterns.ASCENDING_TRIANGLE (which is a similar pattern). Marked, not pruned.",
    }
    return [
        _signal(
            sym,
            "triangle_breakout_swing",
            entry,
            stop,
            target,
            "HIGH",
            notes,
            raw,
            overlaps_with=["patterns.ASCENDING_TRIANGLE"],
        )
    ]


def _detect_institutional_gap(sym, df):
    closes = df["close"].values.astype(float)
    opens = df["open"].values.astype(float)
    highs = df["high"].values.astype(float)
    lows = df["low"].values.astype(float)
    if len(closes) < 60:
        return []
    dma50 = _sma(closes, 50)
    if dma50 is None or closes[-1] <= dma50:
        return []
    # Find a recent gap up in last 20 bars
    gap_found = None
    for i in range(len(df) - 20, len(df) - 2):
        if i < 1:
            continue
        prior_high = float(highs[i - 1])
        today_low = float(lows[i])
        if prior_high <= 0:
            continue
        if today_low > prior_high * 1.005:  # at least 0.5% gap
            gap_found = {
                "idx": i,
                "gap_top": today_low,
                "gap_bottom": prior_high,
                "gap_pct": (opens[i] / closes[i - 1] - 1),
            }
            break
    if gap_found is None:
        return []
    # First retracement to gap zone
    for j in range(gap_found["idx"] + 1, len(df)):
        if lows[j] <= gap_found["gap_top"]:
            # Count how many retracements
            retracements = sum(1 for k in range(gap_found["idx"] + 1, j + 1) if lows[k] <= gap_found["gap_top"])
            if retracements > 1:
                return []
            # Confirmation: bullish reversal candle
            cur = _candle_shape(df, len(df) - 1)
            if cur is None or not cur["is_bull"]:
                return []
            vr = _vol_ratio(df)
            entry = closes[-1]
            stop = gap_found["gap_bottom"] * 0.99
            target = entry + 2.0 * (entry - stop)
            notes = (
                f"Institutional gap retracement to "
                f"₹{_fmt_num(gap_found['gap_bottom'])}-"
                f"₹{_fmt_num(gap_found['gap_top'])}"
            )
            raw = {
                "gap_bottom": gap_found["gap_bottom"],
                "gap_top": gap_found["gap_top"],
                "gap_pct": gap_found["gap_pct"],
                "retracements": retracements,
                "vol_ratio": vr,
                "exits": _mk_exits(
                    stop_hard=stop,
                    stop_thesis="Book: stop below gap zone.",
                    stop_condition=f"close below ₹{_fmt_num(stop)}",
                    target_hard=target,
                    target_thesis="1:2 R/R.",
                    target_condition=f"close ≥ ₹{_fmt_num(target)}",
                    offset_thesis="Book: exit on second/third retracement.",
                    offset_trigger="second retracement of gap zone",
                    invalidation_thesis="Close below gap bottom.",
                    invalidation_condition="close < gap_bottom",
                    time_exit_sessions=10,
                    time_exit_thesis="Standard.",
                ),
                "overlap_note": "Overlaps McAllen island bottom / Nison rising window. Marked, not pruned.",
            }
            return [
                _signal(
                    sym,
                    "institutional_gap_retracement",
                    entry,
                    stop,
                    target,
                    "MED",
                    notes,
                    raw,
                    overlaps_with=["mcallen.mcallen_island_bottom_long", "nison.nison_rising_window_support"],
                )
            ]
    return []


def _detect_bb_width_breakout(sym, df):
    closes = df["close"].values.astype(float)
    if len(closes) < BB_PERIOD + 30:
        return []
    upper, lower, _mid, width_now = _bollinger(closes)
    if upper is None:
        return []
    widths = _bb_width_series(closes, n=25)
    if len(widths) < 20:
        return []
    # Squeeze: width flat for at least 5 bars before today
    recent_widths = widths[-6:-1]
    avg_w = float(np.mean(recent_widths)) if recent_widths else None
    if avg_w is None:
        return []
    squeezed = all(w <= avg_w * 1.10 for w in recent_widths)
    if not squeezed:
        return []
    expanded = width_now > avg_w * 1.15
    if not expanded:
        return []
    if closes[-1] <= upper + TICK:
        return []
    rng, _ = _consolidation(df, 20)
    if rng is None or rng > 0.10:
        return []
    entry = closes[-1]
    stop = lower
    target = entry + 2.0 * (entry - stop)
    notes = f"BB width squeeze → expansion, breakout above ₹{_fmt_num(upper)}"
    raw = {
        "bb_upper": upper,
        "bb_lower": lower,
        "bb_width": width_now,
        "avg_width_before": avg_w,
        "exits": _mk_exits(
            stop_hard=stop,
            stop_thesis="Book: stop at lower BB.",
            stop_condition=f"close below ₹{_fmt_num(stop)}",
            target_hard=target,
            target_thesis="1:2 R/R.",
            target_condition=f"close ≥ ₹{_fmt_num(target)}",
            offset_thesis="Book: exit if width contracts again.",
            offset_trigger="BB width drops back",
            invalidation_thesis="Close back inside bands.",
            invalidation_condition="close < bb_upper",
            time_exit_sessions=5,
            time_exit_thesis="Standard.",
        ),
    }
    return [_signal(sym, "bb_width_breakout", entry, stop, target, "HIGH", notes, raw)]


def _detect_ichimoku(sym, df):
    closes = df["close"].values.astype(float)
    highs = df["high"].values.astype(float)
    lows = df["low"].values.astype(float)
    ich = _ichimoku(highs, lows, closes)
    if ich is None:
        return []
    if ich["tenkan"] <= ich["kijun"]:
        return []
    if closes[-1] <= ich["cloud_top"]:
        return []
    vr = _vol_ratio(df)
    entry = closes[-1]
    stop = ich["cloud_bottom"]
    target = entry + 2.0 * (entry - stop)
    notes = (
        f"Ichimoku: tenkan {_fmt_num(ich['tenkan'])} > "
        f"kijun {_fmt_num(ich['kijun'])}, close above cloud "
        f"₹{_fmt_num(ich['cloud_top'])}"
    )
    raw = {
        "ichimoku": ich,
        "vol_ratio": vr,
        "exits": _mk_exits(
            stop_hard=stop,
            stop_thesis="Book: stop at cloud bottom.",
            stop_condition=f"close below ₹{_fmt_num(stop)}",
            target_hard=target,
            target_thesis="1:2 R/R.",
            target_condition=f"close ≥ ₹{_fmt_num(target)}",
            offset_thesis="Book: exit on tenkan/kijun bearish cross.",
            offset_trigger="tenkan crosses below kijun",
            invalidation_thesis="Close back inside cloud.",
            invalidation_condition="close < cloud_top",
            time_exit_sessions=5,
            time_exit_thesis="Standard.",
        ),
    }
    return [_signal(sym, "ichimoku_cloud_swing", entry, stop, target, "HIGH", notes, raw)]


# ============================================================
# Ch 4 — Positional methods (4)
# ============================================================
def _detect_macro_trend_pivot(sym, df):
    closes = df["close"].values.astype(float)
    highs = df["high"].values.astype(float)
    lows = df["low"].values.astype(float)
    if len(closes) < 30:
        return []
    # Uptrend context: last 3 pivot highs rising
    piv_h = _pivots(highs, k=3, lookback=90, kind="high")
    if len(piv_h) < 3:
        return []
    hs = [p[1] for p in piv_h[-3:]]
    if not (hs[0] < hs[1] < hs[2]):
        return []
    # Daily pivot from yesterday's bar
    pivots = _pivot_points(highs[-2], lows[-2], closes[-2])
    if pivots is None:
        return []
    cur_close = closes[-1]
    cur = _candle_shape(df, len(df) - 1)
    if cur is None or not cur["is_bull"]:
        return []
    # Price near a support pivot
    for key in ("P", "S1", "S2"):
        lvl = pivots[key]
        if lvl <= 0:
            continue
        if abs(cur_close - lvl) / lvl <= PIVOT_TOLERANCE:
            entry = cur_close
            stop = cur["low"]
            target = entry + 2.0 * (entry - stop)
            notes = f"Price at {key} pivot {_fmt_num(lvl)} in uptrend"
            raw = {
                "pivot_level_used": key,
                "pivot_value": lvl,
                "all_pivots": pivots,
                "exits": _mk_exits(
                    stop_hard=stop,
                    stop_thesis="Book: stop below bullish candle.",
                    stop_condition=f"close below ₹{_fmt_num(stop)}",
                    target_hard=target,
                    target_thesis="1:2 R/R.",
                    target_condition=f"close ≥ ₹{_fmt_num(target)}",
                    offset_thesis="Book: exit on close below support.",
                    offset_trigger="close below pivot support",
                    invalidation_thesis="Trend structure breaks.",
                    invalidation_condition="close < previous swing low",
                    time_exit_sessions=5,
                    time_exit_thesis="Standard.",
                ),
            }
            return [_signal(sym, "macro_trend_pivot", entry, stop, target, "MED", notes, raw)]
    return []


def _detect_supertrend_rsi(sym, df):
    closes = df["close"].values.astype(float)
    if len(closes) < 40:
        return []
    st_line, st_dir = _supertrend(df, ST_PERIOD, ST_MULT)
    if st_line is None or st_dir != 1:
        return []
    rsi = _rsi(closes, 14)
    if rsi is None or rsi < 60:
        return []
    if closes[-1] <= st_line:
        return []
    entry = closes[-1]
    stop = st_line
    target = entry + 2.0 * (entry - stop)
    notes = f"Supertrend bullish (₹{_fmt_num(st_line)}) + RSI {_fmt_num(rsi, 1)}"
    raw = {
        "supertrend": st_line,
        "supertrend_dir": st_dir,
        "rsi": rsi,
        "exits": _mk_exits(
            stop_hard=stop,
            stop_thesis="Book: stop at Supertrend.",
            stop_condition=f"close below ₹{_fmt_num(stop)}",
            target_hard=target,
            target_thesis="1:2 R/R.",
            target_condition=f"close ≥ ₹{_fmt_num(target)}",
            offset_thesis="Book: exit when Supertrend flips.",
            offset_trigger="Supertrend flip to bearish",
            invalidation_thesis="RSI re-enters 40-60 range.",
            invalidation_condition="RSI between 40 and 60",
            time_exit_sessions=10,
            time_exit_thesis="Positional window.",
        ),
        "overlap_note": "Overlaps chande 65sma-3cc / nison golden cross (trend-following family). Marked, not pruned.",
    }
    return [
        _signal(
            sym,
            "supertrend_rsi_positional",
            entry,
            stop,
            target,
            "HIGH",
            notes,
            raw,
            overlaps_with=["chande.chande_65sma_3cc", "nison.nison_golden_cross"],
        )
    ]


def _detect_sector_rs(sym, df, sector_rs):
    """Uses the system's canonical sector RS (sector_gate)."""
    if sector_rs is None or sector_rs < 0.7:
        return []
    closes = df["close"].values.astype(float)
    if len(closes) < 30:
        return []
    dma20 = _sma(closes, 20)
    if dma20 is None or closes[-1] <= dma20:
        return []
    entry = closes[-1]
    stop = _default_stop(entry, df)
    target = entry + 2.0 * (entry - stop)
    notes = f"Sector RS {_fmt_num(sector_rs * 100, 0)} (top quartile) + price above DMA20"
    raw = {
        "sector_rs": sector_rs,
        "dma20": dma20,
        "exits": _mk_exits(
            stop_hard=stop,
            stop_thesis="2× ATR stop.",
            stop_condition=f"close below ₹{_fmt_num(stop)}",
            target_hard=target,
            target_thesis="1:2 R/R.",
            target_condition=f"close ≥ ₹{_fmt_num(target)}",
            offset_thesis="Book: exit when sector RS falls out of top.",
            offset_trigger="sector RS < 0.5",
            invalidation_thesis="Close below DMA20.",
            invalidation_condition="close < dma20",
            time_exit_sessions=20,
            time_exit_thesis="Positional window.",
        ),
    }
    return [_signal(sym, "sector_rs_positional", entry, stop, target, "MED", notes, raw)]


def _rsi(closes, period=14):
    if len(closes) < period + 1:
        return None
    gains = 0.0
    losses = 0.0
    for i in range(len(closes) - period, len(closes)):
        ch = closes[i] - closes[i - 1]
        if ch > 0:
            gains += ch
        else:
            losses -= ch
    if losses == 0:
        return 100.0
    return 100 - 100 / (1 + gains / losses)


def _rsi_series(closes, period=14):
    n = len(closes)
    if n < period + 1:
        return None
    out = [None] * n
    gains = losses = 0.0
    for i in range(1, period + 1):
        ch = closes[i] - closes[i - 1]
        if ch > 0:
            gains += ch
        else:
            losses -= ch
    ag, al = gains / period, losses / period
    out[period] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    for i in range(period + 1, n):
        ch = closes[i] - closes[i - 1]
        g = ch if ch > 0 else 0.0
        l = -ch if ch < 0 else 0.0
        ag = (ag * (period - 1) + g) / period
        al = (al * (period - 1) + l) / period
        out[i] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    return out


def _detect_mw_rsi(sym, df):
    closes = df["close"].values.astype(float)
    rsi = _rsi_series(closes, 14)
    if rsi is None or len(rsi) < 40:
        return []
    # Find a W shape: two RSI troughs at oversold, second higher
    rsi_vals = [v for v in rsi if v is not None]
    if len(rsi_vals) < 30:
        return []
    recent = rsi_vals[-30:]
    # Find two local minima below 35
    troughs = []
    for i in range(3, len(recent) - 3):
        if recent[i] < 35 and recent[i] == min(recent[i - 3 : i + 4]):
            troughs.append((i, recent[i]))
    if len(troughs) < 2:
        return []
    (_i1, v1), (_i2, v2) = troughs[-2], troughs[-1]
    # Second trough must be higher
    if v2 <= v1:
        return []
    # Confirmation: RSI back above 30
    if rsi[-1] is None or rsi[-1] <= 30:
        return []
    entry = closes[-1]
    stop = _default_stop(entry, df)
    target = entry + 2.0 * (entry - stop)
    notes = f"RSI W at oversold: trough1 {_fmt_num(v1, 1)} → trough2 {_fmt_num(v2, 1)}"
    raw = {
        "rsi": rsi[-1],
        "trough1": v1,
        "trough2": v2,
        "exits": _mk_exits(
            stop_hard=stop,
            stop_thesis="2× ATR stop.",
            stop_condition=f"close below ₹{_fmt_num(stop)}",
            target_hard=target,
            target_thesis="1:2 R/R.",
            target_condition=f"close ≥ ₹{_fmt_num(target)}",
            offset_thesis="Book: exit if RSI makes new extreme.",
            offset_trigger="RSI makes new low",
            invalidation_thesis="W structure broken.",
            invalidation_condition="RSI trough undercut",
            time_exit_sessions=10,
            time_exit_thesis="Positional window.",
        ),
    }
    return [_signal(sym, "mw_rsi_positional", entry, stop, target, "MED", notes, raw)]


# ============================================================
# Ch 7 — More methods (7)
# ============================================================
def _detect_ema9_21(sym, df):
    closes = df["close"].values.astype(float)
    if len(closes) < 30:
        return []
    ema9 = _ema(closes, 9)
    ema21 = _ema(closes, 21)
    # Fresh cross
    if not (ema9[-2] <= ema21[-2] and ema9[-1] > ema21[-1]):
        return []
    # Consolidation + breakout
    rng, _ = _consolidation(df, 10)
    if rng is None:
        return []
    highs = df["high"].values.astype(float)
    resistance = float(np.max(highs[-11:-1]))
    if closes[-1] <= resistance + TICK:
        return []
    entry = closes[-1]
    stop = _default_stop(entry, df)
    target = entry + 2.0 * (entry - stop)
    notes = f"Fresh 9>21 EMA cross + breakout above ₹{_fmt_num(resistance)}"
    raw = {
        "ema9": float(ema9[-1]),
        "ema21": float(ema21[-1]),
        "resistance": resistance,
        "exits": _mk_exits(
            stop_hard=stop,
            stop_thesis="2× ATR stop.",
            stop_condition=f"close below ₹{_fmt_num(stop)}",
            target_hard=target,
            target_thesis="1:2 R/R.",
            target_condition=f"close ≥ ₹{_fmt_num(target)}",
            offset_thesis="Book: exit on EMA bearish cross.",
            offset_trigger="9 EMA crosses below 21 EMA",
            invalidation_thesis="EMAs cross back.",
            invalidation_condition="9 EMA < 21 EMA",
            time_exit_sessions=5,
            time_exit_thesis="Standard.",
        ),
    }
    return [_signal(sym, "ema9_21_support", entry, stop, target, "HIGH", notes, raw)]


def _detect_positional_breakout_volume(sym, df):
    closes = df["close"].values.astype(float)
    highs = df["high"].values.astype(float)
    if len(closes) < 80:
        return []
    mom60 = closes[-1] / closes[-61] - 1 if len(closes) >= 61 else None
    if mom60 is None or mom60 < 0.15:
        return []
    rng, _ = _consolidation(df, 20)
    if rng is None or rng > 0.15:
        return []
    # Volume dry-up during consolidation
    v = df["volume"].values.astype(float)
    avg20 = _sma(v, 20)
    if avg20 is None or avg20 <= 0:
        return []
    cons_avg = float(np.mean(v[-21:-1]))
    if cons_avg / avg20 > 0.70:
        return []
    range_high = float(np.max(highs[-21:-1]))
    if closes[-1] <= range_high + TICK:
        return []
    vr = _vol_ratio(df)
    if vr is None or vr < VOL_STRONG:
        return []
    entry = closes[-1]
    stop = _default_stop(entry, df)
    target = entry + 2.0 * (entry - stop)
    notes = (
        f"Positional BO: +{_fmt_num(mom60 * 100, 0)}% 60d, "
        f"consolidation {_fmt_num(rng * 100, 1)}%, "
        f"vol {_fmt_num(vr, 2)}x"
    )
    raw = {
        "mom_60d": mom60,
        "consolidation_range_pct": rng,
        "vol_ratio": vr,
        "range_high": range_high,
        "exits": _mk_exits(
            stop_hard=stop,
            stop_thesis="2× ATR stop.",
            stop_condition=f"close below ₹{_fmt_num(stop)}",
            target_hard=target,
            target_thesis="1:2 R/R.",
            target_condition=f"close ≥ ₹{_fmt_num(target)}",
            offset_thesis="Book: exit on close below consolidation range.",
            offset_trigger="close below range low",
            invalidation_thesis="Close below range.",
            invalidation_condition="close < range_high",
            time_exit_sessions=10,
            time_exit_thesis="Positional window.",
        ),
        "overlap_note": "Overlaps O'Neil flat base / Chande CB-PB. Marked, not pruned.",
    }
    return [
        _signal(
            sym,
            "positional_breakout_volume",
            entry,
            stop,
            target,
            "HIGH",
            notes,
            raw,
            overlaps_with=["oneil.oneil_flat_base", "chande.chande_cb_pb_long"],
        )
    ]


def _detect_pin_bar(sym, df):
    if len(df) < 40:
        return []
    cur = _candle_shape(df, len(df) - 1)
    kind = _is_pin_bar(cur)
    if kind != "bull":
        return []
    # Context: near a range bottom (recent low)
    lows = df["low"].values.astype(float)
    recent_low = float(np.min(lows[-20:]))
    if cur["low"] > recent_low * 1.02:
        return []
    entry = cur["close"]
    stop = cur["low"]
    target = entry + 2.0 * (entry - stop)
    notes = f"Bullish pin bar at range low ₹{_fmt_num(recent_low)}"
    raw = {
        "pin_bar_low": cur["low"],
        "pin_bar_high": cur["high"],
        "range_low": recent_low,
        "exits": _mk_exits(
            stop_hard=stop,
            stop_thesis="Book: stop at pin bar low.",
            stop_condition=f"close below ₹{_fmt_num(stop)}",
            target_hard=target,
            target_thesis="1:2 R/R.",
            target_condition=f"close ≥ ₹{_fmt_num(target)}",
            offset_thesis="Book: exit if range breaks down.",
            offset_trigger="close below range low",
            invalidation_thesis="Range breaks.",
            invalidation_condition="close < range_low",
            time_exit_sessions=5,
            time_exit_thesis="Standard.",
        ),
        "overlap_note": "Overlaps mcallen three-white / nison hammer. Marked, not pruned.",
    }
    return [
        _signal(
            sym,
            "pin_bar_reversal",
            entry,
            stop,
            target,
            "MED",
            notes,
            raw,
            overlaps_with=["nison.nison_candlestick_reversal_at_support"],
        )
    ]


def _detect_pullback_retest(sym, df):
    closes = df["close"].values.astype(float)
    highs = df["high"].values.astype(float)
    lows = df["low"].values.astype(float)
    if len(closes) < 60:
        return []
    # Find a recent resistance break
    piv_h = _pivots(highs, k=3, lookback=60, kind="high")
    if len(piv_h) < 1:
        return []
    resistance = piv_h[-1][1]
    r_idx = piv_h[-1][0]
    if r_idx >= len(df) - 3:
        return []
    # Was it broken?
    break_idx = None
    for i in range(r_idx + 1, len(df)):
        if closes[i] > resistance + TICK:
            break_idx = i
            break
    if break_idx is None:
        return []
    # Now pullback to resistance zone?
    for j in range(break_idx + 1, len(df)):
        if lows[j] <= resistance * 1.01:
            cur = _candle_shape(df, len(df) - 1)
            if cur is None or not cur["is_bull"]:
                return []
            entry = closes[-1]
            stop = cur["low"]
            target = entry + 2.0 * (entry - stop)
            notes = f"Pullback to broken resistance ₹{_fmt_num(resistance)} + bullish candle"
            raw = {
                "resistance": resistance,
                "break_idx": break_idx,
                "pullback_idx": j,
                "exits": _mk_exits(
                    stop_hard=stop,
                    stop_thesis="Book: stop below pullback candle.",
                    stop_condition=f"close below ₹{_fmt_num(stop)}",
                    target_hard=target,
                    target_thesis="1:2 R/R.",
                    target_condition=f"close ≥ ₹{_fmt_num(target)}",
                    offset_thesis="Book: exit if resistance breaks down.",
                    offset_trigger="close below resistance",
                    invalidation_thesis="Pullback breaks resistance.",
                    invalidation_condition="close < resistance",
                    time_exit_sessions=5,
                    time_exit_thesis="Standard.",
                ),
                "overlap_note": "Overlaps Ishaan trend_pullback. Marked, not pruned.",
            }
            return [
                _signal(
                    sym,
                    "pullback_retest",
                    entry,
                    stop,
                    target,
                    "HIGH",
                    notes,
                    raw,
                    overlaps_with=["ishaan_agnihotri.trend_pullback_playbook"],
                )
            ]
    return []


def _detect_repo_rate(sym, df):
    """R42: silent until DR-23 (RBI repo rate) supplied."""
    if REPO_RATE_CURRENT is None or REPO_RATE_PRIOR is None:
        return []
    if REPO_RATE_CURRENT >= REPO_RATE_PRIOR:
        return []
    # Rate cut → buy signal
    closes = df["close"].values.astype(float)
    if len(closes) < 30:
        return []
    entry = closes[-1]
    stop = _default_stop(entry, df)
    target = entry + 2.0 * (entry - stop)
    notes = f"RBI repo cut: {_fmt_num(REPO_RATE_PRIOR, 2)}% → {_fmt_num(REPO_RATE_CURRENT, 2)}%"
    raw = {
        "repo_prior": REPO_RATE_PRIOR,
        "repo_current": REPO_RATE_CURRENT,
        "exits": _mk_exits(
            stop_hard=stop,
            stop_thesis="2× ATR stop.",
            stop_condition=f"close below ₹{_fmt_num(stop)}",
            target_hard=target,
            target_thesis="1:2 R/R.",
            target_condition=f"close ≥ ₹{_fmt_num(target)}",
            offset_thesis="Book: sell on rate hike.",
            offset_trigger="RBI hikes repo rate",
            invalidation_thesis="Rate hike reverses thesis.",
            invalidation_condition="repo rate hiked",
            time_exit_sessions=20,
            time_exit_thesis="Positional window.",
        ),
    }
    return [_signal(sym, "repo_rate_trading", entry, stop, target, "MED", notes, raw)]


def _detect_vcp(sym, df):
    closes = df["close"].values.astype(float)
    highs = df["high"].values.astype(float)
    if len(closes) < 80:
        return []
    vcp = _vcp_pattern(df, min_pullbacks=3)
    if vcp is None:
        return []
    # Uptrend context
    dma50 = _sma(closes, 50)
    if dma50 is None or closes[-1] <= dma50:
        return []
    # Breakout above recent resistance
    rng, _ = _consolidation(df, 20)
    if rng is None or rng > 0.15:
        return []
    range_high = float(np.max(highs[-21:-1]))
    if closes[-1] <= range_high + TICK:
        return []
    vr = _vol_ratio(df)
    if vr is None or vr < VOL_STRONG:
        return []
    entry = closes[-1]
    stop = _default_stop(entry, df)
    target = entry + 2.0 * (entry - stop)
    notes = f"VCP: {vcp['pullback_count']} successively shorter pullbacks, range {_fmt_num(vcp['range_pct'] * 100, 1)}%"
    raw = {
        "vcp": vcp,
        "range_high": range_high,
        "vol_ratio": vr,
        "exits": _mk_exits(
            stop_hard=stop,
            stop_thesis="2× ATR stop.",
            stop_condition=f"close below ₹{_fmt_num(stop)}",
            target_hard=target,
            target_thesis="1:2 R/R.",
            target_condition=f"close ≥ ₹{_fmt_num(target)}",
            offset_thesis="Book: exit on close below 3rd pullback low.",
            offset_trigger="close below last pullback low",
            invalidation_thesis="VCP structure broken.",
            invalidation_condition="close below range low",
            time_exit_sessions=10,
            time_exit_thesis="Positional window.",
        ),
        "overlap_note": "Overlaps O'Neil cup/flat family. Marked, not pruned.",
    }
    return [
        _signal(
            sym, "vcp_breakout", entry, stop, target, "HIGH", notes, raw, overlaps_with=["oneil.oneil_cup_with_handle"]
        )
    ]


def _detect_two_legged_pullback(sym, df):
    tl = _detect_two_leg_pullback(df)
    if tl is None:
        return []
    closes = df["close"].values.astype(float)
    highs = df["high"].values.astype(float)
    cur = _candle_shape(df, len(df) - 1)
    if cur is None or not cur["is_bull"]:
        return []
    # Breakout above the second leg's prior high
    recent_high = float(np.max(highs[-10:-1]))
    if closes[-1] <= recent_high + TICK:
        return []
    entry = closes[-1]
    stop = cur["low"]
    target = entry + 2.0 * (entry - stop)
    notes = f"Two-legged pullback: {len(tl['highs'])} rising highs, {len(tl['lows'])} rising lows"
    raw = {
        "two_leg": tl,
        "recent_high": recent_high,
        "exits": _mk_exits(
            stop_hard=stop,
            stop_thesis="Book: stop below entry candle.",
            stop_condition=f"close below ₹{_fmt_num(stop)}",
            target_hard=target,
            target_thesis="1:2 R/R.",
            target_condition=f"close ≥ ₹{_fmt_num(target)}",
            offset_thesis="Book: exit on trend structure break.",
            offset_trigger="lower low forms",
            invalidation_thesis="Trend broken.",
            invalidation_condition="close below last higher low",
            time_exit_sessions=5,
            time_exit_thesis="Standard.",
        ),
    }
    return [_signal(sym, "two_legged_pullback", entry, stop, target, "MED", notes, raw)]


# ----------------------------------------------------------------
# Per-symbol scan
# ----------------------------------------------------------------
def _scan_symbol(sym, df, sector_rs):
    sigs = []
    _try_emit(sigs, lambda: _detect_bb_9ema(sym, df))
    _try_emit(sigs, lambda: _detect_williams_macd_sma(sym, df))
    _try_emit(sigs, lambda: _detect_macd_fib(sym, df))
    _try_emit(sigs, lambda: _detect_triangle_breakout(sym, df))
    _try_emit(sigs, lambda: _detect_institutional_gap(sym, df))
    _try_emit(sigs, lambda: _detect_bb_width_breakout(sym, df))
    _try_emit(sigs, lambda: _detect_ichimoku(sym, df))
    _try_emit(sigs, lambda: _detect_macro_trend_pivot(sym, df))
    _try_emit(sigs, lambda: _detect_supertrend_rsi(sym, df))
    _try_emit(sigs, lambda: _detect_sector_rs(sym, df, sector_rs))
    _try_emit(sigs, lambda: _detect_mw_rsi(sym, df))
    _try_emit(sigs, lambda: _detect_ema9_21(sym, df))
    _try_emit(sigs, lambda: _detect_positional_breakout_volume(sym, df))
    _try_emit(sigs, lambda: _detect_pin_bar(sym, df))
    _try_emit(sigs, lambda: _detect_pullback_retest(sym, df))
    _try_emit(sigs, lambda: _detect_repo_rate(sym, df))
    _try_emit(sigs, lambda: _detect_vcp(sym, df))
    _try_emit(sigs, lambda: _detect_two_legged_pullback(sym, df))
    return sigs


# ----------------------------------------------------------------
# Sector RS map (canonical, from top_picks pattern)
# ----------------------------------------------------------------
def _sector_rs_map(conn):
    try:
        import sector_gate

        g = sector_gate.sector_perf(conn)
        if g is None or g.empty:
            return {}
        n = len(g)
        rank = {}
        for i, (_, row) in enumerate(g.iterrows()):
            rank[row["sector"]] = 1.0 - (i / max(1, n - 1))
        out = {}
        for sym, sec in conn.execute("SELECT symbol, sector FROM stocks WHERE sector IS NOT NULL AND sector!=''"):
            out[sym] = rank.get(sec, 0.5)
        return out
    except Exception as e:
        log.warning(f"sector RS skipped: {e}")
        return {}


# ----------------------------------------------------------------
# Universe scan
# ----------------------------------------------------------------
def scan(conn=None, limit=DEFAULT_LIMIT):
    own = conn is None
    if own:
        conn = db.get_conn()
    syms = band_universe(conn, limit=limit)
    log.info(f"Singhal scan: {len(syms)} symbols in universe")

    sector_rs = _sector_rs_map(conn)

    # Data-coverage note
    if REPO_RATE_CURRENT is None:
        log.info(
            "Singhal data gap: repo_rate (DR-23) — Method 49 (repo_rate_trading) will emit 0 signals until supplied"
        )

    signals = []
    n_loaded = 0
    n_short = 0
    n_low = 0
    for i, sym in enumerate(syms, 1):
        df = _load_df(conn, sym)
        if df is None:
            n_short += 1
            continue
        if df["close"].iloc[-1] < MIN_PRICE:
            n_low += 1
            continue
        n_loaded += 1
        try:
            signals.extend(_scan_symbol(sym, df, sector_rs.get(sym)))
        except Exception as e:
            log.warning(f"{sym} scan failed: {e}")
        if i % 100 == 0:
            log.info(f"  progress {i}/{len(syms)}, {len(signals)} signals")

    if own:
        conn.close()

    n_sym = len({s["symbol"] for s in signals})
    log.info(
        f"Singhal scan complete: {n_loaded} loaded, "
        f"short_history={n_short}, price<₹{MIN_PRICE}={n_low}, "
        f"{len(signals)} signals across {n_sym} symbols"
    )
    return signals
