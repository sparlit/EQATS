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
Tushar S. Chande — Beyond Technical Analysis (2001).
Classified: MULTI (Swing + Positional, long-only).

5 methods extracted per docs/BOOK_EXTRACTION_PROMPT.md.
All methods price-only. No data blocks. Fully implementable today.

Method 4 (Gold-Bond Intermarket) and Method 7 (Trend-Antitrend) were
removed by the owner during extraction — not implemented.

Exit strategy (R40): every signal carries raw.exits — SUGGESTIVE.
Each exit rule has:
    - thesis      : plain-English explainer, cites the book
    - hard_number : a computed price where the rule yields one
    - condition   : textual trigger for when the rule fires
Blocks: stop_out, target, offset, invalidation, exhaustion, time_exit.

Overlap marking: same policy as Nison — mark, don't prune.
Owner decides later whether to consolidate.

R35 safety: _fmt_num + _try_emit from day one.
"""
import db
import numpy as np
import pandas as pd
from log_utils import get_logger
from universe_helper import band_universe

log = get_logger("trader.chande")

SLUG = "chande"
NAME = "Tushar Chande"
PILLAR = "multi"
SOURCE = "Beyond Technical Analysis (2001)"


# ----------------------------------------------------------------
# Tunables — book-cited parameters
# ----------------------------------------------------------------
TICK = 0.05
MIN_PRICE = 100
MIN_BARS = 120
DEFAULT_LIMIT = 800

VOL_MIN = 1.2

# Method 1 — 65sma-3cc
SMA65_PERIOD = 65
CONSEC_CLOSES = 3
RAVI_MIN = 0.5  # percent

# Method 2 — CB-PB
CB_HIGH_DAYS = 20
CB_HIGH_WINDOW = 7
CB_LOW_DAYS = 5
CB_TRAIL_LOW_DAYS = 40

# Method 3 — ADX Burst
ADX_PERIOD = 18
ADX_BURST_MIN = 1.0
SMA_FAST = 3
SMA_SLOW = 12
ADX_BURST_TIME_EXIT = 20

# Method 4 — Bottom-fishing
BF_LOW_DAYS = 20
BF_LOW_WINDOW = 5
BF_RANGE_ATR_MULT = 1.5  # conservative
BF_CLOSE_ATR_MULT = 0.5  # conservative

# Method 5 — Extraordinary opportunity
EXTRA_FAST_SMA = 7
EXTRA_SLOW_SMA = 50
EXTRA_BAND_PCT = 0.03
EXTRA_BREAKOUT_DAYS = 20

# Stops (translated from dollar stops to volatility-based)
STOP_ATR_MULT = 2.0
STOP_ATR_MULT_AGGRESSIVE = 2.5
STOP_PCT = 0.02


# ----------------------------------------------------------------
# METHODS registry — 5 total, all scanned
# ----------------------------------------------------------------
METHODS = [
    {
        "id": "chande_65sma_3cc",
        "name": "65sma-3cc Trend-Following",
        "description": "3 consecutive closes above the 65-day SMA → long. Exit on 3 consecutive closes below.",
        "direction": "long",
        "scan": True,
        "confidence": "HIGH",
    },
    {
        "id": "chande_cb_pb_long",
        "name": "Channel Breakout-Pullback (CB-PB)",
        "description": "20-day high within last 7 days + 5-day low today → buy next open.",
        "direction": "long",
        "scan": True,
        "confidence": "HIGH",
    },
    {
        "id": "chande_adx_burst_long",
        "name": "ADX Burst Trend-Seeking",
        "description": "ADX18 up > 1.0 + SMA3 > SMA12 → buy next open.",
        "direction": "long",
        "scan": True,
        "confidence": "MED",
    },
    {
        "id": "chande_bottom_fishing_long",
        "name": "Bottom-Fishing Pattern",
        "description": "20-day low within 5 days + wide range day + strong close → buy next close.",
        "direction": "long",
        "scan": True,
        "confidence": "MED",
    },
    {
        "id": "chande_extraordinary_opportunity_long",
        "name": "Extraordinary Opportunity",
        "description": "7-SMA > 1.03 × 50-SMA + 20-day breakout.",
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
# Data + indicators
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


def _adx(df, period=ADX_PERIOD):
    """Wilder's ADX. Returns array aligned with df, or None."""
    h = df["high"].values.astype(float)
    l = df["low"].values.astype(float)
    c = df["close"].values.astype(float)
    n = len(c)
    if n < 2 * period + 2:
        return None
    tr = np.zeros(n)
    plus_dm = np.zeros(n)
    minus_dm = np.zeros(n)
    for i in range(1, n):
        up = h[i] - h[i - 1]
        dn = l[i - 1] - l[i]
        plus_dm[i] = up if (up > dn and up > 0) else 0.0
        minus_dm[i] = dn if (dn > up and dn > 0) else 0.0
        tr[i] = max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
    atr = np.zeros(n)
    pdm = np.zeros(n)
    mdm = np.zeros(n)
    atr[period] = np.sum(tr[1 : period + 1])
    pdm[period] = np.sum(plus_dm[1 : period + 1])
    mdm[period] = np.sum(minus_dm[1 : period + 1])
    for i in range(period + 1, n):
        atr[i] = atr[i - 1] - atr[i - 1] / period + tr[i]
        pdm[i] = pdm[i - 1] - pdm[i - 1] / period + plus_dm[i]
        mdm[i] = mdm[i - 1] - mdm[i - 1] / period + minus_dm[i]
    pdi = np.zeros(n)
    mdi = np.zeros(n)
    dx = np.zeros(n)
    for i in range(period, n):
        if atr[i] > 0:
            pdi[i] = 100.0 * pdm[i] / atr[i]
            mdi[i] = 100.0 * mdm[i] / atr[i]
        s = pdi[i] + mdi[i]
        if s > 0:
            dx[i] = 100.0 * abs(pdi[i] - mdi[i]) / s
    adx = np.zeros(n)
    adx[2 * period] = np.mean(dx[period : 2 * period + 1])
    for i in range(2 * period + 1, n):
        adx[i] = (adx[i - 1] * (period - 1) + dx[i]) / period
    return adx


def _ravi(closes):
    """Range Action Verification Index = |100 × (SMA7 − SMA65) / SMA65|."""
    s7 = _sma(closes, 7)
    s65 = _sma(closes, SMA65_PERIOD)
    if s7 is None or s65 is None or s65 == 0:
        return None
    return abs(100.0 * (s7 - s65) / s65)


# ----------------------------------------------------------------
# Exit-block builder (R40)
# ----------------------------------------------------------------
def _exits_block(
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
            {"thesis": exhaustion_thesis, "rule": "8–10 consecutive same-direction sessions"}
            if exhaustion_thesis
            else None
        ),
        "time_exit": ({"thesis": time_exit_thesis, "sessions": time_exit_sessions} if time_exit_sessions else None),
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
# METHOD 1 — 65sma-3cc
# ============================================================
def _detect_65sma_3cc(sym, df):
    closes = df["close"].values.astype(float)
    if len(closes) < SMA65_PERIOD + CONSEC_CLOSES + 2:
        return []
    sma65 = _sma(closes, SMA65_PERIOD)
    if sma65 is None:
        return []
    # 3 consecutive closes above SMA65 (today is the 3rd)
    if not all(closes[-i - 1] > sma65 for i in range(CONSEC_CLOSES)):
        return []
    # Yesterday must NOT have had 3 consecutive above (fresh signal)
    sma65_yest = float(np.mean(closes[-SMA65_PERIOD - 1 : -1]))
    prev_three_above = all(closes[-i - 2] > sma65_yest for i in range(CONSEC_CLOSES))
    if prev_three_above:
        return []

    # Optional RAVI filter
    ravi = _ravi(closes)
    if ravi is not None and ravi < RAVI_MIN:
        return []

    atr = _atr(df, 20)
    if atr is None or atr <= 0:
        return []
    entry = closes[-1]
    stop_hard = entry - STOP_ATR_MULT * atr
    if stop_hard >= entry:
        stop_hard = entry * (1 - STOP_PCT)

    notes = f"65sma-3cc long: 3 closes above SMA65 ₹{_fmt_num(sma65)}" + (
        f" · RAVI {_fmt_num(ravi, 2)}%" if ravi else ""
    )
    raw = {
        "sma65": sma65,
        "ravi": ravi,
        "atr": atr,
        "exits": _exits_block(
            stop_hard=stop_hard,
            stop_thesis=(
                "Book: initial money-management stop of "
                "2–3× ATR (translated from the $2,000–$5,000 "
                "futures stops). This is a safety net, not the "
                "trend exit."
            ),
            stop_condition=f"close ≤ ₹{_fmt_num(stop_hard)}",
            target_hard=None,
            target_thesis=(
                "Book does not use a fixed target for this "
                "system — it is a trend-follower designed to "
                "capture intermediate moves; the trend exit "
                "is the primary profit-taker."
            ),
            target_condition="trail — no fixed target",
            offset_thesis=(
                "Book: 'exit when three consecutive closes "
                "below the 65-day SMA'. This is the signal "
                "exit — the trend has changed."
            ),
            offset_trigger="3 consecutive closes below the 65-SMA",
            invalidation_thesis=(
                "Book: 3 consecutive closes below the "
                "65-SMA is the definitive trend-kill. "
                "Same as offset — the book treats entry "
                "and exit symmetrically."
            ),
            invalidation_condition="3 consecutive closes below the 65-SMA",
            time_exit_sessions=14,
            time_exit_thesis=(
                "Book (optional): a 14-day trailing exit "
                "at the lowest low of the last 14 days — "
                "rarely used standalone, a supplement to "
                "the 3cc exit."
            ),
        ),
        "overlap_note": (
            "Conceptual overlap with "
            "way_of_the_turtle.turtle_system_1_20d and "
            "nison.nison_golden_cross — all MA-based "
            "trend following. Different lookback and "
            "confirmation logic. Marked, not pruned."
        ),
    }
    return [
        _signal(
            sym,
            "chande_65sma_3cc",
            entry,
            stop_hard,
            None,
            "HIGH",
            notes,
            raw,
            overlaps_with=[
                "way_of_the_turtle.turtle_system_1_20d",
                "nison.nison_golden_cross",
            ],
        )
    ]


# ============================================================
# METHOD 2 — Channel Breakout-Pullback (CB-PB)
# ============================================================
def _detect_cb_pb(sym, df):
    n = len(df)
    if n < CB_HIGH_DAYS + CB_HIGH_WINDOW + CB_LOW_DAYS + 5:
        return []
    h = df["high"].values.astype(float)
    l = df["low"].values.astype(float)
    c = df["close"].values.astype(float)

    # 20-day high within last 7 sessions
    recent_idx = None
    for j in range(n - CB_HIGH_WINDOW, n):
        window_high = float(np.max(h[j - CB_HIGH_DAYS + 1 : j + 1]))
        if h[j] >= window_high - 1e-9:
            recent_idx = j
    if recent_idx is None:
        return []
    days_since_high = n - 1 - recent_idx
    if days_since_high > CB_HIGH_WINDOW:
        return []

    # 5-day low formed today
    prior_5_low = float(np.min(l[-CB_LOW_DAYS - 1 : -1]))
    if not (l[-1] < prior_5_low - 1e-9):
        return []

    atr = _atr(df, 20)
    if atr is None or atr <= 0:
        return []
    entry = c[-1]
    stop_hard = entry - STOP_ATR_MULT * atr
    # Target: recent 20-day high (short-term exit variant)
    target_hard = float(np.max(h[-CB_HIGH_DAYS:]))
    if target_hard <= entry:
        target_hard = None
    # Trail: 40-day low (long-term exit variant)
    trail_40d_low = float(np.min(l[-CB_TRAIL_LOW_DAYS:])) if n >= CB_TRAIL_LOW_DAYS else None

    notes = f"CB-PB long: 20-day high {days_since_high}d ago, 5-day low today"
    raw = {
        "days_since_20d_high": days_since_high,
        "recent_5d_low": prior_5_low,
        "atr": atr,
        "trail_40d_low": trail_40d_low,
        "exits": _exits_block(
            stop_hard=stop_hard,
            stop_thesis=(
                "Book: initial stop 1.5–2× ATR or 2% equity. "
                "Volatility-based stop; wider than 65sma-3cc "
                "because CB-PB entries are nearer pullback lows."
            ),
            stop_condition=f"close ≤ ₹{_fmt_num(stop_hard)}",
            target_hard=target_hard,
            target_thesis=(
                "Book (short-term variant): exit at the "
                "recent 20-day high with a limit order. "
                "This captures the bounce without waiting "
                "for trend exhaustion."
            ),
            target_condition=(f"limit @ ₹{_fmt_num(target_hard)}" if target_hard else "trail — see long-term"),
            offset_thesis=(
                "Book: none specific — CB-PB is a pullback "
                "buy; there is no opposite-signal exit. "
                "Positions exit via target, trail, or time."
            ),
            offset_trigger="none — see target / trail / time",
            invalidation_thesis=(
                "Book: a new 20-day low after entry voids the setup — the supposed pullback became a downtrend."
            ),
            invalidation_condition="new 20-day low after entry",
            time_exit_sessions=50,
            time_exit_thesis=(
                "Book (intermediate variant): exit on the "
                "close of the 50th day in trade. The "
                "other variant is a trailing stop at the "
                "lowest low of the last 40 days" + (f" (current: ₹{_fmt_num(trail_40d_low)})" if trail_40d_low else "")
            ),
        ),
        "overlap_note": (
            "Overlaps with way_of_the_turtle.turtle_system_1_20d, "
            "seven_simple_strategies.breakout_with_momentum_long, "
            "ishaan_agnihotri.trend_pullback_playbook — all "
            "20-day-breakout + pullback family. Marked, "
            "not pruned."
        ),
    }
    return [
        _signal(
            sym,
            "chande_cb_pb_long",
            entry,
            stop_hard,
            target_hard,
            "HIGH",
            notes,
            raw,
            overlaps_with=[
                "way_of_the_turtle.turtle_system_1_20d",
                "seven_simple_strategies.breakout_with_momentum_long",
                "ishaan_agnihotri.trend_pullback_playbook",
            ],
        )
    ]


# ============================================================
# METHOD 3 — ADX Burst
# ============================================================
def _detect_adx_burst(sym, df):
    n = len(df)
    if n < 2 * ADX_PERIOD + 3:
        return []
    adx = _adx(df, ADX_PERIOD)
    if adx is None:
        return []
    if adx[-1] - adx[-2] <= ADX_BURST_MIN:
        return []
    closes = df["close"].values.astype(float)
    s3 = _sma(closes, SMA_FAST)
    s12 = _sma(closes, SMA_SLOW)
    if s3 is None or s12 is None or s3 <= s12:
        return []

    atr = _atr(df, 20)
    if atr is None or atr <= 0:
        return []
    entry = closes[-1]
    stop_hard = entry - STOP_ATR_MULT_AGGRESSIVE * atr

    notes = (
        f"ADX burst: ADX18 {_fmt_num(adx[-2], 2)} → "
        f"{_fmt_num(adx[-1], 2)} (+"
        f"{_fmt_num(adx[-1] - adx[-2], 2)}), SMA3 "
        f"{_fmt_num(s3)} > SMA12 {_fmt_num(s12)}"
    )
    raw = {
        "adx18_prev": float(adx[-2]),
        "adx18_now": float(adx[-1]),
        "adx_burst": float(adx[-1] - adx[-2]),
        "sma3": s3,
        "sma12": s12,
        "atr": atr,
        "exits": _exits_block(
            stop_hard=stop_hard,
            stop_thesis=(
                "Book: initial stop 2–3× ATR or 2% equity. "
                "Wider stop because ADX bursts can be "
                "whipsawed before the trend takes hold."
            ),
            stop_condition=f"close ≤ ₹{_fmt_num(stop_hard)}",
            target_hard=None,
            target_thesis=("Book does not use a fixed target for ADX burst — it is a momentum-trend hybrid."),
            target_condition="trail — see time exit / trailing",
            offset_thesis=(
                "Book: none specific — this is a momentum "
                "system. Trend reversal is detected by "
                "the trailing stop, not by an opposite signal."
            ),
            offset_trigger="none — see trailing stop / time exit",
            invalidation_thesis=(
                "Book: a failed burst (ADX falls back below the entry level and price reverses) voids the setup."
            ),
            invalidation_condition=("ADX reversal + price below entry level"),
            time_exit_sessions=ADX_BURST_TIME_EXIT,
            time_exit_thesis=(
                "Book: exit on the close of the 20th day "
                "in trade. Alternative: trailing stop at "
                "2× ATR from the highest close."
            ),
        ),
        "overlap_note": (
            "Conceptually related to "
            "larry_spears.force_index (both are momentum-"
            "acceleration filters). Different math, "
            "different trader. Marked, not pruned."
        ),
    }
    return [
        _signal(
            sym,
            "chande_adx_burst_long",
            entry,
            stop_hard,
            None,
            "MED",
            notes,
            raw,
            overlaps_with=["larry_spears.force_index"],
        )
    ]


# ============================================================
# METHOD 4 — Bottom-Fishing
# ============================================================
def _detect_bottom_fishing(sym, df):
    n = len(df)
    if n < BF_LOW_DAYS + BF_LOW_WINDOW + 5:
        return []
    h = df["high"].values.astype(float)
    l = df["low"].values.astype(float)
    c = df["close"].values.astype(float)
    o = df["open"].values.astype(float)

    # 20-day low within last 5 sessions
    recent_low_idx = None
    for j in range(n - BF_LOW_WINDOW, n):
        window_low = float(np.min(l[j - BF_LOW_DAYS + 1 : j + 1]))
        if l[j] <= window_low + 1e-9:
            recent_low_idx = j
    if recent_low_idx is None:
        return []
    days_since_low = n - 1 - recent_low_idx
    if days_since_low > BF_LOW_WINDOW:
        return []

    atr = _atr(df, 20)
    if atr is None or atr <= 0:
        return []

    # Today's range and close-open spread
    today_range = h[-1] - l[-1]
    today_body = c[-1] - o[-1]
    if today_range < BF_RANGE_ATR_MULT * atr:
        return []
    if today_body < BF_CLOSE_ATR_MULT * atr:
        return []

    entry = c[-1]
    stop_hard = entry - STOP_ATR_MULT * atr
    # Trailing stop variant: 5-day low AFTER +2R profit
    two_r = entry + 2 * (entry - stop_hard)
    trail_5d_low = float(np.min(l[-5:]))

    notes = (
        f"Bottom-fishing: 20-day low {days_since_low}d ago, "
        f"wide range {_fmt_num(today_range / atr, 2)}N, "
        f"body {_fmt_num(today_body / atr, 2)}N"
    )
    raw = {
        "days_since_20d_low": days_since_low,
        "range_atr": round(today_range / atr, 2),
        "body_atr": round(today_body / atr, 2),
        "atr": atr,
        "two_r_target": round(two_r, 2),
        "trail_5d_low": trail_5d_low,
        "exits": _exits_block(
            stop_hard=stop_hard,
            stop_thesis=(
                "Book: initial stop 2% equity or 2× ATR. "
                "Because bottom-fishing trades against a "
                "recent decline, a tight volatility stop "
                "protects against continuation lower."
            ),
            stop_condition=f"close ≤ ₹{_fmt_num(stop_hard)}",
            target_hard=None,
            target_thesis=("Book: no fixed target. Profit-taking is trail-based — see trailing exit below."),
            target_condition="trail-based profit-taking",
            offset_thesis=(
                "Book (trailing exit): once the trade has "
                "made 2× ATR in profit, trail the stop at "
                "the 5-day low" + (f" (current: ₹{_fmt_num(trail_5d_low)})" if trail_5d_low else "")
            ),
            offset_trigger="after +2× ATR profit — trail at 5-day low",
            invalidation_thesis=("Book: a new 20-day low after entry voids the capitulation thesis."),
            invalidation_condition="new 20-day low after entry",
            time_exit_sessions=20,
            time_exit_thesis=(
                "Book: exit on the close of the 20th day "
                "in trade. Bottom-fishing is a bounce "
                "trade — it does not wait for a new trend."
            ),
        ),
        "overlap_note": (
            "Overlaps with "
            "nison.nison_candlestick_reversal_at_support, "
            "ishaan_agnihotri.candlestick_reversal_at_support, "
            "seven_simple_strategies.bullish_hammer_long — "
            "all reversal-after-decline family. Chande's "
            "version does not require a specific candle, "
            "only a wide-range day with strong close. "
            "Marked, not pruned."
        ),
    }
    return [
        _signal(
            sym,
            "chande_bottom_fishing_long",
            entry,
            stop_hard,
            None,
            "MED",
            notes,
            raw,
            signal_type="REVERSAL",
            overlaps_with=[
                "nison.nison_candlestick_reversal_at_support",
                "ishaan_agnihotri.candlestick_reversal_at_support",
                "seven_simple_strategies.bullish_hammer_long",
            ],
        )
    ]


# ============================================================
# METHOD 5 — Extraordinary Opportunity
# ============================================================
def _detect_extraordinary(sym, df):
    n = len(df)
    if n < max(EXTRA_SLOW_SMA, EXTRA_BREAKOUT_DAYS) + 5:
        return []
    closes = df["close"].values.astype(float)
    h = df["high"].values.astype(float)

    s7 = _sma(closes, EXTRA_FAST_SMA)
    s50 = _sma(closes, EXTRA_SLOW_SMA)
    if s7 is None or s50 is None or s50 <= 0:
        return []
    band_top = s50 * (1 + EXTRA_BAND_PCT)
    if s7 <= band_top:
        return []

    # 20-day breakout: today's high > prior 20-day high
    prior_high = float(np.max(h[-EXTRA_BREAKOUT_DAYS - 1 : -1]))
    if h[-1] <= prior_high:
        return []

    atr = _atr(df, 20)
    if atr is None or atr <= 0:
        return []
    entry = closes[-1]
    stop_hard = entry - STOP_ATR_MULT_AGGRESSIVE * atr

    notes = (
        f"Extraordinary opportunity: SMA7 {_fmt_num(s7)} > "
        f"1.03 × SMA50 {_fmt_num(s50)}, 20-day breakout above "
        f"₹{_fmt_num(prior_high)}"
    )
    raw = {
        "sma7": s7,
        "sma50": s50,
        "band_top": band_top,
        "prior_20d_high": prior_high,
        "atr": atr,
        "exits": _exits_block(
            stop_hard=stop_hard,
            stop_thesis=(
                "Book: initial stop 2–3× ATR or 3% equity — "
                "the widest stop in the book, reflecting that "
                "extraordinary signals often come with "
                "extraordinary volatility."
            ),
            stop_condition=f"close ≤ ₹{_fmt_num(stop_hard)}",
            target_hard=None,
            target_thesis=(
                "Book: no fixed target — the signal identifies exceptional up-moves, which are held until trend decay."
            ),
            target_condition="trail-based",
            offset_thesis=(
                "Book (signal exit): when the 7-day SMA "
                "falls back inside the 3% band, the "
                "extraordinary condition no longer holds — "
                "exit."
            ),
            offset_trigger="SMA7 re-enters the 3% band around SMA50",
            invalidation_thesis=("Book: same as offset — the extraordinary condition ending is the setup kill."),
            invalidation_condition="SMA7 ≤ 1.03 × SMA50",
            time_exit_sessions=20,
            time_exit_thesis=("Book: exit on the close of the 20th day in trade. Alternative: 3% trailing stop."),
        ),
        "overlap_note": (
            "Overlaps with "
            "seven_simple_strategies.breakout_with_momentum_long "
            "— both use 20-day breakouts. Chande adds the "
            "7/50 SMA band gate, which fires only on "
            "exceptional trends. Marked, not pruned."
        ),
    }
    return [
        _signal(
            sym,
            "chande_extraordinary_opportunity_long",
            entry,
            stop_hard,
            None,
            "MED",
            notes,
            raw,
            signal_type="EXTRAORDINARY_BREAKOUT",
            overlaps_with=["seven_simple_strategies.breakout_with_momentum_long"],
        )
    ]


# ----------------------------------------------------------------
# Per-symbol scan
# ----------------------------------------------------------------
def _scan_symbol(sym, df):
    sigs = []
    _try_emit(sigs, lambda: _detect_65sma_3cc(sym, df))
    _try_emit(sigs, lambda: _detect_cb_pb(sym, df))
    _try_emit(sigs, lambda: _detect_adx_burst(sym, df))
    _try_emit(sigs, lambda: _detect_bottom_fishing(sym, df))
    _try_emit(sigs, lambda: _detect_extraordinary(sym, df))
    return sigs


# ----------------------------------------------------------------
# Universe scan
# ----------------------------------------------------------------
def scan(conn=None, limit=DEFAULT_LIMIT):
    own = conn is None
    if own:
        conn = db.get_conn()
    syms = band_universe(conn, limit=limit)
    log.info(f"Chande scan: {len(syms)} symbols in universe")

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
        f"Chande scan complete: {n_loaded} loaded, "
        f"short_history={n_short_hist}, "
        f"price<₹{MIN_PRICE}={n_low_price}, "
        f"{len(signals)} signals across {n_sym} symbols"
    )
    return signals
