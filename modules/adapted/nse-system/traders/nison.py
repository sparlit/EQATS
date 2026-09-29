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
Steve Nison — Beyond Candlesticks (1994).
Classified: MULTI (Swing + Positional, long-only extraction).

6 methods extracted per docs/BOOK_EXTRACTION_PROMPT.md.
All methods price-only. No data blocks. Fully implementable today.

Exit strategy — per owner's explicit instruction, R30's
"setup-identification only" rule is overridden for this trader.
Every signal carries a structured `raw.exits` block:
    stop_out      — price + textual condition
    target        — price + textual condition
    offset        — opposite-pattern exit trigger
    invalidation  — setup-death condition
    exhaustion    — 8-10 record-session rule
    time_exit     — None or N-session window

Overlap marking — Nison's candlestick_reversal_at_support carries
`overlaps_with: ["ishaan_agnihotri.candlestick_reversal_at_support"]`
on every signal. Owner decides later whether to prune.

R35 safety: _fmt_num + _try_emit from day one.
"""
import db
import numpy as np
import pandas as pd
from log_utils import get_logger
from universe_helper import band_universe

log = get_logger("trader.nison")

SLUG = "nison"
NAME = "Steve Nison"
PILLAR = "multi"
SOURCE = "Beyond Candlesticks (1994)"


# ----------------------------------------------------------------
# Tunables — book-cited defaults, India adaptations noted
# ----------------------------------------------------------------
TICK = 0.05
MIN_PRICE = 100
MIN_BARS = 260  # room for SMA200 + TLB state
DEFAULT_LIMIT = 800

VOL_CONFIRM = 1.5
VOL_MIN = 1.2

SMA_TREND = 20  # "prior downtrend" filter
SMA_MID = 50
SMA_LONG = 200
EMA_FAST = 13
EMA_SLOW = 26

PIVOT_K = 3
PIVOT_LOOKBACK = 120
TOUCH_TOL = 0.03  # 3% — "at support"

DISPARITY_PERIOD = 13
DISPARITY_OVERSOLD = -10.0
DISPARITY_VERY_OVERSOLD = -15.0

RR_MIN = 2.0  # Method 1 risk/reward filter

LONG_CANDLE_BODY_MULT = 3.0  # Method 3: body >= 3x avg prior 10
WINDOW_LOOKBACK = 20  # Method 2: scan last N bars for a gap up
LONG_CANDLE_LOOKBACK = 15  # Method 3: scan last N bars for the tall candle

TLB_SENSITIVITY = 3  # book default (3-line break)
RENKO_ATR_MULT = 1.0  # brick size = 1x ATR(20) or 3% of price
RENKO_PCT_FLOOR = 0.03  # whichever is larger
KAGI_TURNAROUND_PCT = 0.03  # book's NTAA default


# ----------------------------------------------------------------
# METHODS registry — 6 total, all scanned
# ----------------------------------------------------------------
METHODS = [
    {
        "id": "nison_candlestick_reversal_at_support",
        "name": "Candlestick Reversal at Support",
        "description": "Prior downtrend + validated support + bullish "
        "candle (hammer / morning star / piercing / "
        "engulfing / dragonfly) + R/R >= 2:1. "
        "Overlaps Ishaan #3 (marked).",
        "direction": "long",
        "scan": True,
        "confidence": "HIGH",
    },
    {
        "id": "nison_rising_window_support",
        "name": "Rising Window as Support",
        "description": "Gap up + pullback into window + bullish candle holding the window's bottom.",
        "direction": "long",
        "scan": True,
        "confidence": "HIGH",
    },
    {
        "id": "nison_long_white_candle_support",
        "name": "Long White Candle Support Zone",
        "description": "Tall white candle (body >= 3x avg) + pullback into its upper half + bullish confirmation.",
        "direction": "long",
        "scan": True,
        "confidence": "MED",
    },
    {
        "id": "nison_disparity_index_oversold",
        "name": "Disparity Index Oversold Reversal",
        "description": "13-period disparity <= -10% + bullish candle / doji. Mean reversion trade.",
        "direction": "long",
        "scan": True,
        "confidence": "HIGH",
    },
    {
        "id": "nison_golden_cross",
        "name": "Golden Cross 13/26 EMA",
        "description": "Fresh 13-EMA cross above 26-EMA + price above both. Trend following.",
        "direction": "long",
        "scan": True,
        "confidence": "MED",
    },
    {
        "id": "nison_new_price_chart_trend",
        "name": "New-Price Chart Trend (TLB / Renko / Kagi)",
        "description": "Non-time chart turns bullish: TLB white turnaround / Renko white brick / Kagi yang.",
        "direction": "long",
        "scan": True,
        "confidence": "HIGH",
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
# Data loading + indicators
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


def _sma(arr, period):
    if len(arr) < period:
        return None
    return float(np.mean(arr[-period:]))


def _ema_series(arr, span):
    return pd.Series(arr).ewm(span=span, adjust=False).mean().values


def _atr(df, period=20):
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


# ----------------------------------------------------------------
# Candlestick pattern detectors
# ----------------------------------------------------------------
def _is_hammer(s):
    if s is None:
        return False
    if s["body"] < 1e-6:
        return s["lower"] >= 0.6 * s["rng"] and s["upper"] <= 0.15 * s["rng"] and s["close_pos"] >= 0.6
    return s["lower"] >= 2.0 * s["body"] and s["upper"] <= 0.2 * s["body"] and s["close_pos"] >= 0.6


def _is_dragonfly_doji(s):
    if s is None:
        return False
    return s["body"] <= 0.15 * s["rng"] and s["lower"] >= 0.6 * s["rng"] and s["upper"] <= 0.1 * s["rng"]


def _is_bullish_engulfing(df, i):
    if i < 1:
        return False
    prev = _candle_shape(df, i - 1)
    cur = _candle_shape(df, i)
    if prev is None or cur is None:
        return False
    if prev["is_bull"] or not cur["is_bull"]:
        return False
    return cur["open"] <= prev["close"] and cur["close"] >= prev["open"] and cur["body"] > prev["body"]


def _is_piercing(df, i):
    """Long black candle followed by a white candle that opens at a
    new low and closes above the midpoint of the prior black body."""
    if i < 1:
        return False
    prev = _candle_shape(df, i - 1)
    cur = _candle_shape(df, i)
    if prev is None or cur is None:
        return False
    if prev["is_bull"] or not cur["is_bull"]:
        return False
    prev_mid = (prev["open"] + prev["close"]) / 2.0
    return cur["open"] < prev["low"] and cur["close"] > prev_mid and cur["close"] < prev["open"]


def _is_morning_star(df, i):
    """3-candle: long black, small body, long white closing well into
    the first body. `i` is the third (white) candle index."""
    if i < 2:
        return False
    c1 = _candle_shape(df, i - 2)
    c2 = _candle_shape(df, i - 1)
    c3 = _candle_shape(df, i)
    if c1 is None or c2 is None or c3 is None:
        return False
    # c1: long black
    if c1["is_bull"] or c1["body"] < 0.5 * c1["rng"]:
        return False
    # c2: small body (star) — small relative to c1's body
    if c2["body"] > 0.4 * c1["body"]:
        return False
    # c3: long white, closes well into c1's body (above midpoint)
    if not c3["is_bull"]:
        return False
    c1_mid = (c1["open"] + c1["close"]) / 2.0
    return c3["close"] > c1_mid


def _any_bullish_reversal(df, i):
    """Return (name, shape) if a bullish reversal candle is present."""
    shape = _candle_shape(df, i)
    if shape is None:
        return None, None
    if not shape["is_bull"] and not _is_dragonfly_doji(shape):
        # morning star's third candle is bullish so covered below;
        # doji is allowed
        if _is_dragonfly_doji(shape):
            return "dragonfly_doji", shape
        return None, None
    if _is_bullish_engulfing(df, i):
        return "bullish_engulfing", shape
    if _is_morning_star(df, i):
        return "morning_star", shape
    if _is_piercing(df, i):
        return "piercing", shape
    if _is_hammer(shape):
        return "hammer", shape
    if _is_dragonfly_doji(shape):
        return "dragonfly_doji", shape
    return None, None


# ----------------------------------------------------------------
# Level detection
# ----------------------------------------------------------------
def _pivots(values, k=PIVOT_K, lookback=PIVOT_LOOKBACK, kind="low"):
    n = len(values)
    start = max(k, n - lookback)
    out = []
    for i in range(start, n - k):
        win = values[i - k : i + k + 1]
        if (kind == "low" and values[i] == win.min()) or (kind == "high" and values[i] == win.max()):
            out.append((i, float(values[i])))
    return out


def _nearest_support(df, current_low):
    """Return (level, touches) or None."""
    lows = df["low"].values.astype(float)
    piv = _pivots(lows, kind="low")
    if not piv:
        return None
    best = None
    for _i, lv in piv:
        if lv <= 0:
            continue
        if abs(current_low - lv) / lv <= TOUCH_TOL:
            if best is None or lv > best[0]:
                best = (lv, 1)
    if best is None:
        return None
    # Count touches within 3%
    level = best[0]
    touches = sum(1 for _, lv in piv if level > 0 and abs(lv - level) / level <= TOUCH_TOL)
    return level, touches


def _nearest_resistance(df, current_close):
    """Return the nearest pivot-high above current_close, or None."""
    highs = df["high"].values.astype(float)
    piv = _pivots(highs, kind="high")
    candidates = [hv for _, hv in piv if hv > current_close]
    if not candidates:
        return None
    return min(candidates)


def _at_support(df, close, low):
    """Return the support level if we're at one, else None."""
    # Method A: pivot low cluster
    res = _nearest_support(df, low)
    if res is not None:
        return res[0]
    # Method B: near SMA50 or SMA200
    closes = df["close"].values.astype(float)
    for period in (SMA_MID, SMA_LONG):
        ma = _sma(closes, period)
        if ma and ma > 0 and abs(close - ma) / ma <= 0.02:
            return ma
    return None


def _prior_downtrend(df):
    """Book: 'downtrend' before the reversal candle."""
    if len(df) < 10:
        return False
    closes = df["close"].values.astype(float)
    sma20 = _sma(closes, SMA_TREND)
    if sma20 is None:
        return False
    below = sum(1 for i in range(len(closes) - 5, len(closes)) if closes[i] < sma20)
    lower_lows = closes[-1] < closes[-10]
    return below >= 3 or lower_lows


# ----------------------------------------------------------------
# Exit strategy builder (R30 override for Nison)
# ----------------------------------------------------------------
def _mk_exits(
    stop_price, stop_cond, target_price, target_cond, offset_trigger, invalidation, exhaustion=None, time_exit=None
):
    return {
        "stop_out": {
            "price": round(float(stop_price), 2) if stop_price else None,
            "condition": stop_cond,
        },
        "target": {
            "price": round(float(target_price), 2) if target_price else None,
            "condition": target_cond,
        },
        "offset": {"trigger": offset_trigger},
        "invalidation": {"condition": invalidation},
        "exhaustion": exhaustion,
        "time_exit": time_exit,
    }


# ----------------------------------------------------------------
# Signal constructor
# ----------------------------------------------------------------
def _signal(sym, method_id, entry, stop, target, confidence, notes, raw, signal_type="LONG_SETUP", overlaps_with=None):
    sig = {
        "symbol": sym,
        "trader": SLUG,
        "method": method_id,
        "direction": "BULLISH",
        "signal_type": signal_type,
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


# ============================================================
# METHOD 1 — Candlestick Reversal at Support
# ============================================================
def _detect_candlestick_reversal(sym, df):
    if len(df) < 60:
        return []
    if not _prior_downtrend(df):
        return []
    close = float(df["close"].iloc[-1])
    low = float(df["low"].iloc[-1])

    support = _at_support(df, close, low)
    if support is None:
        return []

    name, shape = _any_bullish_reversal(df, len(df) - 1)
    if name is None:
        return []

    entry = close
    stop_price = shape["low"]
    risk = entry - stop_price
    if risk <= 0:
        return []

    resistance = _nearest_resistance(df, close)
    if resistance is None or (resistance - entry) / risk < RR_MIN:
        return []
    reward = resistance - entry

    notes = f"{name} at support ₹{_fmt_num(support)} (R/R {(resistance - entry) / risk:.1f}:1)"
    raw = {
        "candle_type": name,
        "support_level": support,
        "risk": round(risk, 2),
        "reward": round(reward, 2),
        "rr": round((resistance - entry) / risk, 2),
        "exits": _mk_exits(
            stop_price=stop_price,
            stop_cond="close below the reversal candle's low",
            target_price=resistance,
            target_cond="nearest resistance (prior swing high)",
            offset_trigger=("dark cloud cover, evening star, or bearish engulfing at resistance"),
            invalidation="close below the support level",
            time_exit="3 sessions (setup validity window)",
        ),
        "overlap_note": (
            "Same conceptual setup as "
            "ishaan_agnihotri.candlestick_reversal_at_support. "
            "Nison adds R/R >= 2:1 filter and structured "
            "exit rules. Owner decides later whether to prune."
        ),
    }
    return [
        _signal(
            sym,
            "nison_candlestick_reversal_at_support",
            entry,
            stop_price,
            resistance,
            "HIGH",
            notes,
            raw,
            overlaps_with=["ishaan_agnihotri.candlestick_reversal_at_support"],
        )
    ]


# ============================================================
# METHOD 2 — Rising Window as Support
# ============================================================
def _detect_rising_window(sym, df):
    n = len(df)
    if n < WINDOW_LOOKBACK + 5:
        return []
    h = df["high"].values.astype(float)
    l = df["low"].values.astype(float)
    c = df["close"].values.astype(float)
    o = df["open"].values.astype(float)
    v = df["volume"].values.astype(float)

    # Scan recent bars for a gap up (prior high < current low)
    window = None
    for j in range(n - WINDOW_LOOKBACK, n):
        if h[j - 1] < l[j] - 1e-9:
            avg_vol = np.mean(v[max(0, j - 20) : j]) if j >= 20 else np.mean(v[:j])
            if avg_vol > 0 and v[j] / avg_vol >= VOL_MIN:
                window = {"idx": j, "top": l[j], "bottom": h[j - 1]}
                # keep the most recent one
    if window is None:
        return []
    # Was there a pullback AFTER the window?
    pullback_seen = False
    for k in range(window["idx"] + 1, n):
        if l[k] <= window["top"]:
            pullback_seen = True
            break
    if not pullback_seen:
        return []
    # Today: close must hold above window's bottom
    if c[-1] <= window["bottom"]:
        return []
    # Today must be a bullish candle
    if c[-1] <= o[-1]:
        return []

    entry = c[-1]
    stop_price = window["bottom"]
    resistance = _nearest_resistance(df, entry)
    if resistance is None:
        return []
    risk = entry - stop_price
    if risk <= 0:
        return []

    notes = (
        f"Rising window (gap ₹{_fmt_num(window['bottom'])}–"
        f"₹{_fmt_num(window['top'])}) held on pullback, bullish "
        f"confirmation"
    )
    raw = {
        "window_top": window["top"],
        "window_bottom": window["bottom"],
        "window_bar_index": window["idx"],
        "exits": _mk_exits(
            stop_price=stop_price,
            stop_cond="close below the bottom of the rising window",
            target_price=resistance,
            target_cond="prior swing high or next resistance",
            offset_trigger=("failure to hold above the window after multiple tests"),
            invalidation="close below the bottom of the window",
            time_exit="5 sessions (setup validity window)",
        ),
    }
    return [_signal(sym, "nison_rising_window_support", entry, stop_price, resistance, "HIGH", notes, raw)]


# ============================================================
# METHOD 3 — Long White Candle Support Zone
# ============================================================
def _detect_long_white_candle(sym, df):
    n = len(df)
    if n < LONG_CANDLE_LOOKBACK + 15:
        return []
    o = df["open"].values.astype(float)
    h = df["high"].values.astype(float)
    l = df["low"].values.astype(float)
    c = df["close"].values.astype(float)

    # Find the most recent tall white candle in the last N bars
    tall = None
    for j in range(n - LONG_CANDLE_LOOKBACK, n - 1):
        if j < 10:
            continue
        body = abs(c[j] - o[j])
        avg_body = np.mean([abs(c[k] - o[k]) for k in range(j - 10, j)])
        if avg_body <= 0:
            continue
        if c[j] > o[j] and body >= LONG_CANDLE_BODY_MULT * avg_body:
            tall = {"idx": j, "high": h[j], "low": l[j], "mid": (o[j] + c[j]) / 2.0}
    if tall is None:
        return []
    # Current price must have pulled back into the upper half
    if not (tall["mid"] <= c[-1] <= tall["high"]):
        return []
    # Today: bullish candle
    if c[-1] <= o[-1]:
        return []

    entry = c[-1]
    stop_price = tall["low"]
    resistance = _nearest_resistance(df, entry)
    risk = entry - stop_price
    if risk <= 0 or resistance is None:
        return []

    notes = (
        f"Pullback into long white candle's upper half (mid ₹{_fmt_num(tall['mid'])} · high ₹{_fmt_num(tall['high'])})"
    )
    raw = {
        "tall_candle_high": tall["high"],
        "tall_candle_low": tall["low"],
        "tall_candle_mid": tall["mid"],
        "tall_candle_bar_index": tall["idx"],
        "exits": _mk_exits(
            stop_price=stop_price,
            stop_cond=("close below the long white candle's low (including lower shadow)"),
            target_price=resistance,
            target_cond="prior high or next resistance",
            offset_trigger=("tall black candle violates the candle's midpoint on close"),
            invalidation="close below the long white candle's bottom",
            time_exit="10 sessions (setup validity window)",
        ),
    }
    return [_signal(sym, "nison_long_white_candle_support", entry, stop_price, resistance, "MED", notes, raw)]


# ============================================================
# METHOD 4 — Disparity Index Oversold Reversal
# ============================================================
def _detect_disparity_oversold(sym, df):
    if len(df) < DISPARITY_PERIOD + 10:
        return []
    closes = df["close"].values.astype(float)
    ma13 = _sma(closes, DISPARITY_PERIOD)
    if ma13 is None or ma13 <= 0:
        return []
    disp = (closes[-1] - ma13) / ma13 * 100.0
    if disp > DISPARITY_OVERSOLD:
        return []

    name, shape = _any_bullish_reversal(df, len(df) - 1)
    if name is None:
        # allow a plain doji
        s = _candle_shape(df, len(df) - 1)
        if s is not None and s["body"] <= 0.15 * s["rng"]:
            name = "doji"
            shape = s
    if name is None:
        return []

    entry = closes[-1]
    stop_price = shape["low"] if shape else None
    if stop_price is None or stop_price >= entry:
        return []

    notes = f"Disparity {disp:.1f}% (≤ {DISPARITY_OVERSOLD}%) + {name} — mean reversion long"
    raw = {
        "disparity_pct": round(disp, 2),
        "ma13": ma13,
        "candle_type": name,
        "exits": _mk_exits(
            stop_price=stop_price,
            stop_cond="close below the bullish candle's low",
            target_price=ma13,
            target_cond=("disparity returns to 0 (mean reversion to the 13-period MA)"),
            offset_trigger=("disparity index reaches 0 or turns positive (book's overbought signal)"),
            invalidation=("disparity extends below -15% and price makes new lows without a bullish candle"),
            time_exit="5 sessions after disparity first hits extreme",
        ),
    }
    return [
        _signal(
            sym,
            "nison_disparity_index_oversold",
            entry,
            stop_price,
            ma13,
            "HIGH",
            notes,
            raw,
            signal_type="MEAN_REVERSION",
        )
    ]


# ============================================================
# METHOD 5 — Golden Cross 13/26 EMA
# ============================================================
def _detect_golden_cross(sym, df):
    if len(df) < EMA_SLOW + 5:
        return []
    closes = df["close"].values.astype(float)
    ema13 = _ema_series(closes, EMA_FAST)
    ema26 = _ema_series(closes, EMA_SLOW)
    # Fresh cross in the last bar
    if not (ema13[-2] <= ema26[-2] and ema13[-1] > ema26[-1]):
        return []
    if closes[-1] <= ema13[-1] or closes[-1] <= ema26[-1]:
        return []

    entry = closes[-1]
    stop_price = ema26[-1]

    notes = f"Golden cross: 13-EMA {_fmt_num(ema13[-1])} crossed above 26-EMA {_fmt_num(ema26[-1])}"
    raw = {
        "ema13": float(ema13[-1]),
        "ema26": float(ema26[-1]),
        "exits": _mk_exits(
            stop_price=stop_price,
            stop_cond="close below the 26 EMA",
            target_price=None,
            target_cond="trail — no fixed target (trend following)",
            offset_trigger="dead cross (13 EMA crosses back below 26 EMA)",
            invalidation="dead cross or close below both MAs",
            exhaustion="8-10 consecutive higher highs (record session rule)",
            time_exit=None,
        ),
    }
    return [_signal(sym, "nison_golden_cross", entry, stop_price, None, "MED", notes, raw, signal_type="TREND_FOLLOW")]


# ============================================================
# METHOD 6 — New-Price Charts (TLB / Renko / Kagi)
# ============================================================
def _build_tlb(closes, sensitivity=TLB_SENSITIVITY):
    """Return list of lines [{open, close, color}]."""
    lines = []
    if not len(closes):
        return lines
    lines.append({"open": closes[0], "close": closes[0], "color": "w"})
    for c in closes[1:]:
        last = lines[-1]
        if c > last["close"]:
            lines.append({"open": last["close"], "close": c, "color": "w"})
        elif c < last["close"]:
            lines.append({"open": last["close"], "close": c, "color": "b"})
    return lines


def _detect_tlb(sym, df):
    closes = df["close"].values.astype(float)
    if len(closes) < 30:
        return []
    lines = _build_tlb(closes, TLB_SENSITIVITY)
    if len(lines) < 4:
        return []
    last4 = lines[-4:]
    # White turnaround = last 3 are black, newest is white
    if not (
        last4[0]["color"] == "b" and last4[1]["color"] == "b" and last4[2]["color"] == "b" and last4[3]["color"] == "w"
    ):
        return []
    # Only emit on the transition bar (today must be the newest line)
    if lines[-1]["close"] != closes[-1]:
        return []

    entry = closes[-1]
    # Stop: low of the last 3 white lines that preceded the pullback
    prior_whites = [ln for ln in lines[:-3] if ln["color"] == "w"]
    stop_price = prior_whites[-3]["open"] if len(prior_whites) >= 3 else min(ln["close"] for ln in lines[-4:])

    notes = "TLB white turnaround — trend flipped bullish"
    raw = {
        "tlb_lines_tail": [dict(l) for l in lines[-6:]],
        "exits": _mk_exits(
            stop_price=stop_price,
            stop_cond=("black turnaround line (price breaks below the low of the last 3 white lines)"),
            target_price=None,
            target_cond="trail — trend following",
            offset_trigger="black turnaround line appears",
            invalidation="black turnaround line",
            exhaustion="8-10 consecutive white lines (record session rule)",
            time_exit=None,
        ),
    }
    return [
        _signal(
            sym,
            "nison_new_price_chart_trend",
            entry,
            stop_price,
            None,
            "HIGH",
            notes,
            raw,
            signal_type="TLB_WHITE_TURNAROUND",
        )
    ]


def _build_renko(closes, brick_size):
    """Return list of bricks [{close, color}]."""
    if not len(closes) or brick_size <= 0:
        return []
    bricks = []
    last_close = closes[0]
    for c in closes[1:]:
        # One brick per day max (simple, no intraday simulation)
        if c >= last_close + brick_size:
            # Draw enough white bricks to reach c
            while c >= last_close + brick_size:
                last_close += brick_size
                bricks.append({"close": last_close, "color": "w"})
        elif c <= last_close - brick_size:
            while c <= last_close - brick_size:
                last_close -= brick_size
                bricks.append({"close": last_close, "color": "b"})
    return bricks


def _detect_renko(sym, df):
    closes = df["close"].values.astype(float)
    if len(closes) < 30:
        return []
    atr = _atr(df, 20)
    if atr is None or atr <= 0:
        return []
    brick_size = max(atr * RENKO_ATR_MULT, closes[-1] * RENKO_PCT_FLOOR)
    bricks = _build_renko(closes, brick_size)
    if len(bricks) < 2:
        return []
    # Fresh white brick today
    if bricks[-1]["color"] != "w" or bricks[-2]["color"] == "w":
        return []

    entry = closes[-1]
    stop_price = bricks[-1]["close"] - brick_size  # bottom of the white brick

    notes = f"Renko: new white brick above ₹{_fmt_num(bricks[-1]['close'])} (brick size ₹{_fmt_num(brick_size)})"
    raw = {
        "brick_size": round(brick_size, 2),
        "last_brick_close": bricks[-1]["close"],
        "exits": _mk_exits(
            stop_price=stop_price,
            stop_cond=("close crosses below the most recent white brick (new black brick)"),
            target_price=None,
            target_cond="trail — trend following",
            offset_trigger="new black brick appears",
            invalidation="new black brick",
            exhaustion="8-10 consecutive white bricks (record session rule)",
            time_exit=None,
        ),
    }
    return [
        _signal(
            sym,
            "nison_new_price_chart_trend",
            entry,
            stop_price,
            None,
            "HIGH",
            notes,
            raw,
            signal_type="RENKO_WHITE_BRICK",
        )
    ]


def _build_kagi(closes, turnaround_pct):
    """Return (state_list, last_yang_flip_index)."""
    state = []
    if not len(closes):
        return state, None
    trend = None
    extreme = closes[0]
    last_flip = None
    for i, c in enumerate(closes):
        if trend is None:
            trend = "up" if c > extreme else "down"
            extreme = c
            state.append({"i": i, "trend": trend, "close": c})
            continue
        if trend == "up":
            if c > extreme:
                extreme = c
            elif c <= extreme * (1 - turnaround_pct):
                trend = "down"
                extreme = c
                state.append({"i": i, "trend": trend, "close": c})
        elif c < extreme:
            extreme = c
        elif c >= extreme * (1 + turnaround_pct):
            trend = "up"
            extreme = c
            last_flip = i
            state.append({"i": i, "trend": trend, "close": c})
    return state, last_flip


def _detect_kagi(sym, df):
    closes = df["close"].values.astype(float)
    if len(closes) < 30:
        return []
    _state, flip_idx = _build_kagi(closes, KAGI_TURNAROUND_PCT)
    if flip_idx is None:
        return []
    # Flip must be today
    if flip_idx != len(closes) - 1:
        return []
    entry = closes[-1]
    # Stop: below the recent low established during the preceding yin leg
    recent_low = min(closes[max(0, flip_idx - 20) : flip_idx + 1])

    notes = f"Kagi yang flip at ₹{_fmt_num(entry)} (turnaround {KAGI_TURNAROUND_PCT * 100:.1f}%)"
    raw = {
        "turnaround_pct": KAGI_TURNAROUND_PCT,
        "recent_low": recent_low,
        "exits": _mk_exits(
            stop_price=recent_low,
            stop_cond=("kagi line turns from yang to yin (prior waist broken)"),
            target_price=None,
            target_cond="trail — trend following",
            offset_trigger="yang→yin transition",
            invalidation="yang→yin transition",
            exhaustion="9+ higher shoulders (record session rule)",
            time_exit=None,
        ),
    }
    return [
        _signal(
            sym, "nison_new_price_chart_trend", entry, recent_low, None, "HIGH", notes, raw, signal_type="KAGI_YANG"
        )
    ]


# ----------------------------------------------------------------
# Per-symbol scan
# ----------------------------------------------------------------
def _scan_symbol(sym, df):
    sigs = []
    _try_emit(sigs, lambda: _detect_candlestick_reversal(sym, df))
    _try_emit(sigs, lambda: _detect_rising_window(sym, df))
    _try_emit(sigs, lambda: _detect_long_white_candle(sym, df))
    _try_emit(sigs, lambda: _detect_disparity_oversold(sym, df))
    _try_emit(sigs, lambda: _detect_golden_cross(sym, df))
    # TLB / Renko / Kagi — all three sub-variants of method 6
    _try_emit(sigs, lambda: _detect_tlb(sym, df))
    _try_emit(sigs, lambda: _detect_renko(sym, df))
    _try_emit(sigs, lambda: _detect_kagi(sym, df))
    return sigs


# ----------------------------------------------------------------
# Universe scan
# ----------------------------------------------------------------
def scan(conn=None, limit=DEFAULT_LIMIT):
    own = conn is None
    if own:
        conn = db.get_conn()
    syms = band_universe(conn, limit=limit)
    log.info(f"Nison scan: {len(syms)} symbols in universe")

    signals = []
    n_loaded = 0
    n_short_hist = 0
    n_low_price = 0
    for i, sym in enumerate(syms, 1):
        df = _load_df(conn, sym)
        if df is None:
            n_short_hist += 1
            continue
        if df["close"].iloc[-1] < MIN_PRICE:
            n_low_price += 1
            continue
        n_loaded += 1
        try:
            signals.extend(_scan_symbol(sym, df))
        except Exception as e:
            log.warning(f"{sym} scan failed: {e}")
        if i % 100 == 0:
            log.info(f"  progress {i}/{len(syms)}, {len(signals)} signals")

    if own:
        conn.close()

    n_sym = len({s["symbol"] for s in signals})
    log.info(
        f"Nison scan complete: {n_loaded} loaded, "
        f"short_history={n_short_hist}, "
        f"price<₹{MIN_PRICE}={n_low_price}, "
        f"{len(signals)} signals across {n_sym} symbols"
    )
    return signals
