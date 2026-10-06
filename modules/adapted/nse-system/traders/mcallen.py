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
Fred McAllen — Charting and Technical Analysis.
Classified: MULTI (Swing + Positional, long-only extraction).

11 methods extracted per docs/BOOK_EXTRACTION_PROMPT.md, restricted
to the NET-NEW patterns not already implemented in patterns.py or
in traders #1-#12 (Option B, per owner instruction I73).

Overlap handling — R41: each signal carries overlaps_with=[...] to
mark the trader it conceptually echoes. The owner decides later
whether to prune or keep.

Signal types (R43):
  - LONG_ENTRY      — 4 patterns: saucer, island, 3 white soldiers,
                      bullish harami
  - TOP_WARNING     — 7 patterns: 3 black crows, bearish harami,
                      hanging man, shooting star, exhaustion gap,
                      spike top, descending triangle
  Top-warnings are informational. They flag a potential exit for the
  owner's review. They are NOT short entries.

Exit strategy (R40): every signal carries raw.exits with
  thesis + hard_number + condition per rule.
Blocks: stop_out, target, offset, invalidation, exhaustion, time_exit.

R35 safety: _fmt_num + _try_emit from day one.
"""
import db
import numpy as np
import pandas as pd
from log_utils import get_logger

log = get_logger("trader.mcallen")

SLUG = "mcallen"
NAME = "Fred McAllen"
PILLAR = "multi"
SOURCE = "Charting and Technical Analysis"


# ----------------------------------------------------------------
# Tunables — book-cited parameters
# ----------------------------------------------------------------
TICK = 0.05
MIN_PRICE = 100
MIN_BARS = 200
DEFAULT_LIMIT = 800

# Volume confirmation
VOL_CONFIRM = 1.2
VOL_MIN = 0.5

# Chart patterns
SAUCER_MIN_WEEKS = 12
SAUCER_MAX_WEEKS = 26
SAUCER_MAX_DEPTH = 0.50

ISLAND_MAX_DAYS = 10
ISLAND_MIN_DAYS = 2

DESC_TRI_FLAT_TOL = 0.02  # 2% — pivot lows treated as flat
DESC_TRI_DECLINE_MIN = 0.01  # 1% — pivot highs must decline at least

# Candlestick
LONG_BODY_RATIO = 0.5  # body >= 50% of range = long candle
SMALL_BODY_RATIO = 0.3  # body <= 30% of range = small candle
HAMMER_WICK_RATIO = 2.0  # lower wick >= 2x body (hammer/hanging man)
HAMMER_BODY_MAX = 0.4  # body <= 40% of range

# Exhaustion gap
EXHAUSTION_ADVANCE_MIN = 0.30  # 30% prior advance
EXHAUSTION_LOOKBACK = 40

# Spike top
SPIKE_ADVANCE_MIN = 0.30
SPIKE_ANGLE_THRESHOLD = 0.015  # ~45° when normalised (slope/price)
SPIKE_LOOKBACK = 20


# ----------------------------------------------------------------
# METHODS registry — 11 total (4 entries, 7 warnings)
# ----------------------------------------------------------------
METHODS = [
    # ---- LONG ENTRIES (4) ----
    {
        "id": "mcallen_saucer_bottom_long",
        "name": "Saucer Bottom Long",
        "description": "Long rounding bottom over 12-26 weeks + resistance breakout on volume.",
        "direction": "long",
        "scan": True,
        "confidence": "MED",
        "signal_type": "LONG_ENTRY",
    },
    {
        "id": "mcallen_island_bottom_long",
        "name": "Island Bottom Long",
        "description": "Gap-down followed by gap-up isolating price "
        "action at a low. Confirms major turn up.",
        "direction": "long",
        "scan": True,
        "confidence": "MED",
        "signal_type": "LONG_ENTRY",
    },
    {
        "id": "mcallen_three_white_soldiers_long",
        "name": "Three White Soldiers Long",
        "description": "3 consecutive long white candles, each closing higher. Continuation entry.",
        "direction": "long",
        "scan": True,
        "confidence": "MED",
        "signal_type": "LONG_ENTRY",
    },
    {
        "id": "mcallen_bullish_harami_long",
        "name": "Bullish Harami Long",
        "description": "Small bullish candle inside a prior large bearish "
        "candle after a decline. Reversal entry.",
        "direction": "long",
        "scan": True,
        "confidence": "MED",
        "signal_type": "LONG_ENTRY",
    },
    # ---- TOP WARNINGS (7) — informational, not short ----
    {
        "id": "mcallen_three_black_crows_warning",
        "name": "Three Black Crows Warning",
        "description": "3 consecutive long black candles. Top warning.",
        "direction": "long",
        "scan": True,
        "confidence": "MED",
        "signal_type": "TOP_WARNING",
    },
    {
        "id": "mcallen_bearish_harami_warning",
        "name": "Bearish Harami Warning",
        "description": "Small bearish candle inside a prior large bullish "
        "candle after an advance. Top warning.",
        "direction": "long",
        "scan": True,
        "confidence": "MED",
        "signal_type": "TOP_WARNING",
    },
    {
        "id": "mcallen_hanging_man_warning",
        "name": "Hanging Man Warning",
        "description": "Hammer shape after an advance. Top warning.",
        "direction": "long",
        "scan": True,
        "confidence": "MED",
        "signal_type": "TOP_WARNING",
    },
    {
        "id": "mcallen_shooting_star_warning",
        "name": "Shooting Star Warning",
        "description": "Inverted hammer after an advance. Top warning.",
        "direction": "long",
        "scan": True,
        "confidence": "MED",
        "signal_type": "TOP_WARNING",
    },
    {
        "id": "mcallen_exhaustion_gap_warning",
        "name": "Exhaustion Gap Warning",
        "description": "Gap up after an extended advance — last gasp of the move. Top warning.",
        "direction": "long",
        "scan": True,
        "confidence": "MED",
        "signal_type": "TOP_WARNING",
    },
    {
        "id": "mcallen_spike_top_warning",
        "name": "Spike Top Warning",
        "description": "Parabolic >45° advance. Top warning.",
        "direction": "long",
        "scan": True,
        "confidence": "MED",
        "signal_type": "TOP_WARNING",
    },
    {
        "id": "mcallen_descending_triangle_warning",
        "name": "Descending Triangle Warning",
        "description": "Lower highs into flat support. Top warning / breakdown setup.",
        "direction": "long",
        "scan": True,
        "confidence": "MED",
        "signal_type": "TOP_WARNING",
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
# Data + indicators
# ----------------------------------------------------------------
def _load_df(conn, sym, limit=500):
    rows = conn.execute(
        "SELECT date, open, high, low, close, volume "
        "FROM prices_daily WHERE symbol=? ORDER BY date DESC LIMIT ?",
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


def _pivots(values, k=3, lookback=100, kind="low"):
    n = len(values)
    start = max(k, n - lookback)
    out = []
    for i in range(start, n - k):
        win = values[i - k : i + k + 1]
        if kind == "low" and values[i] == win.min() or kind == "high" and values[i] == win.max():
            out.append((i, float(values[i])))
    return out


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


def _prior_downtrend(df, k=10):
    if len(df) < k + 1:
        return False
    closes = df["close"].values.astype(float)
    return closes[-1] < closes[-k - 1]


def _prior_uptrend(df, k=10):
    if len(df) < k + 1:
        return False
    closes = df["close"].values.astype(float)
    return closes[-1] > closes[-k - 1]


def _vol_ratio(df):
    vols = df["volume"].values.astype(float)
    avg = _sma(vols, 20)
    if avg is None or avg <= 0:
        return None
    return float(vols[-1]) / avg


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
    exhaustion_thesis=None,
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
        "offset": {
            "thesis": offset_thesis,
            "trigger": offset_trigger,
        },
        "invalidation": {
            "thesis": invalidation_thesis,
            "condition": invalidation_condition,
        },
        "exhaustion": (
            {"thesis": exhaustion_thesis, "rule": "volume climax or extended advance"}
            if exhaustion_thesis
            else None
        ),
        "time_exit": (
            {"thesis": time_exit_thesis, "sessions": time_exit_sessions}
            if time_exit_sessions
            else None
        ),
    }


# ----------------------------------------------------------------
# Signal constructor
# ----------------------------------------------------------------
def _signal(
    sym, method_id, signal_type, entry, stop, target, confidence, notes, raw, overlaps_with=None
):
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


# ----------------------------------------------------------------
# Detectors — chart patterns
# ----------------------------------------------------------------
def _detect_saucer(df):
    """
    Long rounding bottom. Left side descending, right side ascending,
    low in the middle third of the window.
    """
    n = len(df)
    if n < SAUCER_MIN_WEEKS * 5:
        return None
    window = min(SAUCER_MAX_WEEKS * 5, n)
    h = df["high"].values.astype(float)
    l = df["low"].values.astype(float)
    c = df["close"].values.astype(float)
    seg_h = h[-window:]
    seg_l = l[-window:]
    seg_c = c[-window:]

    ll_idx = int(np.argmin(seg_l))
    # Low must be in the middle third
    if ll_idx < window * 0.25 or ll_idx > window * 0.75:
        return None

    left = seg_c[:ll_idx]
    right = seg_c[ll_idx:]
    if len(left) < 10 or len(right) < 10:
        return None

    left_slope = (left[-1] - left[0]) / max(1, len(left))
    right_slope = (right[-1] - right[0]) / max(1, len(right))
    if left_slope >= 0 or right_slope <= 0:
        return None

    saucer_low = float(seg_l[ll_idx])
    resistance = float(np.max(seg_h[:ll_idx])) if ll_idx > 0 else None
    if resistance is None or resistance <= saucer_low:
        return None

    depth = (resistance - saucer_low) / resistance
    if depth > SAUCER_MAX_DEPTH:
        return None

    weeks = window / 5.0
    if weeks < SAUCER_MIN_WEEKS:
        return None

    breakout = seg_c[-1] > resistance * (1 + TICK / 100.0)
    return {
        "saucer_low": saucer_low,
        "resistance": resistance,
        "depth": round(depth, 3),
        "weeks": round(weeks, 1),
        "breakout": breakout,
    }


def _detect_island_bottom(df):
    """Gap-down then gap-up isolating price action."""
    n = len(df)
    if n < 15:
        return None
    h = df["high"].values.astype(float)
    l = df["low"].values.astype(float)
    c = df["close"].values.astype(float)

    for i in range(n - 15, n - 2):
        if i < 1:
            continue
        if h[i] < l[i - 1] * 0.997:  # gap down
            is_low = float(l[i])
            is_high = float(h[i])
            for j in range(i + 1, min(i + ISLAND_MAX_DAYS + 1, n)):
                is_low = min(is_low, float(l[j]))
                is_high = max(is_high, float(h[j]))
                if j + 1 < n and l[j + 1] > h[j] * 1.003:  # gap up
                    days = j - i + 1
                    if days < ISLAND_MIN_DAYS:
                        continue
                    return {
                        "island_low": is_low,
                        "island_high": is_high,
                        "days": days,
                        "start_idx": i,
                        "end_idx": j,
                        "confirmed": c[-1] > is_high,
                    }
    return None


def _detect_descending_triangle(df):
    """Lower highs into flat support — top warning."""
    n = len(df)
    if n < 60:
        return None
    h = df["high"].values.astype(float)
    l = df["low"].values.astype(float)
    c = df["close"].values.astype(float)

    piv_h = _pivots(h, k=3, lookback=60, kind="high")
    piv_l = _pivots(l, k=3, lookback=60, kind="low")
    if len(piv_h) < 2 or len(piv_l) < 2:
        return None

    h1, h2 = piv_h[-2][1], piv_h[-1][1]
    if h2 >= h1 * (1 - DESC_TRI_DECLINE_MIN):
        return None

    l1, l2 = piv_l[-2][1], piv_l[-1][1]
    if l1 <= 0 or abs(l2 - l1) / l1 > DESC_TRI_FLAT_TOL:
        return None

    flat_support = (l1 + l2) / 2
    if c[-1] > flat_support * 1.03:
        return None

    return {
        "flat_support": flat_support,
        "declining_highs": [h1, h2],
        "current_close": float(c[-1]),
        "breakdown": c[-1] < flat_support * 0.9995,
    }


# ----------------------------------------------------------------
# Detectors — candlestick patterns
# ----------------------------------------------------------------
def _is_three_white_soldiers(df, i):
    if i < 2:
        return False
    shapes = [_candle_shape(df, j) for j in range(i - 2, i + 1)]
    if any(s is None for s in shapes):
        return False
    if not all(s["is_bull"] for s in shapes):
        return False
    if not (shapes[0]["close"] < shapes[1]["close"] < shapes[2]["close"]):
        return False
    return not any(s["body"] < LONG_BODY_RATIO * s["rng"] for s in shapes)


def _is_three_black_crows(df, i):
    if i < 2:
        return False
    shapes = [_candle_shape(df, j) for j in range(i - 2, i + 1)]
    if any(s is None for s in shapes):
        return False
    if any(s["is_bull"] for s in shapes):
        return False
    if not (shapes[0]["close"] > shapes[1]["close"] > shapes[2]["close"]):
        return False
    return not any(s["body"] < LONG_BODY_RATIO * s["rng"] for s in shapes)


def _is_bullish_harami(df, i):
    if i < 1:
        return False
    prev = _candle_shape(df, i - 1)
    cur = _candle_shape(df, i)
    if prev is None or cur is None:
        return False
    if prev["is_bull"] or not cur["is_bull"]:
        return False
    if prev["body"] < LONG_BODY_RATIO * prev["rng"]:
        return False
    if cur["body"] > SMALL_BODY_RATIO * cur["rng"]:
        return False
    body_lo = min(prev["open"], prev["close"])
    body_hi = max(prev["open"], prev["close"])
    return cur["open"] >= body_lo and cur["close"] <= body_hi


def _is_bearish_harami(df, i):
    if i < 1:
        return False
    prev = _candle_shape(df, i - 1)
    cur = _candle_shape(df, i)
    if prev is None or cur is None:
        return False
    if not prev["is_bull"] or cur["is_bull"]:
        return False
    if prev["body"] < LONG_BODY_RATIO * prev["rng"]:
        return False
    if cur["body"] > SMALL_BODY_RATIO * cur["rng"]:
        return False
    body_lo = min(prev["open"], prev["close"])
    body_hi = max(prev["open"], prev["close"])
    return cur["open"] <= body_hi and cur["close"] >= body_lo


def _is_hanging_man(s):
    """Hammer shape (long lower wick, small body, little upper wick)."""
    if s is None:
        return False
    if s["body"] < 1e-6:
        return (
            s["lower"] >= 0.6 * s["rng"] and s["upper"] <= 0.15 * s["rng"] and s["close_pos"] >= 0.6
        )
    return (
        s["lower"] >= HAMMER_WICK_RATIO * s["body"]
        and s["body"] <= HAMMER_BODY_MAX * s["rng"]
        and s["upper"] <= 0.2 * s["body"]
        and s["close_pos"] >= 0.55
    )


def _is_shooting_star(s):
    """Inverted hammer (long upper wick, small body, little lower wick)."""
    if s is None:
        return False
    if s["body"] < 1e-6:
        return (
            s["upper"] >= 0.6 * s["rng"] and s["lower"] <= 0.15 * s["rng"] and s["close_pos"] <= 0.4
        )
    return (
        s["upper"] >= HAMMER_WICK_RATIO * s["body"]
        and s["body"] <= HAMMER_BODY_MAX * s["rng"]
        and s["lower"] <= 0.2 * s["body"]
        and s["close_pos"] <= 0.45
    )


# ----------------------------------------------------------------
# Detectors — gaps and spikes
# ----------------------------------------------------------------
def _detect_exhaustion_gap(df):
    """Gap up after an extended advance."""
    n = len(df)
    if n < EXHAUSTION_LOOKBACK + 3:
        return None
    h = df["high"].values.astype(float)
    l = df["low"].values.astype(float)
    c = df["close"].values.astype(float)
    o = df["open"].values.astype(float)

    # Today must be a gap up
    if not (l[-1] > h[-2] * 1.005):
        return None
    # Prior advance
    prior_low = float(np.min(l[-EXHAUSTION_LOOKBACK:-1]))
    prior_high = float(np.max(h[-EXHAUSTION_LOOKBACK:-1]))
    if prior_low <= 0:
        return None
    advance = prior_high / prior_low - 1
    if advance < EXHAUSTION_ADVANCE_MIN:
        return None
    return {
        "gap_pct": round((o[-1] / c[-2] - 1), 4),
        "prior_advance": round(advance, 3),
        "gap_high": float(h[-1]),
        "gap_low": float(l[-1]),
    }


def _detect_spike_top(df):
    """Parabolic >45° advance."""
    n = len(df)
    if n < SPIKE_LOOKBACK + 3:
        return None
    closes = df["close"].values.astype(float)
    seg = closes[-SPIKE_LOOKBACK:]
    if seg[0] <= 0:
        return None
    # Simple slope per bar, normalised by price
    x = np.arange(len(seg))
    slope = np.polyfit(x, seg, 1)[0]
    angle = slope / np.mean(seg)
    advance = seg[-1] / seg[0] - 1
    if angle < SPIKE_ANGLE_THRESHOLD or advance < SPIKE_ADVANCE_MIN:
        return None
    return {
        "angle": round(angle, 4),
        "advance": round(advance, 3),
        "peak_close": float(seg[-1]),
    }


# ============================================================
# Method 1 — Saucer Bottom Long
# ============================================================
def _detect_saucer_signal(sym, df):
    saucer = _detect_saucer(df)
    if saucer is None or not saucer["breakout"]:
        return []
    vr = _vol_ratio(df)
    if vr is None or vr < VOL_CONFIRM:
        return []
    entry = float(df["close"].iloc[-1])
    stop = saucer["saucer_low"]
    target = saucer["resistance"] + (saucer["resistance"] - saucer["saucer_low"])
    notes = (
        f"Saucer breakout above ₹{_fmt_num(saucer['resistance'])} "
        f"(depth {saucer['depth'] * 100:.1f}%, "
        f"{saucer['weeks']:.0f}w), vol {_fmt_num(vr, 2)}x"
    )
    raw = {
        "saucer_low": saucer["saucer_low"],
        "resistance": saucer["resistance"],
        "depth": saucer["depth"],
        "weeks": saucer["weeks"],
        "vol_ratio": vr,
        "exits": _mk_exits(
            stop_hard=stop,
            stop_thesis=(
                "Book: stop is placed below the saucer's "
                "structural low. A close below that level "
                "invalidates the rounding bottom thesis."
            ),
            stop_condition=f"close below ₹{_fmt_num(stop)} (saucer low)",
            target_hard=target,
            target_thesis=(
                "Book: measured move = saucer depth projected above the breakout level."
            ),
            target_condition=f"close ≥ ₹{_fmt_num(target)}",
            offset_thesis=(
                "Book: a close back below the breakout "
                "resistance re-enters the pattern — the "
                "breakout has failed."
            ),
            offset_trigger="close back below breakout resistance",
            invalidation_thesis=("Book: pattern invalid if price makes a new saucer low."),
            invalidation_condition="close < saucer low",
            time_exit_sessions=20,
            time_exit_thesis=(
                "Book: no explicit time exit. 20 sessions "
                "is a reasonable window to see follow-"
                "through before reassessing."
            ),
        ),
        "overlap_note": (
            "Overlaps patterns.DOUBLE_BOTTOM — different "
            "shape (longer rounding vs. W). Marked, "
            "not pruned."
        ),
    }
    return [
        _signal(
            sym,
            "mcallen_saucer_bottom_long",
            "LONG_ENTRY",
            entry,
            stop,
            target,
            "MED",
            notes,
            raw,
            overlaps_with=["patterns.DOUBLE_BOTTOM"],
        )
    ]


# ============================================================
# Method 2 — Island Bottom Long
# ============================================================
def _detect_island_signal(sym, df):
    island = _detect_island_bottom(df)
    if island is None:
        return []
    vr = _vol_ratio(df)
    entry = float(df["close"].iloc[-1])
    stop = island["island_low"]
    target = island["island_high"] + (island["island_high"] - island["island_low"])
    notes = (
        f"Island bottom: {island['days']}d isolated "
        f"₹{_fmt_num(island['island_low'])}–"
        f"₹{_fmt_num(island['island_high'])}"
    )
    raw = {
        "island_low": island["island_low"],
        "island_high": island["island_high"],
        "island_days": island["days"],
        "vol_ratio": vr,
        "exits": _mk_exits(
            stop_hard=stop,
            stop_thesis=(
                "Book: the island's low is the structural floor. Break below it negates the island."
            ),
            stop_condition=f"close below ₹{_fmt_num(stop)}",
            target_hard=target,
            target_thesis=(
                "Book: measured move = island height projected above the island's high."
            ),
            target_condition=f"close ≥ ₹{_fmt_num(target)}",
            offset_thesis=(
                "Book: a close back inside the island's range voids the reversal signal."
            ),
            offset_trigger="close inside island range",
            invalidation_thesis="Book: pattern invalid if island low breaks.",
            invalidation_condition="close < island low",
            time_exit_sessions=15,
            time_exit_thesis="No explicit book rule; standard window.",
        ),
        "overlap_note": (
            "Related to nison.nison_rising_window_support "
            "— different shape (isolated island vs. single "
            "gap). Marked, not pruned."
        ),
    }
    return [
        _signal(
            sym,
            "mcallen_island_bottom_long",
            "LONG_ENTRY",
            entry,
            stop,
            target,
            "MED",
            notes,
            raw,
            overlaps_with=["nison.nison_rising_window_support"],
        )
    ]


# ============================================================
# Method 3 — Three White Soldiers Long
# ============================================================
def _detect_three_white_soldiers_signal(sym, df):
    if len(df) < 15:
        return []
    if not _is_three_white_soldiers(df, len(df) - 1):
        return []
    vr = _vol_ratio(df)
    if vr is None or vr < VOL_CONFIRM:
        return []
    # Context: somewhere in an uptrend or reversal
    closes = df["close"].values.astype(float)
    sma50 = _sma(closes, 50)
    if sma50 is None:
        return []
    entry = closes[-1]
    stop = float(df["low"].iloc[-3])  # low of first soldier
    target = entry + 2.0 * (entry - stop)
    notes = f"Three white soldiers — 3 long bull candles, vol {_fmt_num(vr, 2)}x"
    raw = {
        "vol_ratio": vr,
        "sma50": sma50,
        "exits": _mk_exits(
            stop_hard=stop,
            stop_thesis=(
                "Book: stop is placed below the first soldier's "
                "low — the pattern is invalidated if that level "
                "is breached."
            ),
            stop_condition=f"close below ₹{_fmt_num(stop)}",
            target_hard=target,
            target_thesis=("Book: measured move = 2× risk from the pattern low."),
            target_condition=f"close ≥ ₹{_fmt_num(target)}",
            offset_thesis=(
                "Book: a single bearish engulfing or three "
                "black crows after the pattern signals the "
                "move is over."
            ),
            offset_trigger="bearish engulfing or three black crows",
            invalidation_thesis="Book: close below first soldier low.",
            invalidation_condition="close < first soldier low",
            exhaustion_thesis=("Book: volume climax at the top of a run is the exhaustion signal."),
            time_exit_sessions=20,
            time_exit_thesis="Standard window.",
        ),
        "overlap_note": (
            "Related to nison (candle family) — different "
            "shape (3 consecutive long bull candles vs. "
            "single reversal). Marked, not pruned."
        ),
    }
    return [
        _signal(
            sym,
            "mcallen_three_white_soldiers_long",
            "LONG_ENTRY",
            entry,
            stop,
            target,
            "MED",
            notes,
            raw,
            overlaps_with=["nison.nison_candlestick_reversal_at_support"],
        )
    ]


# ============================================================
# Method 4 — Bullish Harami Long
# ============================================================
def _detect_bullish_harami_signal(sym, df):
    if len(df) < 20:
        return []
    if not _is_bullish_harami(df, len(df) - 1):
        return []
    if not _prior_downtrend(df, k=10):
        return []
    vr = _vol_ratio(df)
    entry = float(df["close"].iloc[-1])
    stop = float(df["low"].iloc[-1])
    target = entry + 2.0 * (entry - stop)
    notes = "Bullish harami: small bull candle inside prior large bear candle"
    raw = {
        "vol_ratio": vr,
        "exits": _mk_exits(
            stop_hard=stop,
            stop_thesis="Book: stop below the harami's low.",
            stop_condition=f"close below ₹{_fmt_num(stop)}",
            target_hard=target,
            target_thesis="Book: 2× risk target (standard).",
            target_condition=f"close ≥ ₹{_fmt_num(target)}",
            offset_thesis="Book: opposing candle patterns negate the setup.",
            offset_trigger="bearish harami or engulfing next bar",
            invalidation_thesis="Book: close below harami low.",
            invalidation_condition="close < harami low",
            time_exit_sessions=10,
            time_exit_thesis="Standard window for candle reversals.",
        ),
        "overlap_note": (
            "Related to nison candlestick family — "
            "different shape (harami vs. engulfing). "
            "Marked, not pruned."
        ),
    }
    return [
        _signal(
            sym,
            "mcallen_bullish_harami_long",
            "LONG_ENTRY",
            entry,
            stop,
            target,
            "MED",
            notes,
            raw,
            overlaps_with=["nison.nison_candlestick_reversal_at_support"],
        )
    ]


# ============================================================
# Method 5 — Three Black Crows Warning
# ============================================================
def _detect_three_black_crows_signal(sym, df):
    if len(df) < 15:
        return []
    if not _is_three_black_crows(df, len(df) - 1):
        return []
    vr = _vol_ratio(df)
    entry = float(df["close"].iloc[-1])
    stop = float(df["high"].iloc[-3])
    target = entry - 1.0 * (stop - entry)  # informational
    notes = "Three black crows — 3 long bear candles, top warning" + (
        f", vol {_fmt_num(vr, 2)}x" if vr else ""
    )
    raw = {
        "vol_ratio": vr,
        "exits": _mk_exits(
            stop_hard=stop,
            stop_thesis=("Book: a close back above the first crow's high re-asserts bulls."),
            stop_condition=f"close above ₹{_fmt_num(stop)}",
            target_hard=target,
            target_thesis=(
                "Book: measured move down = 1× pattern range. Informational for owner review."
            ),
            target_condition=f"close ≤ ₹{_fmt_num(target)}",
            offset_thesis=(
                "Book: exit longs if a position is still open on the pattern's completion."
            ),
            offset_trigger="close below third crow's low",
            invalidation_thesis="Book: close above first crow's high.",
            invalidation_condition="close > first crow high",
            time_exit_sessions=10,
            time_exit_thesis="Review window for the warning.",
        ),
        "warning_note": (
            "TOP_WARNING, not a short entry. Owner reviews existing positions. See R43."
        ),
        "overlap_note": "Related to patterns.HEAD_SHOULDERS_TOP_WARNING.",
    }
    return [
        _signal(
            sym,
            "mcallen_three_black_crows_warning",
            "TOP_WARNING",
            entry,
            stop,
            target,
            "MED",
            notes,
            raw,
            overlaps_with=["patterns.HEAD_SHOULDERS_TOP_WARNING"],
        )
    ]


# ============================================================
# Method 6 — Bearish Harami Warning
# ============================================================
def _detect_bearish_harami_signal(sym, df):
    if len(df) < 20:
        return []
    if not _is_bearish_harami(df, len(df) - 1):
        return []
    if not _prior_uptrend(df, k=10):
        return []
    entry = float(df["close"].iloc[-1])
    stop = float(df["high"].iloc[-1])
    target = entry - (stop - entry)
    notes = "Bearish harami — small bear candle inside prior large bull candle, top warning"
    raw = {
        "exits": _mk_exits(
            stop_hard=stop,
            stop_thesis="Book: close above the harami high voids warning.",
            stop_condition=f"close above ₹{_fmt_num(stop)}",
            target_hard=target,
            target_thesis="Book: 1× risk (informational).",
            target_condition=f"close ≤ ₹{_fmt_num(target)}",
            offset_thesis="Book: exit longs on opposing candle.",
            offset_trigger="bullish harami or engulfing next bar",
            invalidation_thesis="Book: close above harami high.",
            invalidation_condition="close > harami high",
            time_exit_sessions=5,
            time_exit_thesis="Review window.",
        ),
        "warning_note": "TOP_WARNING (R43).",
        "overlap_note": "Related to nison candlestick family.",
    }
    return [
        _signal(
            sym,
            "mcallen_bearish_harami_warning",
            "TOP_WARNING",
            entry,
            stop,
            target,
            "MED",
            notes,
            raw,
            overlaps_with=["nison.nison_candlestick_reversal_at_support"],
        )
    ]


# ============================================================
# Method 7 — Hanging Man Warning
# ============================================================
def _detect_hanging_man_signal(sym, df):
    if len(df) < 20:
        return []
    if not _prior_uptrend(df, k=10):
        return []
    s = _candle_shape(df, len(df) - 1)
    if not _is_hanging_man(s):
        return []
    entry = float(df["close"].iloc[-1])
    stop = s["high"]
    target = entry - (stop - entry)
    notes = "Hanging man — hammer shape after an advance, top warning"
    raw = {
        "exits": _mk_exits(
            stop_hard=stop,
            stop_thesis="Book: close above hanging man high.",
            stop_condition=f"close above ₹{_fmt_num(stop)}",
            target_hard=target,
            target_thesis="Book: 1× range (informational).",
            target_condition=f"close ≤ ₹{_fmt_num(target)}",
            offset_thesis="Book: exit longs on close below hanging man low.",
            offset_trigger="close below hanging man low",
            invalidation_thesis="Book: close above hanging man high.",
            invalidation_condition="close > hanging man high",
            time_exit_sessions=3,
            time_exit_thesis="Candle warning window.",
        ),
        "warning_note": "TOP_WARNING (R43).",
        "overlap_note": "Related to patterns.HIGH_TIGHT_FLAG (top family).",
    }
    return [
        _signal(
            sym,
            "mcallen_hanging_man_warning",
            "TOP_WARNING",
            entry,
            stop,
            target,
            "MED",
            notes,
            raw,
            overlaps_with=["patterns.HIGH_TIGHT_FLAG"],
        )
    ]


# ============================================================
# Method 8 — Shooting Star Warning
# ============================================================
def _detect_shooting_star_signal(sym, df):
    if len(df) < 20:
        return []
    if not _prior_uptrend(df, k=10):
        return []
    s = _candle_shape(df, len(df) - 1)
    if not _is_shooting_star(s):
        return []
    entry = float(df["close"].iloc[-1])
    stop = s["high"]
    target = entry - (stop - entry)
    notes = "Shooting star — inverted hammer after an advance"
    raw = {
        "exits": _mk_exits(
            stop_hard=stop,
            stop_thesis="Book: close above shooting star high.",
            stop_condition=f"close above ₹{_fmt_num(stop)}",
            target_hard=target,
            target_thesis="Book: 1× range (informational).",
            target_condition=f"close ≤ ₹{_fmt_num(target)}",
            offset_thesis="Book: exit longs on close below shooting star low.",
            offset_trigger="close below shooting star low",
            invalidation_thesis="Book: close above shooting star high.",
            invalidation_condition="close > shooting star high",
            time_exit_sessions=3,
            time_exit_thesis="Candle warning window.",
        ),
        "warning_note": "TOP_WARNING (R43).",
        "overlap_note": "Related to nison candlestick family.",
    }
    return [
        _signal(
            sym,
            "mcallen_shooting_star_warning",
            "TOP_WARNING",
            entry,
            stop,
            target,
            "MED",
            notes,
            raw,
            overlaps_with=["nison.nison_candlestick_reversal_at_support"],
        )
    ]


# ============================================================
# Method 9 — Exhaustion Gap Warning
# ============================================================
def _detect_exhaustion_gap_signal(sym, df):
    g = _detect_exhaustion_gap(df)
    if g is None:
        return []
    entry = float(df["close"].iloc[-1])
    stop = g["gap_high"]
    target = g["gap_low"]
    notes = (
        f"Exhaustion gap up +{_fmt_num(g['gap_pct'] * 100, 1)}% "
        f"after +{_fmt_num(g['prior_advance'] * 100, 0)}% advance"
    )
    raw = {
        "gap_pct": g["gap_pct"],
        "prior_advance": g["prior_advance"],
        "gap_high": g["gap_high"],
        "gap_low": g["gap_low"],
        "exits": _mk_exits(
            stop_hard=stop,
            stop_thesis="Book: close above the gap high re-asserts bulls.",
            stop_condition=f"close above ₹{_fmt_num(stop)}",
            target_hard=target,
            target_thesis=(
                "Book: a close below the gap low confirms the exhaustion — a sign to exit longs."
            ),
            target_condition=f"close ≤ ₹{_fmt_num(target)} (gap fill)",
            offset_thesis="Book: gap fill within 3 sessions confirms the exhaustion.",
            offset_trigger="close below gap low within 3 sessions",
            invalidation_thesis="Book: a new high above gap high voids it.",
            invalidation_condition="close > gap high",
            exhaustion_thesis=(
                "Book: the gap itself is the exhaustion signal. Owner reviews longs for trimming."
            ),
            time_exit_sessions=3,
            time_exit_thesis="Confirming window.",
        ),
        "warning_note": "TOP_WARNING (R43).",
        "overlap_note": "Related to nison rising window (inverse use).",
    }
    return [
        _signal(
            sym,
            "mcallen_exhaustion_gap_warning",
            "TOP_WARNING",
            entry,
            stop,
            target,
            "MED",
            notes,
            raw,
            overlaps_with=["nison.nison_rising_window_support"],
        )
    ]


# ============================================================
# Method 10 — Spike Top Warning
# ============================================================
def _detect_spike_top_signal(sym, df):
    sp = _detect_spike_top(df)
    if sp is None:
        return []
    entry = float(df["close"].iloc[-1])
    stop = sp["peak_close"] * 1.02
    target = entry * 0.90
    notes = f"Spike top: {sp['angle'] * 100:.2f}%/bar slope, +{sp['advance'] * 100:.0f}% advance"
    raw = {
        "angle": sp["angle"],
        "advance": sp["advance"],
        "exits": _mk_exits(
            stop_hard=stop,
            stop_thesis="Book: close above spike peak invalidates.",
            stop_condition=f"close above ₹{_fmt_num(stop)}",
            target_hard=target,
            target_thesis=(
                "Book: spike tops reverse sharply. Target is "
                "informational — owner decides trim level."
            ),
            target_condition=f"close ≤ ₹{_fmt_num(target)}",
            offset_thesis="Book: exit longs on the first bearish candle.",
            offset_trigger="first bearish engulfing or shooting star",
            invalidation_thesis="Book: new 52-week high voids the warning.",
            invalidation_condition="new 52w high",
            exhaustion_thesis=("Book: >45° advance is the exhaustion signal. Owner reviews longs."),
            time_exit_sessions=10,
            time_exit_thesis="Review window.",
        ),
        "warning_note": "TOP_WARNING (R43).",
        "overlap_note": "Related to O'Neil exhaustion family.",
    }
    return [
        _signal(
            sym,
            "mcallen_spike_top_warning",
            "TOP_WARNING",
            entry,
            stop,
            target,
            "MED",
            notes,
            raw,
            overlaps_with=["oneil.oneil_can_slim_composite"],
        )
    ]


# ============================================================
# Method 11 — Descending Triangle Warning
# ============================================================
def _detect_descending_triangle_signal(sym, df):
    tri = _detect_descending_triangle(df)
    if tri is None:
        return []
    entry = float(df["close"].iloc[-1])
    stop = tri["declining_highs"][0]  # first pivot high
    target = tri["flat_support"] - (stop - tri["flat_support"])
    notes = f"Descending triangle: flat support ₹{_fmt_num(tri['flat_support'])}, declining highs"
    raw = {
        "flat_support": tri["flat_support"],
        "declining_highs": tri["declining_highs"],
        "breakdown": tri["breakdown"],
        "exits": _mk_exits(
            stop_hard=stop,
            stop_thesis="Book: close above first pivot high voids.",
            stop_condition=f"close above ₹{_fmt_num(stop)}",
            target_hard=target,
            target_thesis="Book: measured move = triangle height.",
            target_condition=f"close ≤ ₹{_fmt_num(target)}",
            offset_thesis="Book: exit longs on support break.",
            offset_trigger="close below flat support",
            invalidation_thesis="Book: breakout above declining line voids.",
            invalidation_condition="close > declining trendline",
            time_exit_sessions=10,
            time_exit_thesis="Review window.",
        ),
        "warning_note": "TOP_WARNING (R43).",
        "overlap_note": ("Related to patterns.ASCENDING_TRIANGLE (inverse). Marked, not pruned."),
    }
    return [
        _signal(
            sym,
            "mcallen_descending_triangle_warning",
            "TOP_WARNING",
            entry,
            stop,
            target,
            "MED",
            notes,
            raw,
            overlaps_with=["patterns.ASCENDING_TRIANGLE"],
        )
    ]


# ----------------------------------------------------------------
# Per-symbol scan
# ----------------------------------------------------------------
def _scan_symbol(sym, df):
    sigs = []
    _try_emit(sigs, lambda: _detect_saucer_signal(sym, df))
    _try_emit(sigs, lambda: _detect_island_signal(sym, df))
    _try_emit(sigs, lambda: _detect_three_white_soldiers_signal(sym, df))
    _try_emit(sigs, lambda: _detect_bullish_harami_signal(sym, df))
    _try_emit(sigs, lambda: _detect_three_black_crows_signal(sym, df))
    _try_emit(sigs, lambda: _detect_bearish_harami_signal(sym, df))
    _try_emit(sigs, lambda: _detect_hanging_man_signal(sym, df))
    _try_emit(sigs, lambda: _detect_shooting_star_signal(sym, df))
    _try_emit(sigs, lambda: _detect_exhaustion_gap_signal(sym, df))
    _try_emit(sigs, lambda: _detect_spike_top_signal(sym, df))
    _try_emit(sigs, lambda: _detect_descending_triangle_signal(sym, df))
    return sigs


# ----------------------------------------------------------------
# Universe scan
# ----------------------------------------------------------------
def scan(conn=None, limit=DEFAULT_LIMIT, symbols=None):
    own = conn is None
    if own:
        conn = db.get_conn()
    from traders.base import select_scan_symbols

    syms = select_scan_symbols(conn, limit, symbols)
    log.info(f"McAllen scan: {len(syms)} symbols in universe")

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
            signals.extend(_scan_symbol(sym, df))
        except Exception as e:
            log.warning(f"{sym} scan failed: {e}")
        if i % 100 == 0:
            log.info(f"  progress {i}/{len(syms)}, {len(signals)} signals")

    if own:
        conn.close()

    n_sym = len({s["symbol"] for s in signals})
    n_entry = sum(1 for s in signals if s["signal_type"] == "LONG_ENTRY")
    n_warn = sum(1 for s in signals if s["signal_type"] == "TOP_WARNING")
    log.info(
        f"McAllen scan complete: {n_loaded} loaded, "
        f"short_history={n_short}, price<₹{MIN_PRICE}={n_low}, "
        f"{len(signals)} signals across {n_sym} symbols "
        f"({n_entry} entries, {n_warn} top-warnings)"
    )
    return signals
