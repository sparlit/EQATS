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


"""Shared scan selection and calculation utilities for trader modules."""
import datetime as dt


def select_scan_symbols(conn, limit, symbols=None):
    from universe_helper import band_universe

    universe = band_universe(conn, limit=limit)
    if symbols is None:
        return universe
    if isinstance(symbols, str):
        symbols = [symbols]
    requested = {str(symbol).strip().upper() for symbol in symbols if str(symbol).strip()}
    return [symbol for symbol in universe if symbol in requested]


# ============================================================
# Tick sizes (NSE rolling)
# ============================================================
def tick_size(price):
    if price is None or price <= 0:
        return 0.05
    if price < 100:
        return 0.05
    if price < 500:
        return 0.05
    if price < 1000:
        return 0.10
    if price < 5000:
        return 0.50
    return 1.00


def ticks(n, price):
    return n * tick_size(price)


# ============================================================
# Candles
# ============================================================
def is_bearish(bar):
    return bar["Close"] < bar["Open"]


def is_bullish(bar):
    return bar["Close"] > bar["Open"]


# ============================================================
# Pivots (purely on closes, or on highs/lows)
# ============================================================
def find_pivot_lows(values, k=5):
    """Local minima — value[i] is strictly lower than surrounding k bars
    on each side (with at least one strict side)."""
    out = []
    n = len(values)
    for i in range(k, n - k):
        win = values[i - k : i + k + 1]
        if values[i] == min(win):
            out.append({"index": i, "value": float(values[i])})
    return out


def find_pivot_highs(values, k=5):
    out = []
    n = len(values)
    for i in range(k, n - k):
        win = values[i - k : i + k + 1]
        if values[i] == max(win):
            out.append({"index": i, "value": float(values[i])})
    return out


# ============================================================
# Market holiday accounting (Crane's calendar law)
# Weekday gaps between two trading dates = holidays.
# ============================================================
def count_weekday_holidays(date1_iso, date2_iso):
    """
    Count weekday (Mon-Fri) dates strictly between two ISO dates.
    These are the market holidays to be included in Reverse/Forward counts.
    """
    try:
        d1 = dt.date.fromisoformat(str(date1_iso)[:10])
        d2 = dt.date.fromisoformat(str(date2_iso)[:10])
    except Exception:
        return 0
    if d2 <= d1:
        return 0
    count = 0
    cur = d1 + dt.timedelta(days=1)
    while cur < d2:
        if cur.weekday() < 5:  # Mon-Fri
            count += 1
        cur = cur + dt.timedelta(days=1)
    return count


# ============================================================
# Trendline helpers
# ============================================================
def line_through(p1, p2):
    """Given two (x, y) points, return (slope, intercept)."""
    x1, y1 = p1
    x2, y2 = p2
    if x2 == x1:
        return None, None
    m = (y2 - y1) / (x2 - x1)
    b = y1 - m * x1
    return m, b


def value_at(m, b, x):
    if m is None:
        return None
    return m * x + b


def check_trendline_break_lows(highs, lows, closes, start_idx, end_idx):
    """
    Return True if the support trendline formed by the lowest points
    in [start_idx, end_idx] has been broken downward by any close after
    end_idx.
    """
    if end_idx <= start_idx:
        return False
    # Find two lowest lows in range
    seg = lows[start_idx : end_idx + 1]
    idx_sorted = sorted(range(len(seg)), key=lambda i: seg[i])
    if len(idx_sorted) < 2:
        return False
    i1, i2 = sorted(idx_sorted[:2])
    p1 = (start_idx + i1, float(lows[start_idx + i1]))
    p2 = (start_idx + i2, float(lows[start_idx + i2]))
    m, b = line_through(p1, p2)
    if m is None:
        return False
    for j in range(end_idx + 1, len(closes)):
        line_val = value_at(m, b, j)
        if line_val is not None and closes[j] < line_val:
            return True
    return False


def check_trendline_break_highs(highs, lows, closes, start_idx, end_idx):
    if end_idx <= start_idx:
        return False
    seg = highs[start_idx : end_idx + 1]
    idx_sorted = sorted(range(len(seg)), key=lambda i: -seg[i])
    if len(idx_sorted) < 2:
        return False
    i1, i2 = sorted(idx_sorted[:2])
    p1 = (start_idx + i1, float(highs[start_idx + i1]))
    p2 = (start_idx + i2, float(highs[start_idx + i2]))
    m, b = line_through(p1, p2)
    if m is None:
        return False
    for j in range(end_idx + 1, len(closes)):
        line_val = value_at(m, b, j)
        if line_val is not None and closes[j] > line_val:
            return True
    return False


# ============================================================
# SSTO — Slow Stochastic (20-period)
# ============================================================
def ssto_k(closes, highs, lows, period=20, smooth=3):
    """
    %K smoothed by `smooth` on a 20-period lookback.
    Returns list aligned with input (NaN for first period-1 bars).
    """
    n = len(closes)
    out = [None] * n
    for i in range(period - 1, n):
        hh = max(highs[i - period + 1 : i + 1])
        ll = min(lows[i - period + 1 : i + 1])
        if hh == ll:
            out[i] = 50.0
        else:
            out[i] = 100.0 * (closes[i] - ll) / (hh - ll)
    # Smooth
    smoothed = [None] * n
    for i in range(n):
        seg = [v for v in out[max(0, i - smooth + 1) : i + 1] if v is not None]
        if len(seg) == smooth:
            smoothed[i] = sum(seg) / smooth
    return smoothed


# ============================================================
# Bars ↔ dict helpers
# ============================================================
def bars_to_dicts(df):
    """
    df: pandas DataFrame with Open/High/Low/Close/Volume columns,
        indexed by date (string or timestamp).
    Returns: list of dicts with integer index + date + OHLCV.
    """
    # v2 (2026-09-25): column-wise instead of df.iterrows() — same output,
    # ~20x faster. Matters for the Trader League replay, which calls
    # John Crane's scanner once per stock per historical day.
    n = len(df)
    if n == 0:
        return []
    dates = [str(x)[:10] for x in df.index]
    o = df["Open"].astype(float).tolist()
    h = df["High"].astype(float).tolist()
    lo = df["Low"].astype(float).tolist()
    c = df["Close"].astype(float).tolist()
    v = df["Volume"].astype(float).tolist() if "Volume" in df.columns else [0.0] * n
    return [
        {
            "index": i,
            "date": dates[i],
            "Open": o[i],
            "High": h[i],
            "Low": lo[i],
            "Close": c[i],
            "Volume": v[i],
        }
        for i in range(n)
    ]
