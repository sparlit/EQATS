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
Curtis Faith — Way of the Turtle (2007).
Classified: MULTI (daily-bar trend following, multi-week/multi-month).

9 methods extracted per docs/BOOK_EXTRACTION_PROMPT.md.

The Turtle system is a mechanical, trend-following, volatility-normalized
breakout system. It expects most trades to lose and relies on a few large
winners. Everything here runs on price data only — no fundamental feeds
required. All 8 scanned methods run cleanly on prices_daily.

Design note (Turtle System 1):
  The book's skip rule ("if the last 20-day breakout in the same market
  was a winner, skip the next 20-day breakout") requires tracking trade
  outcomes across time. A stateless scan cannot observe that state.
  We take the aggressive variant — every 20-day breakout fires — and
  document it in the signal notes. The book itself offers System 2
  (55-day, no skip rule) as the simpler alternative.

Signal shape:
  entry = the breakout trigger price (this is setup identification, not
          trade management — the breakout level IS the setup)
  stop  = None (Turtle 2N stops are trade management, per R30 skip list)
  target = None

Direction: BULLISH for long breakouts, BEARISH for short breakouts.
For Indian cash equities only longs are actionable; short signals are
F&O-only and flagged as such in notes.
"""
import db
import numpy as np
import pandas as pd
from log_utils import get_logger
from universe_helper import band_universe

log = get_logger("trader.way_of_the_turtle")

SLUG = "way_of_the_turtle"
NAME = "Curtis Faith"
PILLAR = "multi"
SOURCE = "Way of the Turtle (2007)"


# ----------------------------------------------------------------
# Tunables — book-cited parameters
# ----------------------------------------------------------------
TICK = 0.05  # NSE minimum tick for liquid names
MIN_PRICE = 100  # penny-stock avoidance
MIN_BARS = 360  # enough history for 350-day MA
DEFAULT_LIMIT = 800

# Turtle channels
SYS1_BREAKOUT_DAYS = 20
SYS1_EXIT_DAYS = 10
SYS2_BREAKOUT_DAYS = 55
SYS2_EXIT_DAYS = 20

# ATR channel
ATR_CHANNEL_MA = 350
ATR_CHANNEL_TOP_MULT = 7.0
ATR_CHANNEL_BOTTOM_MULT = 3.0

# Bollinger breakout
BOLL_MA = 350
BOLL_STD_MULT = 2.5

# Donchian trend
DONCHIAN_FAST_EMA = 25
DONCHIAN_SLOW_EMA = 350
DONCHIAN_BREAKOUT_DAYS = 20

# Dual / Triple MA
DUAL_FAST = 100
DUAL_SLOW = 350
TRIPLE_FAST = 150
TRIPLE_MID = 250
TRIPLE_SLOW = 350

# Support/resistance
SR_PIVOT_K = 5
SR_LOOKBACK = 120
SR_TOLERANCE = 0.02  # two levels within 2% are "the same"
SR_BREAKOUT_BUFFER = 0.0005  # 0.05% beyond level = confirmed break


# ----------------------------------------------------------------
# METHODS registry — 9 total (8 scanned, 1 variant)
# ----------------------------------------------------------------
METHODS = [
    {
        "id": "turtle_system_1_20d",
        "name": "Turtle System 1 — 20-Day Breakout",
        "description": "20-day breakout. Skip rule omitted (stateless scan).",
        "direction": "both",
        "scan": True,
        "confidence": "HIGH",
    },
    {
        "id": "turtle_system_2_55d",
        "name": "Turtle System 2 — 55-Day Breakout",
        "description": "55-day breakout, always taken, no skip rule.",
        "direction": "both",
        "scan": True,
        "confidence": "HIGH",
    },
    {
        "id": "atr_channel_breakout",
        "name": "ATR Channel Breakout",
        "description": "350MA ± ATR band breakout.",
        "direction": "both",
        "scan": True,
        "confidence": "MED",
    },
    {
        "id": "bollinger_breakout",
        "name": "Bollinger Breakout",
        "description": "350MA ± 2.5σ band breakout.",
        "direction": "both",
        "scan": True,
        "confidence": "MED",
    },
    {
        "id": "donchian_trend",
        "name": "Donchian Trend",
        "description": "20-day breakout filtered by EMA25/EMA350 trend.",
        "direction": "both",
        "scan": True,
        "confidence": "HIGH",
    },
    {
        "id": "donchian_trend_time_exit",
        "name": "Donchian Trend (Time Exit)",
        "description": "Variant of Donchian Trend — identical entry, 80-day time exit.",
        "direction": "both",
        "scan": False,
        "confidence": "MED",
    },
    {
        "id": "dual_moving_average",
        "name": "Dual Moving Average",
        "description": "100MA / 350MA crossover.",
        "direction": "both",
        "scan": True,
        "confidence": "MED",
    },
    {
        "id": "triple_moving_average",
        "name": "Triple Moving Average",
        "description": "150/250/350 MA stacked cross.",
        "direction": "both",
        "scan": True,
        "confidence": "MED",
    },
    {
        "id": "support_resistance_breakdown",
        "name": "Support/Resistance Breakdown",
        "description": "Break of twice-tested S/R level.",
        "direction": "both",
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


def _atr(df, period=20):
    """Wilder-style ATR approximated as EMA of true range."""
    h = df["high"].values.astype(float)
    l = df["low"].values.astype(float)
    c = df["close"].values.astype(float)
    n = len(c)
    if n < period + 1:
        return np.array([])
    tr = np.zeros(n)
    tr[0] = h[0] - l[0]
    for i in range(1, n):
        tr[i] = max(
            h[i] - l[i],
            abs(h[i] - c[i - 1]),
            abs(l[i] - c[i - 1]),
        )
    # Exponential smoothing
    alpha = 2.0 / (period + 1)
    atr = np.zeros(n)
    atr[0] = tr[0]
    for i in range(1, n):
        atr[i] = alpha * tr[i] + (1 - alpha) * atr[i - 1]
    return atr


def _ema_series(arr, span):
    return pd.Series(arr).ewm(span=span, adjust=False).mean().values


def _sma_at(arr, i, period):
    if i + 1 < period:
        return None
    return float(np.mean(arr[i - period + 1 : i + 1]))


def _swing_levels(lows, highs, k=5, lookback=120):
    """
    Find the two most recent swing lows within SR_TOLERANCE of each other
    (support) and the two most recent swing highs within SR_TOLERANCE of
    each other (resistance). Returns (support_level, resistance_level).
    """
    n = len(lows)
    start = max(k, n - lookback)
    piv_lows, piv_highs = [], []
    for i in range(start, n - k):
        win_l = lows[i - k : i + k + 1]
        win_h = highs[i - k : i + k + 1]
        if lows[i] == win_l.min():
            piv_lows.append(float(lows[i]))
        if highs[i] == win_h.max():
            piv_highs.append(float(highs[i]))

    def _cluster(pivs):
        if len(pivs) < 2:
            return None
        # Take most recent pair within tolerance
        for a in range(len(pivs) - 1, 0, -1):
            for b in range(a - 1, -1, -1):
                avg = (pivs[a] + pivs[b]) / 2.0
                if avg <= 0:
                    continue
                if abs(pivs[a] - pivs[b]) / avg <= SR_TOLERANCE:
                    return avg
        return None

    support = _cluster(piv_lows)
    resistance = _cluster(piv_highs)
    return support, resistance


# ----------------------------------------------------------------
# Method detectors — each returns list of signals for this symbol
# ----------------------------------------------------------------
def _sig(sym, method_id, direction, entry, confidence, notes, raw):
    return {
        "symbol": sym,
        "trader": SLUG,
        "method": method_id,
        "direction": direction,
        "signal_type": "BREAKOUT",
        "entry": round(float(entry), 2) if entry is not None else None,
        "stop": None,
        "target": None,
        "confidence": confidence,
        "notes": notes,
        "raw": raw,
    }


def _detect_turtle_sys1(sym, df):
    """20-day breakout — fresh breakout only."""
    h = df["high"].values.astype(float)
    l = df["low"].values.astype(float)
    c = df["close"].values.astype(float)
    n = len(c)
    if n < SYS1_BREAKOUT_DAYS + 3:
        return []
    prior_high_20 = float(np.max(h[-SYS1_BREAKOUT_DAYS - 1 : -1]))
    prior_high_20_yest = float(np.max(h[-SYS1_BREAKOUT_DAYS - 2 : -2]))
    prior_low_20 = float(np.min(l[-SYS1_BREAKOUT_DAYS - 1 : -1]))
    prior_low_20_yest = float(np.min(l[-SYS1_BREAKOUT_DAYS - 2 : -2]))

    out = []
    # Long
    if c[-1] > prior_high_20 + TICK and c[-2] <= prior_high_20_yest + TICK:
        out.append(
            _sig(
                sym,
                "turtle_system_1_20d",
                "BULLISH",
                prior_high_20 + TICK,
                "HIGH",
                f"20d breakout long (skip rule omitted, aggressive variant) @ ₹{prior_high_20 + TICK:.2f}",
                {"breakout_level": prior_high_20, "skip_rule": "omitted"},
            )
        )
    # Short
    if c[-1] < prior_low_20 - TICK and c[-2] >= prior_low_20_yest - TICK:
        out.append(
            _sig(
                sym,
                "turtle_system_1_20d",
                "BEARISH",
                prior_low_20 - TICK,
                "HIGH",
                f"20d breakdown short (F&O only) @ ₹{prior_low_20 - TICK:.2f}",
                {"breakout_level": prior_low_20, "skip_rule": "omitted"},
            )
        )
    return out


def _detect_turtle_sys2(sym, df):
    """55-day breakout."""
    h = df["high"].values.astype(float)
    l = df["low"].values.astype(float)
    c = df["close"].values.astype(float)
    n = len(c)
    if n < SYS2_BREAKOUT_DAYS + 3:
        return []
    prior_high = float(np.max(h[-SYS2_BREAKOUT_DAYS - 1 : -1]))
    prior_high_yest = float(np.max(h[-SYS2_BREAKOUT_DAYS - 2 : -2]))
    prior_low = float(np.min(l[-SYS2_BREAKOUT_DAYS - 1 : -1]))
    prior_low_yest = float(np.min(l[-SYS2_BREAKOUT_DAYS - 2 : -2]))

    out = []
    if c[-1] > prior_high + TICK and c[-2] <= prior_high_yest + TICK:
        out.append(
            _sig(
                sym,
                "turtle_system_2_55d",
                "BULLISH",
                prior_high + TICK,
                "HIGH",
                f"55d breakout long @ ₹{prior_high + TICK:.2f}",
                {"breakout_level": prior_high},
            )
        )
    if c[-1] < prior_low - TICK and c[-2] >= prior_low_yest - TICK:
        out.append(
            _sig(
                sym,
                "turtle_system_2_55d",
                "BEARISH",
                prior_low - TICK,
                "HIGH",
                f"55d breakdown short (F&O only) @ ₹{prior_low - TICK:.2f}",
                {"breakout_level": prior_low},
            )
        )
    return out


def _detect_atr_channel(sym, df):
    """350MA ± ATR channel breakout."""
    c = df["close"].values.astype(float)
    n = len(c)
    if n < ATR_CHANNEL_MA + 3:
        return []
    atr = _atr(df, 20)
    if len(atr) < n or atr[-1] <= 0:
        return []
    ma = _sma_at(c, n - 1, ATR_CHANNEL_MA)
    if ma is None:
        return []
    top = ma + ATR_CHANNEL_TOP_MULT * atr[-1]
    bottom = ma - ATR_CHANNEL_BOTTOM_MULT * atr[-1]

    out = []
    if c[-1] > top and c[-2] <= top:
        out.append(
            _sig(
                sym,
                "atr_channel_breakout",
                "BULLISH",
                top,
                "MED",
                f"ATR channel top break @ ₹{top:.2f} (350MA {ma:.2f} + 7N {atr[-1]:.2f})",
                {"ma": ma, "atr": atr[-1], "channel_top": top},
            )
        )
    if c[-1] < bottom and c[-2] >= bottom:
        out.append(
            _sig(
                sym,
                "atr_channel_breakout",
                "BEARISH",
                bottom,
                "MED",
                f"ATR channel bottom break @ ₹{bottom:.2f}",
                {"ma": ma, "atr": atr[-1], "channel_bottom": bottom},
            )
        )
    return out


def _detect_bollinger_breakout(sym, df):
    """350MA ± 2.5σ channel breakout."""
    c = df["close"].values.astype(float)
    n = len(c)
    if n < BOLL_MA + 3:
        return []
    window = c[-BOLL_MA:]
    ma = float(np.mean(window))
    std = float(np.std(window))
    if std <= 0:
        return []
    top = ma + BOLL_STD_MULT * std
    bottom = ma - BOLL_STD_MULT * std

    out = []
    if c[-1] > top and c[-2] <= top:
        out.append(
            _sig(
                sym,
                "bollinger_breakout",
                "BULLISH",
                top,
                "MED",
                f"Bollinger upper break @ ₹{top:.2f} (350MA {ma:.2f} + 2.5σ {std:.2f})",
                {"ma": ma, "std": std, "channel_top": top},
            )
        )
    if c[-1] < bottom and c[-2] >= bottom:
        out.append(
            _sig(
                sym,
                "bollinger_breakout",
                "BEARISH",
                bottom,
                "MED",
                f"Bollinger lower break @ ₹{bottom:.2f}",
                {"ma": ma, "std": std, "channel_bottom": bottom},
            )
        )
    return out


def _detect_donchian_trend(sym, df):
    """20-day breakout filtered by EMA25 vs EMA350 trend."""
    h = df["high"].values.astype(float)
    l = df["low"].values.astype(float)
    c = df["close"].values.astype(float)
    n = len(c)
    if n < max(DONCHIAN_SLOW_EMA, DONCHIAN_BREAKOUT_DAYS) + 3:
        return []
    ema25 = _ema_series(c, DONCHIAN_FAST_EMA)
    ema350 = _ema_series(c, DONCHIAN_SLOW_EMA)
    if ema25[-1] == ema350[-1]:
        return []
    trend_up = ema25[-1] > ema350[-1]
    trend_down = ema25[-1] < ema350[-1]

    prior_high = float(np.max(h[-DONCHIAN_BREAKOUT_DAYS - 1 : -1]))
    prior_high_yest = float(np.max(h[-DONCHIAN_BREAKOUT_DAYS - 2 : -2]))
    prior_low = float(np.min(l[-DONCHIAN_BREAKOUT_DAYS - 1 : -1]))
    prior_low_yest = float(np.min(l[-DONCHIAN_BREAKOUT_DAYS - 2 : -2]))

    out = []
    if trend_up and c[-1] > prior_high + TICK and c[-2] <= prior_high_yest + TICK:
        out.append(
            _sig(
                sym,
                "donchian_trend",
                "BULLISH",
                prior_high + TICK,
                "HIGH",
                f"Donchian long @ ₹{prior_high + TICK:.2f} (EMA25 {ema25[-1]:.2f} > EMA350 {ema350[-1]:.2f})",
                {"breakout_level": prior_high, "ema25": float(ema25[-1]), "ema350": float(ema350[-1])},
            )
        )
    if trend_down and c[-1] < prior_low - TICK and c[-2] >= prior_low_yest - TICK:
        out.append(
            _sig(
                sym,
                "donchian_trend",
                "BEARISH",
                prior_low - TICK,
                "HIGH",
                f"Donchian short (F&O only) @ ₹{prior_low - TICK:.2f} "
                f"(EMA25 {ema25[-1]:.2f} < EMA350 {ema350[-1]:.2f})",
                {"breakout_level": prior_low, "ema25": float(ema25[-1]), "ema350": float(ema350[-1])},
            )
        )
    return out


def _detect_dual_ma(sym, df):
    """100MA / 350MA fresh cross."""
    c = df["close"].values.astype(float)
    n = len(c)
    if n < DUAL_SLOW + 3:
        return []
    f_now = _sma_at(c, n - 1, DUAL_FAST)
    s_now = _sma_at(c, n - 1, DUAL_SLOW)
    f_prev = _sma_at(c, n - 2, DUAL_FAST)
    s_prev = _sma_at(c, n - 2, DUAL_SLOW)
    if None in (f_now, s_now, f_prev, s_prev):
        return []
    out = []
    if f_prev <= s_prev and f_now > s_now:
        out.append(
            _sig(
                sym,
                "dual_moving_average",
                "BULLISH",
                c[-1],
                "MED",
                f"Dual MA bullish cross (100MA {f_now:.2f} > 350MA {s_now:.2f})",
                {"ma100": f_now, "ma350": s_now},
            )
        )
    if f_prev >= s_prev and f_now < s_now:
        out.append(
            _sig(
                sym,
                "dual_moving_average",
                "BEARISH",
                c[-1],
                "MED",
                f"Dual MA bearish cross (F&O only) (100MA {f_now:.2f} < 350MA {s_now:.2f})",
                {"ma100": f_now, "ma350": s_now},
            )
        )
    return out


def _detect_triple_ma(sym, df):
    """150/250/350 MA stacked cross."""
    c = df["close"].values.astype(float)
    n = len(c)
    if n < TRIPLE_SLOW + 3:
        return []
    f_now = _sma_at(c, n - 1, TRIPLE_FAST)
    m_now = _sma_at(c, n - 1, TRIPLE_MID)
    s_now = _sma_at(c, n - 1, TRIPLE_SLOW)
    f_prev = _sma_at(c, n - 2, TRIPLE_FAST)
    m_prev = _sma_at(c, n - 2, TRIPLE_MID)
    if None in (f_now, m_now, s_now, f_prev, m_prev):
        return []
    out = []
    if f_prev <= m_prev and f_now > m_now > s_now:
        out.append(
            _sig(
                sym,
                "triple_moving_average",
                "BULLISH",
                c[-1],
                "MED",
                f"Triple MA stack (150 {f_now:.2f} > 250 {m_now:.2f} > 350 {s_now:.2f})",
                {"ma150": f_now, "ma250": m_now, "ma350": s_now},
            )
        )
    if f_prev >= m_prev and f_now < m_now < s_now:
        out.append(
            _sig(
                sym,
                "triple_moving_average",
                "BEARISH",
                c[-1],
                "MED",
                "Triple MA inverse stack (F&O only)",
                {"ma150": f_now, "ma250": m_now, "ma350": s_now},
            )
        )
    return out


def _detect_support_resistance(sym, df):
    """Break of twice-tested S/R level."""
    h = df["high"].values.astype(float)
    l = df["low"].values.astype(float)
    c = df["close"].values.astype(float)
    n = len(c)
    if n < SR_LOOKBACK + SR_PIVOT_K + 3:
        return []
    support, resistance = _swing_levels(l, h, SR_PIVOT_K, SR_LOOKBACK)
    out = []
    buf = SR_BREAKOUT_BUFFER
    if resistance and c[-1] > resistance * (1 + buf) and c[-2] <= resistance:
        out.append(
            _sig(
                sym,
                "support_resistance_breakdown",
                "BULLISH",
                resistance * (1 + buf),
                "MED",
                f"Resistance break @ ₹{resistance:.2f} (twice-tested level)",
                {"level": resistance, "kind": "resistance"},
            )
        )
    if support and c[-1] < support * (1 - buf) and c[-2] >= support:
        out.append(
            _sig(
                sym,
                "support_resistance_breakdown",
                "BEARISH",
                support * (1 - buf),
                "MED",
                f"Support break (F&O only) @ ₹{support:.2f} (twice-tested level)",
                {"level": support, "kind": "support"},
            )
        )
    return out


# ----------------------------------------------------------------
# Per-symbol scan
# ----------------------------------------------------------------
def _scan_symbol(sym, df):
    sigs = []
    detectors = [
        _detect_turtle_sys1,
        _detect_turtle_sys2,
        _detect_atr_channel,
        _detect_bollinger_breakout,
        _detect_donchian_trend,
        _detect_dual_ma,
        _detect_triple_ma,
        _detect_support_resistance,
    ]
    for fn in detectors:
        try:
            sigs.extend(fn(sym, df))
        except Exception as e:
            log.warning(f"{sym} {fn.__name__} failed: {e}")
    return sigs


# ----------------------------------------------------------------
# Universe scan
# ----------------------------------------------------------------
def scan(conn=None, limit=800):
    own = conn is None
    if own:
        conn = db.get_conn()

    syms = band_universe(conn, limit=limit)
    log.info(f"Turtle scan: {len(syms)} symbols in universe")

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
        signals.extend(_scan_symbol(sym, df))
        if i % 100 == 0:
            log.info(f"  progress {i}/{len(syms)}, {len(signals)} signals")

    if own:
        conn.close()

    log.info(
        f"Turtle scan complete: {n_loaded} loaded, "
        f"skipped(short_history)={n_skipped_short}, "
        f"skipped(price<₹{MIN_PRICE})={n_skipped_price}, "
        f"{len(signals)} signals across "
        f"{len({s['symbol'] for s in signals})} symbols"
    )
    return signals
