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
Alpesh B. Patel & Paresh H. Kiri — 7 Simple Strategies of Highly
Effective Traders (2010).
Classified: SWING (long-only, no intraday, no shorting).

11 methods extracted per docs/BOOK_EXTRACTION_PROMPT.md.
Owner's extraction removed all intraday and short-side methods
before handoff; this module implements the remaining long-only
swing/positional setups.

Everything here is price-only. No fundamental feeds, no event feeds.
All 11 methods scanned. No flagged methods. Fully implementable today.

Signal shape:
  entry = the trigger price (breakout level, MA line, etc.)
  stop  = None (2x ATR stops are trade management, per R30 skip list)
  target = None
Direction: BULLISH only (long-only extraction).

Bug-safety per R35:
  - _fmt_num(v, dp) returns "—" for None/NaN — no .Nf on None
  - _try_emit wraps each signal so one method's failure never
    kills the symbol's other signals
"""
import db
import numpy as np
import pandas as pd
from log_utils import get_logger
from universe_helper import band_universe

log = get_logger("trader.seven_simple_strategies")

SLUG = "seven_simple_strategies"
NAME = "Alpesh Patel & Paresh Kiri"
PILLAR = "swing"
SOURCE = "7 Simple Strategies of Highly Effective Traders (2010)"


# ----------------------------------------------------------------
# Tunables — book-cited thresholds
# ----------------------------------------------------------------
TICK = 0.05
MIN_PRICE = 100
MIN_BARS = 260  # room for 200-SMA
DEFAULT_LIMIT = 800

# Method 1 — Breakout with momentum
BREAKOUT_DAYS = 20
CLOSE_LOCATION_MIN = 0.75  # close within 25% of high
VOL_CONFIRM = 1.50  # vol_ratio_20 >= 1.5
GAP_UP_MIN = 0.01  # 1% gap up alternative path

# Method 2 — Mean reversion
MEAN_LOOKBACK = 100
MEAN_EXTENSION = 0.02  # price 2% below mean

# Method 6/7/8 — Trend lines + channel
PIVOT_K = 3
TRENDLINE_LOOKBACK = 90
CHANNEL_LOOKBACK = 90
LINE_TOUCH_ATR = 0.5  # touch tolerance in ATRs
LINE_BREAK_ATR = 2.0  # break distance in ATRs

# Method 9 — Golden entry
CONSOLIDATION_LOOKBACK = 20
CONSOLIDATION_MAX_RANGE = 0.10
GOLDEN_BREAK_ATR = 2.0

# Methods 10/11 — Candlestick
DOWNTREND_BARS = 3  # 3 consecutive lower closes required


# ----------------------------------------------------------------
# METHODS registry — 11 total, all scanned
# ----------------------------------------------------------------
METHODS = [
    {
        "id": "breakout_with_momentum_long",
        "name": "Breakout With Momentum",
        "description": "20d breakout or gap-up, close near high, vol >= 1.5x.",
        "direction": "long",
        "scan": True,
        "confidence": "HIGH",
    },
    {
        "id": "mean_reversion_long",
        "name": "Mean Reversion (Long)",
        "description": "Price >= 2% below 100-day mean + bullish reversal.",
        "direction": "long",
        "scan": True,
        "confidence": "MED",
    },
    {
        "id": "ma_crossover_50_200_long",
        "name": "MA Crossover 50/200",
        "description": "50-SMA crosses above 200-SMA.",
        "direction": "long",
        "scan": True,
        "confidence": "HIGH",
    },
    {
        "id": "ma_crossover_10ema_24sma_long",
        "name": "MA Crossover 10 EMA / 24 SMA",
        "description": "10-EMA crosses above 24-SMA (short-term trend flip).",
        "direction": "long",
        "scan": True,
        "confidence": "HIGH",
    },
    {
        "id": "ma_crossover_9ema_16sma_long",
        "name": "MA Crossover 9 EMA / 16 SMA",
        "description": "9-EMA crosses above 16-SMA (longer-term flip).",
        "direction": "long",
        "scan": True,
        "confidence": "HIGH",
    },
    {
        "id": "trend_line_with_trend_long",
        "name": "Trend Line Trade (With Trend)",
        "description": "Touch of uptrend line + bullish candle.",
        "direction": "long",
        "scan": True,
        "confidence": "MED",
    },
    {
        "id": "trend_line_break_long",
        "name": "Trend Line Break",
        "description": "Break above downtrend line by >= 2 ATR + volume.",
        "direction": "long",
        "scan": True,
        "confidence": "HIGH",
    },
    {
        "id": "channel_trade_long",
        "name": "Channel Trade",
        "description": "Touch of lower channel + bullish candle.",
        "direction": "long",
        "scan": True,
        "confidence": "MED",
    },
    {
        "id": "golden_entry_long",
        "name": "Golden Entry",
        "description": "Consolidation breakout >= 2 ATR + volume.",
        "direction": "long",
        "scan": True,
        "confidence": "HIGH",
    },
    {
        "id": "bullish_hammer_long",
        "name": "Bullish Hammer",
        "description": "Hammer after 3 lower closes.",
        "direction": "long",
        "scan": True,
        "confidence": "MED",
    },
    {
        "id": "bullish_doji_long",
        "name": "Bullish Doji / Spinning Top",
        "description": "Small-range bullish candle after 3 lower closes.",
        "direction": "long",
        "scan": True,
        "confidence": "MED",
    },
]


# ----------------------------------------------------------------
# Helpers
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
    """Null-safe number formatting (R35)."""
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
    """Wrap each signal emit so one method's failure doesn't kill others."""
    try:
        s = fn()
        if s is not None:
            sigs.append(s)
    except Exception as e:
        log.warning(f"signal emit skipped: {e}")


def _load_df(conn, sym, limit=600):
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


def _atr(df, period=14):
    """Wilder-style ATR."""
    h = df["high"].values.astype(float)
    l = df["low"].values.astype(float)
    c = df["close"].values.astype(float)
    n = len(c)
    if n < period + 1:
        return None
    tr = np.zeros(n)
    tr[0] = h[0] - l[0]
    for i in range(1, n):
        tr[i] = max(
            h[i] - l[i],
            abs(h[i] - c[i - 1]),
            abs(l[i] - c[i - 1]),
        )
    alpha = 2.0 / (period + 1)
    atr = tr[0]
    for i in range(1, n):
        atr = alpha * tr[i] + (1 - alpha) * atr
    return float(atr)


def _sma_at(arr, period):
    if len(arr) < period:
        return None
    return float(np.mean(arr[-period:]))


def _sma_prev(arr, period):
    if len(arr) < period + 1:
        return None
    return float(np.mean(arr[-period - 1 : -1]))


def _ema_series(arr, span):
    return pd.Series(arr).ewm(span=span, adjust=False).mean().values


def _is_bullish(b):
    return b["close"] > b["open"]


def _has_downtrend(df, k=DOWNTREND_BARS):
    """True if the last k bars all made lower closes."""
    if len(df) < k + 1:
        return False
    c = df["close"].values
    return all(c[i] < c[i - 1] for i in range(len(c) - k, len(c)))


def _is_hammer(df, i):
    """Book spec: lower shadow >= 2x body, upper shadow <= 0.2x body,
    close in upper 25% of range."""
    o = float(df["open"].iloc[i])
    h = float(df["high"].iloc[i])
    l = float(df["low"].iloc[i])
    c = float(df["close"].iloc[i])
    rng = h - l
    if rng <= 0:
        return False
    body = abs(c - o)
    lower = min(o, c) - l
    upper = h - max(o, c)
    close_pos = (c - l) / rng
    # body can be tiny — use a small epsilon guard
    if body < 1e-6:
        # treat as doji-ish, hammer needs a body relative to shadows
        return (lower >= 0.6 * rng) and (upper <= 0.2 * rng) and close_pos >= 0.75
    return lower >= 2.0 * body and upper <= 0.2 * body and close_pos >= 0.75


def _is_bullish_doji(df, i, atr):
    """Book spec: real body <= 0.5 x ATR, close > open, close in upper
    50% of range."""
    o = float(df["open"].iloc[i])
    c = float(df["close"].iloc[i])
    h = float(df["high"].iloc[i])
    l = float(df["low"].iloc[i])
    rng = h - l
    if rng <= 0 or atr is None or atr <= 0:
        return False
    body = abs(c - o)
    if c <= o:
        return False
    close_pos = (c - l) / rng
    return body <= 0.5 * atr and close_pos >= 0.5


def _fit_line_from_pivots(levels, k=PIVOT_K, lookback=TRENDLINE_LOOKBACK):
    """
    Fit line through the last two pivots in `levels`.
    levels = list of (index, price). Returns (slope, intercept) or None.
    """
    if len(levels) < 2:
        return None
    (x1, y1), (x2, y2) = levels[-2], levels[-1]
    if x2 == x1:
        return None
    m = (y2 - y1) / (x2 - x1)
    b = y1 - m * x1
    return m, b


def _pivot_lows(df, k=PIVOT_K, lookback=TRENDLINE_LOOKBACK):
    lows = df["low"].values.astype(float)
    n = len(lows)
    start = max(k, n - lookback)
    piv = []
    for i in range(start, n - k):
        win = lows[i - k : i + k + 1]
        if lows[i] == win.min():
            piv.append((i, float(lows[i])))
    return piv


def _pivot_highs(df, k=PIVOT_K, lookback=TRENDLINE_LOOKBACK):
    highs = df["high"].values.astype(float)
    n = len(highs)
    start = max(k, n - lookback)
    piv = []
    for i in range(start, n - k):
        win = highs[i - k : i + k + 1]
        if highs[i] == win.max():
            piv.append((i, float(highs[i])))
    return piv


# ----------------------------------------------------------------
# Method detectors
# ----------------------------------------------------------------
def _sig(sym, method_id, entry, confidence, notes, raw):
    return {
        "symbol": sym,
        "trader": SLUG,
        "method": method_id,
        "direction": "BULLISH",
        "signal_type": "LONG_SETUP",
        "entry": round(float(entry), 2) if entry is not None else None,
        "stop": None,
        "target": None,
        "confidence": confidence,
        "notes": notes,
        "raw": raw,
    }


def _detect_breakout_momentum(sym, df, atr, vol_ratio):
    c = df["close"].values.astype(float)
    h = df["high"].values.astype(float)
    l = df["low"].values.astype(float)
    o = df["open"].values.astype(float)
    n = len(c)
    if n < BREAKOUT_DAYS + 2:
        return []
    prior_high = float(np.max(h[-BREAKOUT_DAYS - 1 : -1]))
    prior_high_yest = float(np.max(h[-BREAKOUT_DAYS - 2 : -2]))

    today_rng = h[-1] - l[-1]
    if today_rng <= 0:
        return []
    close_loc = (c[-1] - l[-1]) / today_rng

    # Path 1 — fresh 20d breakout
    fresh_break = c[-1] > prior_high + TICK and c[-2] <= prior_high_yest + TICK
    # Path 2 — gap-up >= 1% from prior close
    gap_up = o[-1] > c[-2] * (1 + GAP_UP_MIN)

    if not (fresh_break or gap_up):
        return []
    if close_loc < CLOSE_LOCATION_MIN:
        return []
    if vol_ratio is None or vol_ratio < VOL_CONFIRM:
        return []

    path = "20d breakout" if fresh_break else "gap-up"
    return [
        _sig(
            sym,
            "breakout_with_momentum_long",
            c[-1],
            "HIGH",
            f"Breakout with momentum ({path}), close at {close_loc * 100:.0f}% of range, vol {_fmt_num(vol_ratio, 2)}x",
            {"path": path, "close_location": round(close_loc, 3), "vol_ratio": vol_ratio},
        )
    ]


def _detect_mean_reversion(sym, df, atr):
    c = df["close"].values.astype(float)
    o = df["open"].values.astype(float)
    h = df["high"].values.astype(float)
    l = df["low"].values.astype(float)
    n = len(c)
    if n < MEAN_LOOKBACK + 2:
        return []
    mean = float(np.mean(c[-MEAN_LOOKBACK:]))
    threshold = mean * (1 - MEAN_EXTENSION)
    if c[-1] > threshold:
        return []

    # Bullish reversal candle: close > open and close in upper half
    rng = h[-1] - l[-1]
    if rng <= 0 or c[-1] <= o[-1]:
        return []
    close_pos = (c[-1] - l[-1]) / rng
    if close_pos < 0.5:
        return []

    return [
        _sig(
            sym,
            "mean_reversion_long",
            c[-1],
            "MED",
            f"Mean reversion: close ₹{_fmt_num(c[-1])} "
            f"{MEAN_EXTENSION * 100:.0f}%+ below "
            f"{MEAN_LOOKBACK}d mean ₹{_fmt_num(mean)}, bullish candle",
            {"mean": mean, "close": float(c[-1]), "close_pos": round(close_pos, 3)},
        )
    ]


def _detect_ma_cross(sym, df, fast_kind, fast_span, slow_span, method_id, confidence, label):
    c = df["close"].values.astype(float)
    n = len(c)
    if n < slow_span + 2:
        return []
    if fast_kind == "ema":
        fast_now = _ema_series(c, fast_span)[-1]
        fast_prev = _ema_series(c[:-1], fast_span)[-1]
    else:
        fast_now = _sma_at(c, fast_span)
        fast_prev = _sma_prev(c, fast_span)
    slow_now = _sma_at(c, slow_span)
    slow_prev = _sma_prev(c, slow_span)
    if None in (fast_now, fast_prev, slow_now, slow_prev):
        return []
    if not (fast_prev <= slow_prev and fast_now > slow_now):
        return []
    return [
        _sig(
            sym,
            method_id,
            c[-1],
            confidence,
            f"{label} bullish cross (fast {_fmt_num(fast_now)} > slow {_fmt_num(slow_now)})",
            {"fast_now": float(fast_now), "slow_now": float(slow_now)},
        )
    ]


def _detect_trend_line_with_trend(sym, df, atr):
    """Touch of an uptrend line drawn from the last two swing lows,
    with a bullish candle."""
    if atr is None or atr <= 0:
        return []
    lows = _pivot_lows(df)
    if len(lows) < 2:
        return []
    line = _fit_line_from_pivots(lows)
    if line is None:
        return []
    m, b = line
    if m <= 0:
        # uptrend line must have positive slope
        return []
    today_x = len(df) - 1
    line_price = m * today_x + b
    today_low = float(df["low"].iloc[-1])
    today_close = float(df["close"].iloc[-1])
    today_open = float(df["open"].iloc[-1])
    if abs(today_low - line_price) > LINE_TOUCH_ATR * atr:
        return []
    if today_close <= today_open:
        return []
    return [
        _sig(
            sym,
            "trend_line_with_trend_long",
            today_close,
            "MED",
            f"Uptrend line touch at ₹{_fmt_num(line_price)}, bullish candle closes ₹{_fmt_num(today_close)}",
            {"line_price": float(line_price), "slope": float(m)},
        )
    ]


def _detect_trend_line_break(sym, df, atr, vol_ratio):
    """Break above a downtrend line by >= 2 ATR + volume."""
    if atr is None or atr <= 0:
        return []
    highs = _pivot_highs(df)
    if len(highs) < 2:
        return []
    line = _fit_line_from_pivots(highs)
    if line is None:
        return []
    m, b = line
    if m >= 0:
        # downtrend line must have negative slope
        return []
    today_x = len(df) - 1
    line_price = m * today_x + b
    today_close = float(df["close"].iloc[-1])
    if today_close <= line_price + LINE_BREAK_ATR * atr:
        return []
    if vol_ratio is None or vol_ratio < VOL_CONFIRM:
        return []
    return [
        _sig(
            sym,
            "trend_line_break_long",
            today_close,
            "HIGH",
            f"Downtrend line break by {(today_close - line_price) / atr:.1f}N, vol {_fmt_num(vol_ratio, 2)}x",
            {
                "line_price": float(line_price),
                "break_atr": float((today_close - line_price) / atr),
                "vol_ratio": vol_ratio,
            },
        )
    ]


def _detect_channel_trade(sym, df, atr):
    """Touch of lower channel line (parallel to upper) + bullish candle."""
    if atr is None or atr <= 0:
        return []
    lows = _pivot_lows(df, lookback=CHANNEL_LOOKBACK)
    highs = _pivot_highs(df, lookback=CHANNEL_LOOKBACK)
    if len(lows) < 2 or len(highs) < 2:
        return []
    low_line = _fit_line_from_pivots(lows)
    high_line = _fit_line_from_pivots(highs)
    if low_line is None or high_line is None:
        return []
    ml, bl = low_line
    mh, _bh = high_line
    # channels should be roughly parallel — check slope agreement
    if (ml > 0) != (mh > 0):
        return []
    if abs(ml - mh) > 0.5 * max(abs(ml), abs(mh), 1e-6):
        return []
    today_x = len(df) - 1
    lower_price = ml * today_x + bl
    today_low = float(df["low"].iloc[-1])
    today_close = float(df["close"].iloc[-1])
    today_open = float(df["open"].iloc[-1])
    if abs(today_low - lower_price) > LINE_TOUCH_ATR * atr:
        return []
    if today_close <= today_open:
        return []
    return [
        _sig(
            sym,
            "channel_trade_long",
            today_close,
            "MED",
            f"Lower channel touch at ₹{_fmt_num(lower_price)}, bullish candle",
            {"lower_channel": float(lower_price), "slope": float(ml)},
        )
    ]


def _detect_golden_entry(sym, df, atr, vol_ratio):
    """Consolidation (range <= 10% over 20 bars) + breakout >= 2 ATR
    + volume."""
    if atr is None or atr <= 0:
        return []
    h = df["high"].values.astype(float)
    l = df["low"].values.astype(float)
    c = df["close"].values.astype(float)
    n = len(c)
    if n < CONSOLIDATION_LOOKBACK + 3:
        return []
    # Consolidation window = bars [-LOOKBACK-1:-1] (excludes today)
    win_high = float(np.max(h[-CONSOLIDATION_LOOKBACK - 1 : -1]))
    win_low = float(np.min(l[-CONSOLIDATION_LOOKBACK - 1 : -1]))
    win_price = float(np.mean(c[-CONSOLIDATION_LOOKBACK - 1 : -1]))
    if win_price <= 0:
        return []
    win_range_pct = (win_high - win_low) / win_price
    if win_range_pct > CONSOLIDATION_MAX_RANGE:
        return []
    if c[-1] <= win_high + GOLDEN_BREAK_ATR * atr:
        return []
    if vol_ratio is None or vol_ratio < VOL_CONFIRM:
        return []
    return [
        _sig(
            sym,
            "golden_entry_long",
            c[-1],
            "HIGH",
            f"Golden Entry: {CONSOLIDATION_LOOKBACK}d range "
            f"{win_range_pct * 100:.1f}%, breakout "
            f"{(c[-1] - win_high) / atr:.1f}N, "
            f"vol {_fmt_num(vol_ratio, 2)}x",
            {
                "consolidation_range_pct": round(win_range_pct, 4),
                "breakout_atr": float((c[-1] - win_high) / atr),
                "vol_ratio": vol_ratio,
            },
        )
    ]


def _detect_hammer(sym, df, atr):
    if atr is None or atr <= 0:
        return []
    if not _has_downtrend(df, DOWNTREND_BARS):
        return []
    if not _is_hammer(df, len(df) - 1):
        return []
    c = float(df["close"].iloc[-1])
    return [
        _sig(sym, "bullish_hammer_long", c, "MED", f"Bullish hammer after {DOWNTREND_BARS} lower closes", {"close": c})
    ]


def _detect_doji(sym, df, atr):
    if atr is None or atr <= 0:
        return []
    if not _has_downtrend(df, DOWNTREND_BARS):
        return []
    if not _is_bullish_doji(df, len(df) - 1, atr):
        return []
    c = float(df["close"].iloc[-1])
    return [
        _sig(
            sym,
            "bullish_doji_long",
            c,
            "MED",
            f"Bullish doji/spinning top after {DOWNTREND_BARS} lower closes",
            {"close": c},
        )
    ]


# ----------------------------------------------------------------
# Per-symbol scan
# ----------------------------------------------------------------
def _scan_symbol(sym, df):
    atr = _atr(df, 14)
    # vol_ratio_20 from df directly (avoids DB round-trip)
    vols = df["volume"].values.astype(float)
    vol_ratio = None
    if len(vols) >= 20:
        avg = float(np.mean(vols[-20:]))
        if avg > 0:
            vol_ratio = float(vols[-1]) / avg

    sigs = []
    _try_emit(sigs, lambda: _detect_breakout_momentum(sym, df, atr, vol_ratio))
    _try_emit(sigs, lambda: _detect_mean_reversion(sym, df, atr))
    _try_emit(
        sigs, lambda: _detect_ma_cross(sym, df, "sma", 50, 200, "ma_crossover_50_200_long", "HIGH", "50SMA/200SMA")
    )
    _try_emit(
        sigs, lambda: _detect_ma_cross(sym, df, "ema", 10, 24, "ma_crossover_10ema_24sma_long", "HIGH", "10EMA/24SMA")
    )
    _try_emit(
        sigs, lambda: _detect_ma_cross(sym, df, "ema", 9, 16, "ma_crossover_9ema_16sma_long", "HIGH", "9EMA/16SMA")
    )
    _try_emit(sigs, lambda: _detect_trend_line_with_trend(sym, df, atr))
    _try_emit(sigs, lambda: _detect_trend_line_break(sym, df, atr, vol_ratio))
    _try_emit(sigs, lambda: _detect_channel_trade(sym, df, atr))
    _try_emit(sigs, lambda: _detect_golden_entry(sym, df, atr, vol_ratio))
    _try_emit(sigs, lambda: _detect_hammer(sym, df, atr))
    _try_emit(sigs, lambda: _detect_doji(sym, df, atr))

    # Flatten (some detectors return lists, some return _try_emit single)
    out = []
    for s in sigs:
        if isinstance(s, list):
            out.extend(s)
        elif s is not None:
            out.append(s)
    return out


# ----------------------------------------------------------------
# Universe scan
# ----------------------------------------------------------------
def scan(conn=None, limit=800):
    own = conn is None
    if own:
        conn = db.get_conn()

    syms = band_universe(conn, limit=limit)
    log.info(f"7SS scan: {len(syms)} symbols in universe")

    signals = []
    n_loaded = 0
    n_skipped_short = 0
    n_skipped_price = 0

    for i, sym in enumerate(syms, 1):
        df = _load_df(conn, sym)
        if df is None:
            n_skipped_short += 1
            continue
        if df["close"].iloc[-1] < MIN_PRICE:
            n_skipped_price += 1
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

    log.info(
        f"7SS scan complete: {n_loaded} loaded, "
        f"skipped(short_history)={n_skipped_short}, "
        f"skipped(price<₹{MIN_PRICE})={n_skipped_price}, "
        f"{len(signals)} signals across "
        f"{len({s['symbol'] for s in signals})} symbols"
    )
    return signals
