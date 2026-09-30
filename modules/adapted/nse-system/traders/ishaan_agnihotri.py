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
Ishaan Agnihotri — A Technical Trader's Handbook.
Classified: SWING (positional for Method 4).
Long-only extraction — no intraday, no shorting.

5 methods extracted per docs/BOOK_EXTRACTION_PROMPT.md.
All price-only. Fully implementable today. No data blocks.

Bug-safety per R35:
  _fmt_num for null-safe notes, _try_emit per signal.
"""
import db
import numpy as np
import pandas as pd
from log_utils import get_logger
from universe_helper import band_universe

log = get_logger("trader.ishaan_agnihotri")

SLUG = "ishaan_agnihotri"
NAME = "Ishaan Agnihotri"
PILLAR = "swing"
SOURCE = "A Technical Trader's Handbook"


# ----------------------------------------------------------------
# Tunables
# ----------------------------------------------------------------
TICK = 0.05
MIN_PRICE = 100
MIN_BARS = 200
VOL_CONFIRM = 1.5
VOL_CONFIRM_WEAK = 1.2
EMA_FAST = 9
EMA_MID = 21
SMA_LONG = 180
SMA_MID = 50
SMA_SLOW = 200
RSI_PERIOD = 14
RSI_OVERSOLD = 30
PIVOT_K = 3
PIVOT_LOOKBACK = 120
TOUCH_TOL = 0.02


# ----------------------------------------------------------------
# Registry
# ----------------------------------------------------------------
METHODS = [
    {
        "id": "ema_reversal_playbook",
        "name": "EMA Reversal Playbook",
        "description": "Downtrend + close above 9 EMA + (RSI oversold OR MACD cross OR EMA9>EMA21) + retest holds.",
        "direction": "long",
        "scan": True,
        "confidence": "HIGH",
    },
    {
        "id": "pattern_breakout_playbook",
        "name": "Pattern Breakout Playbook",
        "description": "Any of: horizontal resistance, double bottom, inverse H&S — close above boundary + volume.",
        "direction": "long",
        "scan": True,
        "confidence": "HIGH",
    },
    {
        "id": "candlestick_reversal_at_support",
        "name": "Candlestick Reversal @ Support",
        "description": "Validated support + bullish reversal candle + volume.",
        "direction": "long",
        "scan": True,
        "confidence": "HIGH",
    },
    {
        "id": "trend_pullback_playbook",
        "name": "Trend Pullback Playbook",
        "description": "Uptrend + pullback to SMA180/broken resistance + bounce.",
        "direction": "long",
        "scan": True,
        "confidence": "HIGH",
    },
    {
        "id": "momentum_divergence_playbook",
        "name": "Momentum Divergence Playbook",
        "description": "Price lower low, RSI higher low + confirmation close.",
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


def _load_df(conn, sym, limit=400):
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


def _ema(arr, span):
    return pd.Series(arr).ewm(span=span, adjust=False).mean().values


def _sma_at(arr, period):
    if len(arr) < period:
        return None
    return float(np.mean(arr[-period:]))


def _rsi_series(closes, period=14):
    """Returns RSI array; None for first `period` entries."""
    n = len(closes)
    if n < period + 1:
        return None
    out = [None] * n
    gains = 0.0
    losses = 0.0
    for i in range(1, period + 1):
        ch = closes[i] - closes[i - 1]
        if ch > 0:
            gains += ch
        else:
            losses -= ch
    ag = gains / period
    al = losses / period
    out[period] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    for i in range(period + 1, n):
        ch = closes[i] - closes[i - 1]
        g = ch if ch > 0 else 0.0
        l = -ch if ch < 0 else 0.0
        ag = (ag * (period - 1) + g) / period
        al = (al * (period - 1) + l) / period
        out[i] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    return out


def _macd(closes, fast=12, slow=26, signal=9):
    """Returns (macd_line_array, signal_line_array)."""
    if len(closes) < slow + signal:
        return None, None
    ema_fast = _ema(closes, fast)
    ema_slow = _ema(closes, slow)
    macd = ema_fast - ema_slow
    sig = _ema(macd, signal)
    return macd, sig


def _pivots(values, k=PIVOT_K, lookback=PIVOT_LOOKBACK, kind="low"):
    """Return list of (index, value) pivots."""
    n = len(values)
    start = max(k, n - lookback)
    out = []
    for i in range(start, n - k):
        win = values[i - k : i + k + 1]
        if (kind == "low" and values[i] == win.min()) or (kind == "high" and values[i] == win.max()):
            out.append((i, float(values[i])))
    return out


def _is_bullish(df, i):
    return float(df["close"].iloc[i]) > float(df["open"].iloc[i])


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


def _is_hammer(s):
    if s is None:
        return False
    if s["body"] < 1e-6:
        return s["lower"] >= 0.6 * s["rng"] and s["upper"] <= 0.2 * s["rng"] and s["close_pos"] >= 0.6
    return s["lower"] >= 2.0 * s["body"] and s["upper"] <= 0.3 * s["body"] and s["close_pos"] >= 0.6


def _is_dragonfly_doji(s):
    if s is None:
        return False
    return s["body"] <= 0.15 * s["rng"] and s["lower"] >= 0.6 * s["rng"] and s["upper"] <= 0.1 * s["rng"]


def _is_long_legged_doji(s):
    if s is None:
        return False
    return s["body"] <= 0.15 * s["rng"] and s["lower"] >= 0.35 * s["rng"] and s["upper"] >= 0.35 * s["rng"]


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


def _support_level(df, atr):
    """Find a support level from ≥2 clustered pivot lows.
    Returns (level, touches) or None."""
    lows = df["low"].values.astype(float)
    piv = _pivots(lows, k=PIVOT_K, lookback=PIVOT_LOOKBACK, kind="low")
    if len(piv) < 2:
        return None
    # Greedy cluster: walk pivots, count touches within TOUCH_TOL of median
    best = None
    for i in range(len(piv)):
        group = [piv[i]]
        for j in range(i + 1, len(piv)):
            ref = np.median([g[1] for g in group])
            if ref <= 0:
                continue
            if abs(piv[j][1] - ref) / ref <= TOUCH_TOL:
                group.append(piv[j])
        if len(group) >= 2:
            level = float(np.median([g[1] for g in group]))
            if best is None or len(group) > best[1]:
                best = (level, len(group))
    return best


def _resistance_level(df):
    highs = df["high"].values.astype(float)
    piv = _pivots(highs, k=PIVOT_K, lookback=PIVOT_LOOKBACK, kind="high")
    if len(piv) < 2:
        return None
    best = None
    for i in range(len(piv)):
        group = [piv[i]]
        for j in range(i + 1, len(piv)):
            ref = np.median([g[1] for g in group])
            if ref <= 0:
                continue
            if abs(piv[j][1] - ref) / ref <= TOUCH_TOL:
                group.append(piv[j])
        if len(group) >= 2:
            level = float(np.median([g[1] for g in group]))
            if best is None or len(group) > best[1]:
                best = (level, len(group))
    return best


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


def _detect_ema_reversal(sym, df, atr, vol_ratio):
    closes = df["close"].values.astype(float)
    n = len(closes)
    if n < 30:
        return []
    ema9 = _ema(closes, EMA_FAST)
    ema21 = _ema(closes, EMA_MID)
    rsi = _rsi_series(closes, RSI_PERIOD)
    macd, macd_sig = _macd(closes)

    # Group A: prior 5 sessions close below EMA9, today close > EMA9
    if n < 7:
        return []
    below_count = sum(1 for i in range(n - 6, n - 1) if closes[i] < ema9[i])
    if below_count < 5:
        return []
    if not (closes[-1] > ema9[-1] and closes[-2] <= ema9[-2]):
        return []
    if vol_ratio is None or vol_ratio < 1.0:
        return []

    # Group B: at least 1 of 3
    rsi_ok = rsi is not None and rsi[-1] is not None and rsi[-1] <= RSI_OVERSOLD
    macd_ok = False
    if macd is not None and macd_sig is not None:
        if macd[-1] > macd_sig[-1] and macd[-2] <= macd_sig[-2]:
            macd_ok = True
    ema_cross_ok = ema9[-1] > ema21[-1] and ema9[-2] <= ema21[-2]
    if not (rsi_ok or macd_ok or ema_cross_ok):
        return []

    conf_bits = []
    if rsi_ok:
        conf_bits.append(f"RSI {_fmt_num(rsi[-1], 1)}")
    if macd_ok:
        conf_bits.append("MACD cross-up")
    if ema_cross_ok:
        conf_bits.append("EMA9/EMA21 cross-up")

    return [
        _sig(
            sym,
            "ema_reversal_playbook",
            closes[-1],
            "HIGH",
            f"EMA reversal: {below_count} bars below 9EMA, break + {', '.join(conf_bits)}",
            {
                "close": float(closes[-1]),
                "ema9": float(ema9[-1]),
                "rsi": _safe_f(rsi[-1]) if rsi else None,
                "conf": conf_bits,
            },
        )
    ]


def _detect_pattern_breakout(sym, df, atr, vol_ratio):
    if vol_ratio is None or vol_ratio < VOL_CONFIRM:
        return []
    h = df["high"].values.astype(float)
    df["low"].values.astype(float)
    c = df["close"].values.astype(float)
    n = len(c)
    if n < 60:
        return []

    # --- horizontal resistance breakout ---
    res = _resistance_level(df)
    if res is not None:
        level, touches = res
        if c[-1] > level + TICK and c[-2] <= level + TICK:
            return [
                _sig(
                    sym,
                    "pattern_breakout_playbook",
                    c[-1],
                    "HIGH",
                    f"Resistance breakout above ₹{_fmt_num(level)} ({touches} touches), vol {_fmt_num(vol_ratio, 2)}x",
                    {"pattern": "horizontal_resistance", "level": level, "touches": touches, "vol_ratio": vol_ratio},
                )
            ]

    # --- double bottom ---
    lows = df["low"].values.astype(float)
    piv_lows = _pivots(lows, k=PIVOT_K, lookback=PIVOT_LOOKBACK, kind="low")
    if len(piv_lows) >= 2:
        # last two pivots, similar (within 3%)
        (i1, v1), (i2, v2) = piv_lows[-2], piv_lows[-1]
        if i2 - i1 >= 10:
            avg = (v1 + v2) / 2
            if avg > 0 and abs(v1 - v2) / avg <= 0.03:
                # neckline = max high between the two lows
                mid_high = float(np.max(h[i1 : i2 + 1]))
                if c[-1] > mid_high + TICK and c[-2] <= mid_high + TICK:
                    return [
                        _sig(
                            sym,
                            "pattern_breakout_playbook",
                            c[-1],
                            "HIGH",
                            f"Double bottom breakout above neckline "
                            f"₹{_fmt_num(mid_high)}, vol "
                            f"{_fmt_num(vol_ratio, 2)}x",
                            {
                                "pattern": "double_bottom",
                                "neckline": mid_high,
                                "low1": v1,
                                "low2": v2,
                                "vol_ratio": vol_ratio,
                            },
                        )
                    ]

    # --- inverse H&S ---
    if len(piv_lows) >= 3:
        ls, head, rs = piv_lows[-3], piv_lows[-2], piv_lows[-1]
        if ls[0] < head[0] < rs[0]:
            # head must be lower than both shoulders
            if head[1] < ls[1] and head[1] < rs[1]:
                sh_avg = (ls[1] + rs[1]) / 2
                if sh_avg > 0 and abs(ls[1] - rs[1]) / sh_avg <= 0.05:
                    neck_l = float(np.max(h[ls[0] : head[0] + 1]))
                    neck_r = float(np.max(h[head[0] : rs[0] + 1]))
                    neckline = (neck_l + neck_r) / 2
                    if c[-1] > neckline + TICK and c[-2] <= neckline + TICK:
                        return [
                            _sig(
                                sym,
                                "pattern_breakout_playbook",
                                c[-1],
                                "HIGH",
                                f"Inverse H&S breakout above neckline "
                                f"₹{_fmt_num(neckline)}, vol "
                                f"{_fmt_num(vol_ratio, 2)}x",
                                {"pattern": "inverse_head_shoulders", "neckline": neckline, "vol_ratio": vol_ratio},
                            )
                        ]

    return []


def _detect_candlestick_reversal(sym, df, atr, vol_ratio):
    """At a validated support level + bullish reversal candle."""
    if len(df) < 60:
        return []
    if vol_ratio is None or vol_ratio < VOL_CONFIRM_WEAK:
        return []
    support = _support_level(df, atr)
    rsi = _rsi_series(df["close"].values.astype(float), RSI_PERIOD)
    rsi_oversold = rsi is not None and rsi[-1] is not None and rsi[-1] <= RSI_OVERSOLD

    close_now = float(df["close"].iloc[-1])
    low_now = float(df["low"].iloc[-1])
    near_support = False
    support_level = None
    if support is not None:
        support_level, _touches = support
        if support_level > 0 and abs(low_now - support_level) / support_level <= 0.03:
            near_support = True

    if not (near_support or rsi_oversold):
        return []

    cur = _candle_shape(df, len(df) - 1)
    if cur is None or not cur["is_bull"]:
        return []
    reversal_kind = None
    if _is_bullish_engulfing(df, len(df) - 1):
        reversal_kind = "bullish_engulfing"
    elif _is_hammer(cur):
        reversal_kind = "hammer"
    elif _is_dragonfly_doji(cur):
        reversal_kind = "dragonfly_doji"
    elif _is_long_legged_doji(cur):
        reversal_kind = "long_legged_doji"
    if reversal_kind is None:
        return []

    # confirmation: close above reversal candle's high OR above EMA9
    ema9 = _ema(df["close"].values.astype(float), EMA_FAST)[-1]
    confirm = (close_now > cur["high"] * (1 - 0.005)) or (close_now > ema9)
    if not confirm:
        return []

    return [
        _sig(
            sym,
            "candlestick_reversal_at_support",
            close_now,
            "HIGH",
            f"{reversal_kind} at support "
            f"{('₹' + _fmt_num(support_level)) if support_level else '(RSI oversold)'}"
            f", vol {_fmt_num(vol_ratio, 2)}x",
            {
                "reversal": reversal_kind,
                "support_level": support_level,
                "rsi_oversold": rsi_oversold,
                "vol_ratio": vol_ratio,
            },
        )
    ]


def _detect_trend_pullback(sym, df, atr, vol_ratio):
    """Uptrend + pullback to SMA180/broken resistance + bullish bounce."""
    closes = df["close"].values.astype(float)
    n = len(closes)
    if n < SMA_LONG + 5:
        return []
    sma180 = _sma_at(closes, SMA_LONG)
    sma50 = _sma_at(closes, SMA_MID)
    sma200 = _sma_at(closes, SMA_SLOW)
    if sma180 is None:
        return []
    close = closes[-1]

    # Uptrend context — either SMA180 uptrend OR 50>200 stack
    sma180_prev = _sma_at(closes[:-10], SMA_LONG)
    trend_ok = False
    if (sma180_prev is not None and sma180 > sma180_prev and close > sma180) or (
        sma50 is not None and sma200 is not None and sma50 > sma200 and close > sma50
    ):
        trend_ok = True
    if not trend_ok:
        return []

    # Pullback: close within 5% of SMA180 OR near a broken resistance
    pullback = False
    if sma180 > 0 and abs(close - sma180) / sma180 <= 0.05:
        pullback = True
    # broken resistance acts as support
    if not pullback:
        res = _resistance_level(df)
        if res is not None:
            level, _ = res
            if level > 0 and 0 <= (close - level) / level <= 0.03:
                pullback = True
    if not pullback:
        return []

    # Bounce: bullish candle
    if not _is_bullish(df, n - 1):
        return []
    if vol_ratio is not None and vol_ratio < 1.0:
        return []

    return [
        _sig(
            sym,
            "trend_pullback_playbook",
            close,
            "HIGH",
            f"Trend pullback: close ₹{_fmt_num(close)} near SMA180 ₹{_fmt_num(sma180)}, bullish bounce",
            {"close": float(close), "sma180": sma180, "sma50": sma50, "vol_ratio": vol_ratio},
        )
    ]


def _detect_momentum_divergence(sym, df, atr, vol_ratio):
    """Price lower low + RSI higher low + break above 9 EMA."""
    closes = df["close"].values.astype(float)
    n = len(closes)
    if n < 40:
        return []
    rsi = _rsi_series(closes, RSI_PERIOD)
    if rsi is None:
        return []
    lows = df["low"].values.astype(float)
    piv = _pivots(lows, k=PIVOT_K, lookback=90, kind="low")
    if len(piv) < 2:
        return []
    (i1, p1), (i2, p2) = piv[-2], piv[-1]
    if i2 <= i1 or rsi[i1] is None or rsi[i2] is None:
        return []
    # price lower low, RSI higher low
    if not (p2 < p1 and rsi[i2] > rsi[i1]):
        return []
    # confirmation: close above EMA9
    ema9 = _ema(closes, EMA_FAST)[-1]
    if closes[-1] <= ema9:
        return []
    return [
        _sig(
            sym,
            "momentum_divergence_playbook",
            closes[-1],
            "MED",
            f"Bullish RSI divergence: price {_fmt_num(p1)}→{_fmt_num(p2)}, "
            f"RSI {_fmt_num(rsi[i1], 1)}→{_fmt_num(rsi[i2], 1)}, "
            f"confirmed above 9EMA",
            {
                "price_low_prev": p1,
                "price_low_curr": p2,
                "rsi_prev": _safe_f(rsi[i1]),
                "rsi_curr": _safe_f(rsi[i2]),
                "vol_ratio": vol_ratio,
            },
        )
    ]


# ----------------------------------------------------------------
# Per-symbol scan
# ----------------------------------------------------------------
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


def _scan_symbol(sym, df):
    atr = _atr(df, 14)
    vols = df["volume"].values.astype(float)
    vol_ratio = None
    if len(vols) >= 20:
        avg = float(np.mean(vols[-20:]))
        if avg > 0:
            vol_ratio = float(vols[-1]) / avg

    sigs = []
    _try_emit(sigs, lambda: _detect_ema_reversal(sym, df, atr, vol_ratio))
    _try_emit(sigs, lambda: _detect_pattern_breakout(sym, df, atr, vol_ratio))
    _try_emit(sigs, lambda: _detect_candlestick_reversal(sym, df, atr, vol_ratio))
    _try_emit(sigs, lambda: _detect_trend_pullback(sym, df, atr, vol_ratio))
    _try_emit(sigs, lambda: _detect_momentum_divergence(sym, df, atr, vol_ratio))
    return sigs


# ----------------------------------------------------------------
# Universe scan
# ----------------------------------------------------------------
def scan(conn=None, limit=800):
    own = conn is None
    if own:
        conn = db.get_conn()
    syms = band_universe(conn, limit=limit)
    log.info(f"Ishaan scan: {len(syms)} symbols in universe")

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
    log.info(
        f"Ishaan scan complete: {n_loaded} loaded, "
        f"short_history={n_short_hist}, "
        f"price<₹{MIN_PRICE}={n_low_price}, "
        f"{len(signals)} signals across "
        f"{len({s['symbol'] for s in signals})} symbols"
    )
    return signals
