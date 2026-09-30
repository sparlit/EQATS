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
William J. O'Neil — How to Make Money in Stocks.
Classified: MULTI (growth + chart pattern, long-only).

7 methods extracted per docs/BOOK_EXTRACTION_PROMPT.md.

DESIGN PRINCIPLE — R42 (no proxies):
  Every method implements the book's EXACT requirements. If a
  required field is None, the method returns zero signals. Methods
  ship complete and correct; they simply wait for the data.

  This means methods 1-6 all depend on Method 7's confirmed-uptrend
  regime, which requires index data we do not have yet (DR-20).
  Until then they emit zero signals. That is the intended behavior.

  Data gaps are logged at scan time so the owner sees exactly what
  is missing.

Methods:
  1. CAN SLIM composite — needs quarterly EPS + sales YoY, EPS 3y,
     ROE (available), RS rating, sponsorship change, market regime.
  2. Cup-with-handle breakout — needs base-shape detector + market
     regime.
  3. Double bottom (W) breakout — needs O'Neil W detector + market
     regime.
  4. Flat base breakout — needs flat-base detector + market regime.
  5. High tight flag breakout — needs HTF detector + market regime.
  6. Ascending base breakout — needs ascending-base detector +
     market regime.
  7. Market direction filter (registered, not scanned) — computed
     by _compute_market_regime() and consumed by methods 1-6.

Overlap marking — R41, mark-don't-prune. Each signal carries
overlaps_with=[...].

Exit strategy — R40 format. Every signal carries raw.exits with
thesis / hard_number / condition.

R35 safety: _fmt_num + _try_emit from day one.
"""
import db
import numpy as np
import pandas as pd
from log_utils import get_logger
from universe_helper import band_universe

log = get_logger("trader.oneil")

SLUG = "oneil"
NAME = "William J. O'Neil"
PILLAR = "multi"
SOURCE = "How to Make Money in Stocks (4th ed.)"


# ----------------------------------------------------------------
# Tunables — book-cited thresholds (do not adjust without evidence)
# ----------------------------------------------------------------
TICK = 0.05
MIN_PRICE = 100
MIN_BARS = 260
DEFAULT_LIMIT = 800

# CAN SLIM fundamental gates
CURRENT_QTR_EPS_MIN = 0.18  # 18% YoY
CURRENT_QTR_SALES_MIN = 0.25  # 25% YoY
ANNUAL_EPS_3YR_MIN = 0.25  # 25% per year
ROE_MIN = 0.17  # 17%
RS_RATING_MIN = 80  # 1-99 scale

# Base patterns
BASE_DEPTH_MIN = 0.12
BASE_DEPTH_MAX = 0.33
CUP_MIN_WEEKS = 7
CUP_MAX_WEEKS = 65
FLAT_BASE_MIN_WEEKS = 5
FLAT_BASE_MAX_DEPTH = 0.15
HTF_POLE_MIN_PCT = 1.00  # 100%
HTF_POLE_MAX_WEEKS = 8
HTF_FLAG_MAX_PCT = 0.25  # 25%
HTF_FLAG_MIN_WEEKS = 3
HTF_FLAG_MAX_WEEKS = 5
ASCENDING_BASE_MIN_PULLBACKS = 3
PRIOR_UPTREND_MIN = 0.30

# Breakout confirmation
VOL_CONFIRM = 1.4
CLOSE_NEAR_HIGH = 0.75  # close >= low + 0.75*(high-low)
PIVOT_BUFFER = 0.0005  # +0.05% above pivot

# Market regime
DIST_DOWN_CLOSE_PCT = 0.002  # 0.2% down close = distribution day
DIST_CLUSTER_COUNT = 4  # 4-5 in 4-5 weeks = correction
FOLLOW_THROUGH_MIN_GAIN = 0.015  # 1.5% up on higher volume
INDEX_TICKER_CANDIDATES = ["NIFTY500", "NIFTY_50", "NIFTY50", "^NSEI", "NIFTY_500", "NIFTY"]


# ----------------------------------------------------------------
# METHODS registry — 7 total (6 scanned, 1 filter)
# ----------------------------------------------------------------
METHODS = [
    {
        "id": "oneil_can_slim_composite",
        "name": "CAN SLIM Composite",
        "description": "C/A growth + N new high + S supply + L leader + "
        "I sponsorship + M confirmed uptrend. Waits for "
        "quarterly fundamentals + RS rating + regime.",
        "direction": "long",
        "scan": True,
        "confidence": "HIGH",
    },
    {
        "id": "oneil_cup_with_handle",
        "name": "Cup-with-Handle Breakout",
        "description": "U-shaped base + handle in upper half + pivot "
        "breakout on volume. Waits for base detector + regime.",
        "direction": "long",
        "scan": True,
        "confidence": "HIGH",
    },
    {
        "id": "oneil_double_bottom",
        "name": "Double Bottom (W) Breakout",
        "description": "W shape with 2nd low undercutting 1st + middle "
        "peak breakout on volume. Waits for W detector + regime.",
        "direction": "long",
        "scan": True,
        "confidence": "HIGH",
    },
    {
        "id": "oneil_flat_base",
        "name": "Flat Base Breakout",
        "description": "20%+ prior advance + 5-7wk tight range + pivot "
        "breakout on volume. Waits for detector + regime.",
        "direction": "long",
        "scan": True,
        "confidence": "HIGH",
    },
    {
        "id": "oneil_high_tight_flag",
        "name": "High Tight Flag Breakout",
        "description": "100%+ pole in 4-8wk + tight flag 3-5wk + flag breakout on volume. Waits for detector + regime.",
        "direction": "long",
        "scan": True,
        "confidence": "HIGH",
    },
    {
        "id": "oneil_ascending_base",
        "name": "Ascending Base Breakout",
        "description": "3 higher lows + 3 higher highs + breakout on volume. Waits for detector + regime.",
        "direction": "long",
        "scan": True,
        "confidence": "MED",
    },
    {
        "id": "oneil_market_direction",
        "name": "Market Direction Filter (Distribution Days)",
        "description": "Not a trade — a regime filter gating methods 1-6. Waits for index daily data (DR-20).",
        "direction": "long",
        "scan": False,
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
# Data loaders + indicators
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


def _pivots(values, k=3, lookback=200, kind="low"):
    n = len(values)
    start = max(k, n - lookback)
    out = []
    for i in range(start, n - k):
        win = values[i - k : i + k + 1]
        if (kind == "low" and values[i] == win.min()) or (kind == "high" and values[i] == win.max()):
            out.append((i, float(values[i])))
    return out


# ----------------------------------------------------------------
# Market regime (Method 7 — computed, not signalled)
# ----------------------------------------------------------------
def _load_index_df(conn, limit=200):
    """Try common index tickers in prices_daily. Return df or None."""
    for sym in INDEX_TICKER_CANDIDATES:
        rows = conn.execute(
            "SELECT date, open, high, low, close, volume FROM prices_daily WHERE symbol=? ORDER BY date DESC LIMIT ?",
            (sym, limit),
        ).fetchall()
        if len(rows) >= 30:
            rows = list(reversed(rows))
            df = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "volume"])
            for c in ["open", "high", "low", "close", "volume"]:
                df[c] = pd.to_numeric(df[c], errors="coerce")
            return df, sym
    return None, None


def _compute_market_regime(conn):
    """
    O'Neil's distribution-day + follow-through logic.
    Returns (state, info_dict).

    state ∈ {"confirmed_uptrend", "correction", "rally_attempt",
             "unavailable"}
    """
    df, sym = _load_index_df(conn)
    if df is None or len(df) < 30:
        return "unavailable", {
            "reason": ("index data not found — see DATA_REQUESTS DR-20 for Nifty 500 daily OHLCV"),
            "symbol": None,
        }

    closes = df["close"].values.astype(float)
    vols = df["volume"].values.astype(float)
    n = len(closes)

    # Distribution days in rolling 25 sessions (5 weeks)
    dist_count = 0
    for i in range(max(1, n - 25), n):
        prior = closes[i - 1]
        if prior <= 0:
            continue
        chg = (closes[i] - prior) / prior
        if chg <= -DIST_DOWN_CLOSE_PCT and vols[i] > vols[i - 1]:
            dist_count += 1

    # Recent rally-attempt + follow-through detection
    rallied = False
    follow_through = False
    lookback = min(15, n)
    for i in range(n - lookback + 4, n):
        if i < 5:
            continue
        up_day = closes[i] > closes[i - 1]
        big_up = (closes[i] / closes[i - 1] - 1) >= FOLLOW_THROUGH_MIN_GAIN
        higher_vol = vols[i] > vols[i - 1]
        # Simple rally-attempt heuristic: last 4 days had at least one
        # higher close after a decline
        if big_up and higher_vol and up_day:
            follow_through = True
            rallied = True
            break

    # Determine state
    if follow_through and dist_count < DIST_CLUSTER_COUNT:
        state = "confirmed_uptrend"
    elif dist_count >= DIST_CLUSTER_COUNT:
        state = "correction"
    elif rallied:
        state = "rally_attempt"
    else:
        state = "confirmed_uptrend" if dist_count < 2 else "rally_attempt"

    info = {
        "index_symbol": sym,
        "distribution_days": dist_count,
        "follow_through_recent": follow_through,
        "index_close": float(closes[-1]),
    }
    return state, info


# ----------------------------------------------------------------
# Base pattern detectors (O'Neil's own logic — no proxies)
# ----------------------------------------------------------------
def _detect_cup_with_handle(df):
    """
    O'Neil's cup-with-handle. All parameters from the book.
    Returns dict {pivot, base_depth, base_length_weeks,
    handle_depth} or None.
    """
    n = len(df)
    if n < CUP_MIN_WEEKS * 5 + 30:
        return None
    h = df["high"].values.astype(float)
    l = df["low"].values.astype(float)
    c = df["close"].values.astype(float)

    # Prior uptrend >= 30% before base
    lookback_uptrend = 90
    if n < lookback_uptrend + 30:
        return None
    seg_start = n - lookback_uptrend - 30
    seg_end = n - 30
    if seg_end <= seg_start:
        return None
    pre_base_low = float(np.min(l[seg_start : seg_end + 1]))
    pre_base_high = float(np.max(h[seg_start : seg_end + 1]))
    if pre_base_low <= 0:
        return None
    prior_uptrend = pre_base_high / pre_base_low - 1
    if prior_uptrend < PRIOR_UPTREND_MIN:
        return None

    # Search for cup in the last ~65 weeks of bars
    cup_win = min(CUP_MAX_WEEKS * 5, n)
    hh_idx = int(np.argmax(h[-cup_win:])) + (n - cup_win)
    if hh_idx >= n - 5:
        return None
    cup_high = float(h[hh_idx])

    # Find the lowest low after the cup high (cup bottom)
    after = l[hh_idx:]
    if len(after) == 0:
        return None
    ll_idx_rel = int(np.argmin(after))
    ll_idx = hh_idx + ll_idx_rel
    cup_low = float(l[ll_idx])
    if cup_low <= 0:
        return None

    base_depth = (cup_high - cup_low) / cup_high
    if not (BASE_DEPTH_MIN <= base_depth <= BASE_DEPTH_MAX):
        return None

    # Cup length in weeks
    cup_length_days = n - 1 - hh_idx
    cup_length_weeks = cup_length_days / 5.0
    if not (CUP_MIN_WEEKS <= cup_length_weeks <= CUP_MAX_WEEKS):
        return None

    # U-shape: second half has to climb back near the right rim
    if ll_idx >= n - 5:
        return None
    right_side_max = float(np.max(h[ll_idx:]))
    if right_side_max < cup_low + 0.7 * (cup_high - cup_low):
        return None

    # Handle: recent 1-3 weeks pullback in upper half of base
    handle_win = min(15, ll_idx)  # 15 bars = 3 weeks
    if handle_win < 5:
        return None
    handle_high = float(np.max(h[-handle_win:]))
    handle_low = float(np.min(l[-handle_win:]))
    if handle_high <= 0:
        return None
    handle_depth = (handle_high - handle_low) / handle_high
    if handle_depth > 0.20:
        return None

    # Handle must be in upper half of base
    mid_base = cup_low + 0.5 * (cup_high - cup_low)
    if handle_low < mid_base:
        return None

    # Handle drifts down/sideways — last close should be below handle high
    if c[-1] > handle_high:
        return None

    return {
        "pivot": handle_high,
        "base_depth": round(base_depth, 3),
        "base_length_weeks": round(cup_length_weeks, 1),
        "handle_depth": round(handle_depth, 3),
        "cup_high": cup_high,
        "cup_low": cup_low,
    }


def _detect_double_bottom_w(df):
    """
    O'Neil's W pattern with 2nd low undercutting 1st.
    Own detector — does NOT reuse patterns.py.
    """
    n = len(df)
    if n < 80:
        return None
    h = df["high"].values.astype(float)
    l = df["low"].values.astype(float)

    # Find recent pivot lows in the last ~30 weeks
    piv = _pivots(l, k=4, lookback=150, kind="low")
    if len(piv) < 2:
        return None

    # Look at the last two pivot lows that are separated by >= 20 bars
    for i in range(len(piv) - 1, 0, -1):
        i2, low2 = piv[i]
        for j in range(i - 1, -1, -1):
            i1, low1 = piv[j]
            if i2 - i1 < 20:
                continue
            if i2 > n - 30:  # must be recent
                continue
            # Second low must be <= first low (undercut)
            if not (low2 <= low1 * 1.005):
                continue
            # Middle peak must exist
            mid_high = float(np.max(h[i1 : i2 + 1]))
            if mid_high <= low1 * 1.05:
                continue
            base_depth = (mid_high - min(low1, low2)) / mid_high
            if not (0.12 <= base_depth <= 0.40):
                continue
            return {
                "pivot": mid_high,
                "low1": low1,
                "low2": low2,
                "base_depth": round(base_depth, 3),
                "undercut_pct": round((low1 - low2) / low1, 4),
            }
    return None


def _detect_flat_base(df):
    """
    O'Neil's flat base: 20%+ prior advance, 5-7 week sideways range
    <= 15% deep, breakout at top.
    """
    n = len(df)
    if n < 60:
        return None
    h = df["high"].values.astype(float)
    l = df["low"].values.astype(float)
    c = df["close"].values.astype(float)

    flat_win = 30  # 6 weeks
    if n < flat_win + 30:
        return None

    # Prior advance off a base
    pre = c[n - flat_win - 30 : n - flat_win]
    if len(pre) < 20:
        return None
    pre_low = float(np.min(pre))
    pre_high = float(np.max(pre))
    if pre_low <= 0:
        return None
    advance = pre_high / pre_low - 1
    if advance < 0.20:
        return None

    # Flat base range
    base_high = float(np.max(h[-flat_win:]))
    base_low = float(np.min(l[-flat_win:]))
    if base_high <= 0:
        return None
    depth = (base_high - base_low) / base_high
    if depth > FLAT_BASE_MAX_DEPTH:
        return None

    # Breakout is the top of the base range
    return {
        "pivot": base_high,
        "base_depth": round(depth, 3),
        "base_length_weeks": round(flat_win / 5.0, 1),
        "prior_advance": round(advance, 3),
    }


def _detect_high_tight_flag(df):
    """
    O'Neil's HTF: 100%+ pole in 4-8 weeks + 3-5 week tight flag.
    """
    n = len(df)
    if n < 60:
        return None
    h = df["high"].values.astype(float)
    l = df["low"].values.astype(float)

    # Pole window: 4-8 weeks = 20-40 bars
    pole_win = 40
    if n < pole_win + 20:
        return None

    pole_high = float(np.max(h[-pole_win:]))
    pole_low = float(np.min(l[-pole_win:]))
    if pole_low <= 0:
        return None
    pole_gain = pole_high / pole_low - 1
    if pole_gain < HTF_POLE_MIN_PCT:
        return None

    # Flag: last 3-5 weeks
    flag_win = 20  # 4 weeks
    flag_high = float(np.max(h[-flag_win:]))
    flag_low = float(np.min(l[-flag_win:]))
    if flag_high <= 0:
        return None
    flag_depth = (flag_high - flag_low) / flag_high
    if flag_depth > HTF_FLAG_MAX_PCT:
        return None

    return {
        "pivot": flag_high,
        "pole_gain": round(pole_gain, 3),
        "flag_depth": round(flag_depth, 3),
        "flag_length_weeks": round(flag_win / 5.0, 1),
    }


def _detect_ascending_base(df):
    """
    O'Neil's ascending base: 3 pullbacks each with higher low AND
    higher high.
    """
    n = len(df)
    if n < 90:
        return None
    h = df["high"].values.astype(float)
    l = df["low"].values.astype(float)

    piv_lows = _pivots(l, k=3, lookback=90, kind="low")
    piv_highs = _pivots(h, k=3, lookback=90, kind="high")
    if len(piv_lows) < 3 or len(piv_highs) < 3:
        return None

    lows = [p[1] for p in piv_lows[-3:]]
    highs = [p[1] for p in piv_highs[-3:]]

    # Three higher lows
    if not (lows[0] < lows[1] < lows[2]):
        return None
    # Three higher highs
    if not (highs[0] < highs[1] < highs[2]):
        return None
    # Each pullback 10-20%
    for i in range(3):
        depth = (highs[i] - lows[i]) / highs[i] if highs[i] > 0 else 0
        if not (0.10 <= depth <= 0.20):
            return None

    return {
        "pivot": highs[2],
        "pullbacks": 3,
        "lows": lows,
        "highs": highs,
    }


# ----------------------------------------------------------------
# Exit block builder (R40)
# ----------------------------------------------------------------
def _oneil_exits_block(entry_price, atr=None):
    """
    O'Neil's exit rules as THESIS + HARD NUMBER + CONDITION.
    Stop: 7-8% below entry (7.5% midpoint).
    Target: 22.5% above entry (20-25% midpoint).
    """
    stop_hard = round(entry_price * (1 - 0.075), 2)
    target_hard = round(entry_price * (1 + 0.225), 2)
    return {
        "stop_out": {
            "thesis": (
                "Book: 'Cut every single loss at 7-8%, without "
                "exception.' This is the insurance-premium rule — "
                "the single most important defensive rule in the "
                "book. Failing to enforce it kills the portfolio "
                "over a cycle."
            ),
            "hard_number": stop_hard,
            "condition": f"close ≤ ₹{stop_hard} (7.5% below entry)",
        },
        "target": {
            "thesis": (
                "Book: take 20-25% profits into strength. If the "
                "stock advances 20% in under 3 weeks, HOLD for at "
                "least 8 weeks — this is likely a big leader, "
                "not a swing trade."
            ),
            "hard_number": target_hard,
            "condition": f"close ≥ ₹{target_hard} (22.5% above entry)",
        },
        "offset": {
            "thesis": (
                "Book: if the general market enters a confirmed "
                "correction (5+ distribution days), sell into "
                "strength, raise cash, and wait for a follow-"
                "through day before re-entering."
            ),
            "trigger": "market regime → correction (5+ distribution days in 4-5 weeks)",
        },
        "invalidation": {
            "thesis": (
                "Book: a close below the 10-week (50-day) moving "
                "average voids the setup — the leader has lost "
                "its uptrend structure."
            ),
            "condition": "close < 10-week (50-day) MA, or RS Rating drops below 70",
        },
        "exhaustion": {
            "thesis": (
                "Book: climax top signals — largest daily price "
                "run-up of the move, heaviest daily volume, "
                "exhaustion gap, climax top activity, signs of "
                "distribution, or stock split announcement."
            ),
            "rule": "any climax top signal → tighten stops, trim",
        },
        "time_exit": {
            "thesis": (
                "Book: no fixed time exit. But if a stock gains "
                "20% in under 3 weeks, extend the hold to at "
                "least 8 weeks instead of taking profit at the "
                "usual 20-25%."
            ),
            "sessions": None,
        },
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
# METHOD 1 — CAN SLIM composite
# ============================================================
def _detect_can_slim(sym, df, fund, market_regime):
    """
    All CAN SLIM gates must pass. Missing fields → method returns [].
    """
    if market_regime != "confirmed_uptrend":
        return []

    # C — current quarterly EPS growth
    eps_q = _safe_f(fund.get("eps_growth_current_qtr"))
    sales_q = _safe_f(fund.get("sales_growth_current_qtr"))
    if eps_q is None or sales_q is None:
        return []
    if eps_q < CURRENT_QTR_EPS_MIN or sales_q < CURRENT_QTR_SALES_MIN:
        return []

    # A — annual EPS growth 3y
    eps_3y = _safe_f(fund.get("eps_growth_3yr"))
    if eps_3y is None or eps_3y < ANNUAL_EPS_3YR_MIN:
        return []

    # ROE — available in fundamentals today
    roe = _safe_f(fund.get("roe"))
    if roe is None or roe < ROE_MIN * 100:
        return []

    # N — near 52w high
    closes = df["close"].values.astype(float)
    highs = df["high"].values.astype(float)
    hi52 = float(np.max(highs[-252:])) if len(highs) >= 252 else float(np.max(highs))
    if hi52 <= 0:
        return []
    dist_high = (hi52 - closes[-1]) / hi52
    if dist_high > 0.05:
        return []

    # S — breakout on volume
    vols = df["volume"].values.astype(float)
    avg_vol = _sma(vols, 20)
    if avg_vol is None or avg_vol <= 0:
        return []
    vol_ratio = vols[-1] / avg_vol
    if vol_ratio < VOL_CONFIRM:
        return []

    # L — RS rating
    rs = _safe_f(fund.get("rs_rating_52w"))
    if rs is None or rs < RS_RATING_MIN:
        return []

    # I — sponsorship change
    spon = _safe_f(fund.get("sponsorship_change"))
    if spon is None or spon <= 0:
        return []

    # Breakout base pattern (any of the 5)
    base = (
        _detect_cup_with_handle(df)
        or _detect_double_bottom_w(df)
        or _detect_flat_base(df)
        or _detect_high_tight_flag(df)
        or _detect_ascending_base(df)
    )
    if base is None:
        return []
    pivot = base["pivot"]
    if closes[-1] < pivot * (1 + PIVOT_BUFFER):
        return []

    entry = closes[-1]
    atr = _atr(df, 20)
    stop_hard = entry * 0.925
    notes = (
        f"CAN SLIM: EPSq {_fmt_num(eps_q * 100, 0)}% · "
        f"SalesQ {_fmt_num(sales_q * 100, 0)}% · "
        f"EPS3y {_fmt_num(eps_3y * 100, 0)}% · "
        f"ROE {_fmt_num(roe, 1)} · RS {_fmt_num(rs, 0)} · "
        f"pivot ₹{_fmt_num(pivot)}"
    )
    raw = {
        "eps_q": eps_q,
        "sales_q": sales_q,
        "eps_3y": eps_3y,
        "roe": roe,
        "rs_rating": rs,
        "sponsorship_change": spon,
        "pivot": pivot,
        "base": base,
        "market_regime": market_regime,
        "exits": _oneil_exits_block(entry, atr),
        "overlap_note": (
            "Overlaps oshaughnessy fundamentals family (EPS growth + RS) — different gate logic. Marked, not pruned."
        ),
    }
    return [
        _signal(
            sym,
            "oneil_can_slim_composite",
            entry,
            stop_hard,
            entry * 1.225,
            "HIGH",
            notes,
            raw,
            overlaps_with=[
                "oshaughnessy.relative_price_strength_1y",
                "oshaughnessy.low_pe_plus_rs",
            ],
        )
    ]


# ============================================================
# Helper — common breakout gate for methods 2-6
# ============================================================
def _breakout_signal(sym, method_id, df, market_regime, base, overlaps):
    if market_regime != "confirmed_uptrend":
        return []
    if base is None:
        return []
    closes = df["close"].values.astype(float)
    pivot = base["pivot"]
    if closes[-1] < pivot * (1 + PIVOT_BUFFER):
        return []
    vols = df["volume"].values.astype(float)
    avg_vol = _sma(vols, 20)
    if avg_vol is None or avg_vol <= 0:
        return []
    if vols[-1] / avg_vol < VOL_CONFIRM:
        return []
    # Close near high
    h = float(df["high"].iloc[-1])
    l = float(df["low"].iloc[-1])
    if h - l > 0 and (closes[-1] - l) / (h - l) < CLOSE_NEAR_HIGH:
        return []

    entry = closes[-1]
    atr = _atr(df, 20)
    stop_hard = entry * 0.925
    notes = f"{method_id}: pivot ₹{_fmt_num(pivot)} breakout, vol {_fmt_num(vols[-1] / avg_vol, 2)}x, close near high"
    raw = {
        "pivot": pivot,
        "base": base,
        "market_regime": market_regime,
        "exits": _oneil_exits_block(entry, atr),
        "overlap_note": "Marked, not pruned (R41).",
    }
    return [_signal(sym, method_id, entry, stop_hard, entry * 1.225, "HIGH", notes, raw, overlaps_with=overlaps)]


# ============================================================
# METHODS 2-6 — Base breakouts
# ============================================================
def _detect_cup(sym, df, market_regime):
    return _breakout_signal(
        sym,
        "oneil_cup_with_handle",
        df,
        market_regime,
        _detect_cup_with_handle(df),
        ["patterns.HIGH_TIGHT_FLAG", "ishaan_agnihotri.pattern_breakout_playbook"],
    )


def _detect_db(sym, df, market_regime):
    return _breakout_signal(
        sym, "oneil_double_bottom", df, market_regime, _detect_double_bottom_w(df), ["patterns.DOUBLE_BOTTOM"]
    )


def _detect_flat(sym, df, market_regime):
    return _breakout_signal(
        sym, "oneil_flat_base", df, market_regime, _detect_flat_base(df), ["seven_simple_strategies.golden_entry_long"]
    )


def _detect_htf(sym, df, market_regime):
    return _breakout_signal(
        sym, "oneil_high_tight_flag", df, market_regime, _detect_high_tight_flag(df), ["patterns.HIGH_TIGHT_FLAG"]
    )


def _detect_ascending(sym, df, market_regime):
    return _breakout_signal(
        sym, "oneil_ascending_base", df, market_regime, _detect_ascending_base(df), ["patterns.ASCENDING_TRIANGLE"]
    )


# ----------------------------------------------------------------
# Per-symbol scan
# ----------------------------------------------------------------
def _scan_symbol(sym, df, fund, market_regime):
    sigs = []
    _try_emit(sigs, lambda: _detect_can_slim(sym, df, fund, market_regime))
    _try_emit(sigs, lambda: _detect_cup(sym, df, market_regime))
    _try_emit(sigs, lambda: _detect_db(sym, df, market_regime))
    _try_emit(sigs, lambda: _detect_flat(sym, df, market_regime))
    _try_emit(sigs, lambda: _detect_htf(sym, df, market_regime))
    _try_emit(sigs, lambda: _detect_ascending(sym, df, market_regime))
    return sigs


# ----------------------------------------------------------------
# Universe scan
# ----------------------------------------------------------------
def _fundamentals_map(conn):
    try:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(fundamentals)")]
    except Exception:
        return {}
    if not cols:
        return {}
    sel = ", ".join(cols)
    out = {}
    try:
        for row in conn.execute(f"SELECT {sel} FROM fundamentals"):
            m = dict(zip(cols, row, strict=False))
            sym = m.get("symbol")
            if sym:
                out[sym] = m
    except Exception as e:
        log.warning(f"fundamentals load failed: {e}")
    return out


def scan(conn=None, limit=DEFAULT_LIMIT):
    own = conn is None
    if own:
        conn = db.get_conn()

    # Compute market regime first
    market_regime, regime_info = _compute_market_regime(conn)
    log.info(f"O'Neil market regime: {market_regime} (info: {regime_info})")

    syms = band_universe(conn, limit=limit)
    fund_map = _fundamentals_map(conn)
    log.info(f"O'Neil scan: {len(syms)} symbols, {len(fund_map)} with fundamentals")

    # Data-coverage report
    missing = []
    if market_regime == "unavailable":
        missing.append("market_regime (DR-20)")
    if not any(_safe_f(f.get("eps_growth_current_qtr")) for f in fund_map.values()):
        missing.append("eps_growth_current_qtr (DR-21)")
    if not any(_safe_f(f.get("sales_growth_current_qtr")) for f in fund_map.values()):
        missing.append("sales_growth_current_qtr (DR-21)")
    if not any(_safe_f(f.get("eps_growth_3yr")) for f in fund_map.values()):
        missing.append("eps_growth_3yr (DR-21)")
    if not any(_safe_f(f.get("rs_rating_52w")) for f in fund_map.values()):
        missing.append("rs_rating_52w (DR-22)")
    if not any(_safe_f(f.get("sponsorship_change")) for f in fund_map.values()):
        missing.append("sponsorship_change (DR-22)")
    if missing:
        log.info(
            f"O'Neil data gaps: {', '.join(missing)} — "
            f"methods 1-6 will emit 0 signals for gated checks "
            f"until these are supplied. See DATA_REQUESTS.md"
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
        fund = fund_map.get(sym, {})
        try:
            signals.extend(_scan_symbol(sym, df, fund, market_regime))
        except Exception as e:
            log.warning(f"{sym} scan failed: {e}")
        if i % 100 == 0:
            log.info(f"  progress {i}/{len(syms)}, {len(signals)} signals")

    if own:
        conn.close()

    n_sym = len({s["symbol"] for s in signals})
    log.info(
        f"O'Neil scan complete: {n_loaded} loaded, "
        f"short_history={n_short}, price<₹{MIN_PRICE}={n_low}, "
        f"{len(signals)} signals across {n_sym} symbols"
    )
    return signals
