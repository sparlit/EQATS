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
Larry Spears — swing-trading setup identification.
Classified: SWING.

Setup filter set:
  beta_filter            — symbol beta ≥ 1.30 vs ^NSEI
  amplitude_filter       — 5-day high-low range ≥ 5% of price
  gap_classification     — open ≥ 0.5% from prior close
  ma_trend               — SMA10/20/50 stacking with slopes
  counter_trend          — 2-3 consecutive lower highs / higher lows
  force_index            — 13-period ≥0 / 3-period ≤0 (long); reverse for short
  setup                  — composite of the above

Excluded (per owner request): entry stops, position sizing, protective
stops, trailing, 5-day invalidation roll-forward, target tranches.
"""
import db
import numpy as np
import pandas as pd
from log_utils import get_logger
from traders import base as B
from universe_helper import band_universe

log = get_logger("trader.larry_spears")

SLUG = "larry_spears"
NAME = "Larry Spears"
PILLAR = "swing"
SOURCE = "Swing-trading methodology (high-volatility swing setups)"

METHODS = [
    {
        "id": "beta_filter",
        "name": "Beta ≥ 1.30",
        "description": "Symbol must be ≥ 30% more volatile than Nifty 50.",
        "direction": "both",
    },
    {
        "id": "amplitude_filter",
        "name": "Amplitude ≥ 5%",
        "description": "5-day high-low range must be ≥ 5% of price.",
        "direction": "both",
    },
    {
        "id": "gap_classification",
        "name": "Gap Classification",
        "description": "Open ≥0.5% from prior close classifies a gap session.",
        "direction": "both",
    },
    {
        "id": "ma_trend",
        "name": "MA Trend Alignment",
        "description": "Close + SMA10/20/50 stacked correctly, slopes agree.",
        "direction": "both",
    },
    {
        "id": "counter_trend",
        "name": "Counter-Trend Retracement",
        "description": "2-3 consecutive lower highs (long) / higher lows (short).",
        "direction": "both",
    },
    {
        "id": "force_index",
        "name": "Force Index Filter",
        "description": "FI13 ≥0 and FI3 ≤0 (long); FI13 ≤0 and FI3 ≥0 (short).",
        "direction": "both",
    },
    {
        "id": "setup",
        "name": "Composite Swing Setup",
        "description": "All filters aligned → actionable setup.",
        "direction": "both",
    },
]

# Tunables
BETA_MIN = 1.30
AMPLITUDE_MIN = 0.05  # 5%
AMPLITUDE_MAX = 0.20  # sanity cap; reject absurd outliers
GAP_THRESHOLD = 0.005  # 0.5%
LOOKBACK_DAYS = 60
MAX_CONSOLIDATION_DAYS = 5
MIN_CONSOLIDATION_DAYS = 2


# ============================================================
# Benchmarks — fetch Nifty 50 returns once per scan
# ============================================================
_BENCH_CACHE = None


def _fetch_benchmark_returns(years=2):
    global _BENCH_CACHE
    if _BENCH_CACHE is not None:
        return _BENCH_CACHE
    try:
        import yfinance as yf

        df = yf.Ticker("^NSEI").history(period=f"{years}y", auto_adjust=True)
        if df is None or len(df) < 200:
            _BENCH_CACHE = pd.Series(dtype=float)
            return _BENCH_CACHE
        _BENCH_CACHE = df["Close"].pct_change().dropna()
    except Exception as e:
        log.warning(f"benchmark fetch failed: {e}")
        _BENCH_CACHE = pd.Series(dtype=float)
    return _BENCH_CACHE


# ============================================================
# Individual filters
# ============================================================
def _beta(sym_closes, bench_returns):
    s_rets = pd.Series(sym_closes).pct_change().dropna()
    if len(s_rets) < 60 or len(bench_returns) < 60:
        return None
    n = min(len(s_rets), len(bench_returns), LOOKBACK_DAYS * 3)
    s = s_rets.iloc[-n:].values.astype(float)
    m = bench_returns.iloc[-n:].values.astype(float)
    if np.var(m) == 0:
        return None
    return float(np.cov(s, m)[0][1] / np.var(m))


def _amplitude(df, lookback=5):
    if len(df) < lookback:
        return None
    seg = df.tail(lookback)
    hi = float(seg["High"].max())
    lo = float(seg["Low"].min())
    avg_close = float(seg["Close"].mean())
    if avg_close <= 0:
        return None
    return (hi - lo) / avg_close


def _gap_pct(today_open, prior_close):
    if not prior_close:
        return None
    return (today_open - prior_close) / prior_close


# ============================================================
# Trend & slopes
# ============================================================
def _sma(values, period):
    if len(values) < period:
        return None
    return float(np.mean(values[-period:]))


def _sma_series(values, period, n_points=6):
    """
    Return last `n_points` of rolling SMA values.
    Ordered oldest → newest.
    """
    out = []
    for i in range(n_points - 1, -1, -1):
        end = len(values) - i
        if end < period:
            out.append(None)
            continue
        seg = values[end - period : end]
        out.append(float(np.mean(seg)))
    return out


def _strictly_increasing(series):
    """True if every consecutive pair is non-None and strictly rising."""
    if not series or len(series) < 2:
        return False
    for i in range(len(series) - 1):
        a = series[i]
        b = series[i + 1]
        if a is None or b is None:
            return False
        if not (a < b):
            return False
    return True


def _strictly_decreasing(series):
    if not series or len(series) < 2:
        return False
    for i in range(len(series) - 1):
        a = series[i]
        b = series[i + 1]
        if a is None or b is None:
            return False
        if not (a > b):
            return False
    return True


def _ma_trend(closes):
    if len(closes) < 60:
        return None
    close = float(closes[-1])
    s10 = _sma(closes, 10)
    s20 = _sma(closes, 20)
    s50 = _sma(closes, 50)
    if s10 is None or s20 is None or s50 is None:
        return None
    s10_hist = _sma_series(closes, 10, n_points=6)
    s20_hist = _sma_series(closes, 20, n_points=6)
    s10_rising = _strictly_increasing(s10_hist)
    s10_falling = _strictly_decreasing(s10_hist)
    s20_rising = _strictly_increasing(s20_hist)
    s20_falling = _strictly_decreasing(s20_hist)

    direction = None
    if close > s20 > s50 and s10 > s20 and s10_rising and s20_rising:
        direction = "UP"
    elif close < s20 < s50 and s10 < s20 and s10_falling and s20_falling:
        direction = "DOWN"
    return {
        "direction": direction,
        "close": close,
        "sma10": s10,
        "sma20": s20,
        "sma50": s50,
        "sma10_rising": s10_rising,
        "sma20_rising": s20_rising,
        "sma10_falling": s10_falling,
        "sma20_falling": s20_falling,
    }


# ============================================================
# Counter-trend retracement
# ============================================================
def _counter_trend(df, direction):
    if len(df) < 6:
        return None
    highs = df["High"].values.astype(float)
    lows = df["Low"].values.astype(float)
    if direction == "UP":
        n = 0
        for i in range(len(highs) - 1, 0, -1):
            if highs[i] < highs[i - 1]:
                n += 1
            else:
                break
        ok = MIN_CONSOLIDATION_DAYS <= n <= MAX_CONSOLIDATION_DAYS
        return {"bars_lower_highs": n, "ok": ok, "invalidated": n > MAX_CONSOLIDATION_DAYS}
    n = 0
    for i in range(len(lows) - 1, 0, -1):
        if lows[i] > lows[i - 1]:
            n += 1
        else:
            break
    ok = MIN_CONSOLIDATION_DAYS <= n <= MAX_CONSOLIDATION_DAYS
    return {"bars_higher_lows": n, "ok": ok, "invalidated": n > MAX_CONSOLIDATION_DAYS}


# ============================================================
# Force Index (Elder)
# ============================================================
def _force_index(closes, volumes, period):
    if len(closes) < period + 2 or len(volumes) < 2:
        return None
    raw = []
    for i in range(1, len(closes)):
        raw.append((float(closes[i]) - float(closes[i - 1])) * float(volumes[i]))
    if not raw:
        return None
    k = 2.0 / (period + 1)
    e = raw[0]
    for x in raw[1:]:
        e = x * k + e * (1 - k)
    return float(e)


def _force_index_filter(closes, volumes, direction):
    fi13 = _force_index(closes, volumes, 13)
    fi3 = _force_index(closes, volumes, 3)
    if fi13 is None or fi3 is None:
        return None
    ok = fi13 >= 0 and fi3 <= 0 if direction == "UP" else fi13 <= 0 and fi3 >= 0
    return {"fi13": round(fi13, 0), "fi3": round(fi3, 0), "ok": ok}


# ============================================================
# Per-symbol scan
# ============================================================
def _scan_symbol(symbol, df, bench_returns):
    if df is None or len(df) < 60:
        return []
    closes = df["Close"].values.astype(float)
    volumes = df["Volume"].values.astype(float)
    signals = []

    # Filter 1 — beta
    beta = _beta(closes, bench_returns)
    if beta is not None:
        signals.append(
            {
                "symbol": symbol,
                "trader": SLUG,
                "method": "beta_filter",
                "direction": "both",
                "signal_type": "PASS" if beta >= BETA_MIN else "FAIL",
                "confidence": "MED",
                "notes": f"beta={beta:.2f} (min {BETA_MIN})",
                "raw": {"beta": round(beta, 3)},
            }
        )

    # Filter 2 — weekly amplitude
    amp = _amplitude(df, lookback=5)
    if amp is not None:
        ok = AMPLITUDE_MIN <= amp <= AMPLITUDE_MAX
        signals.append(
            {
                "symbol": symbol,
                "trader": SLUG,
                "method": "amplitude_filter",
                "direction": "both",
                "signal_type": "PASS" if ok else "FAIL",
                "confidence": "MED",
                "notes": f"5d range={amp * 100:.1f}% (target ≥{AMPLITUDE_MIN * 100:.0f}%)",
                "raw": {"amplitude": round(amp, 4)},
            }
        )

    # Filter 3 — gap classification (latest bar only)
    if len(df) >= 2:
        today_open = float(df["Open"].iloc[-1])
        prior_close = float(df["Close"].iloc[-2])
        gap = _gap_pct(today_open, prior_close)
        if gap is not None:
            is_gap = abs(gap) >= GAP_THRESHOLD
            signals.append(
                {
                    "symbol": symbol,
                    "trader": SLUG,
                    "method": "gap_classification",
                    "direction": "up" if gap > 0 else "down",
                    "signal_type": "GAP" if is_gap else "NORMAL_OPEN",
                    "confidence": "LOW",
                    "notes": f"open gap {gap * 100:+.2f}% ({'gap' if is_gap else 'normal'})",
                    "raw": {"gap_pct": round(gap, 4)},
                }
            )

    # Filter 4 — MA trend
    trend = _ma_trend(closes)
    if trend and trend["direction"]:
        signals.append(
            {
                "symbol": symbol,
                "trader": SLUG,
                "method": "ma_trend",
                "direction": "BULLISH" if trend["direction"] == "UP" else "BEARISH",
                "signal_type": trend["direction"],
                "confidence": "HIGH",
                "notes": (
                    f"close {trend['close']:.2f} · "
                    f"SMA10 {trend['sma10']:.2f} · "
                    f"SMA20 {trend['sma20']:.2f} · "
                    f"SMA50 {trend['sma50']:.2f}"
                ),
                "raw": trend,
            }
        )

        # Filter 5 — counter-trend retracement
        ct = _counter_trend(df, trend["direction"])
        if ct:
            signals.append(
                {
                    "symbol": symbol,
                    "trader": SLUG,
                    "method": "counter_trend",
                    "direction": "BULLISH" if trend["direction"] == "UP" else "BEARISH",
                    "signal_type": "PAUSE" if ct["ok"] else ("INVALIDATED" if ct["invalidated"] else "TOO_SHORT"),
                    "confidence": "MED" if ct["ok"] else "LOW",
                    "notes": (f"{ct.get('bars_lower_highs') or ct.get('bars_higher_lows')} bars of counter-trend move"),
                    "raw": ct,
                }
            )

            # Filter 6 — force index
            fi = _force_index_filter(closes, volumes, trend["direction"])
            if fi:
                signals.append(
                    {
                        "symbol": symbol,
                        "trader": SLUG,
                        "method": "force_index",
                        "direction": "BULLISH" if trend["direction"] == "UP" else "BEARISH",
                        "signal_type": "PASS" if fi["ok"] else "FAIL",
                        "confidence": "MED",
                        "notes": f"FI13={fi['fi13']:.0f} · FI3={fi['fi3']:.0f}",
                        "raw": fi,
                    }
                )

                # Filter 7 — composite setup
                beta_ok = beta is not None and beta >= BETA_MIN
                amp_ok = amp is not None and AMPLITUDE_MIN <= amp <= AMPLITUDE_MAX
                if beta_ok and amp_ok and ct["ok"] and fi["ok"]:
                    signals.append(
                        {
                            "symbol": symbol,
                            "trader": SLUG,
                            "method": "setup",
                            "direction": "BULLISH" if trend["direction"] == "UP" else "BEARISH",
                            "signal_type": "COMPOSITE_SETUP",
                            "confidence": "HIGH",
                            "notes": (
                                f"Full Larry Spears setup: beta={beta:.2f}, "
                                f"amp={amp * 100:.1f}%, "
                                f"CT={ct.get('bars_lower_highs') or ct.get('bars_higher_lows')}d, "
                                f"FI13={fi['fi13']:.0f}/FI3={fi['fi3']:.0f}"
                            ),
                            "raw": {
                                "beta": round(beta, 3),
                                "amplitude": round(amp, 4),
                                "counter_trend": ct,
                                "force_index": fi,
                            },
                        }
                    )

    return signals


# ============================================================
# Universe scan
# ============================================================
def scan(conn=None, limit=800):
    own = conn is None
    if own:
        conn = db.get_conn()

    global _BENCH_CACHE
    _BENCH_CACHE = None
    bench = _fetch_benchmark_returns(years=2)
    if bench is None or len(bench) < 60:
        log.warning("benchmark returns not available; beta filter will be skipped")

    syms = band_universe(conn, limit=limit)
    signals = []
    for i, sym in enumerate(syms, 1):
        rows = conn.execute(
            "SELECT date, open, high, low, close, volume FROM prices_daily WHERE symbol=? ORDER BY date", (sym,)
        ).fetchall()
        if len(rows) < 60:
            continue
        df = pd.DataFrame(list(rows), columns=["date", "Open", "High", "Low", "Close", "Volume"]).set_index("date")
        df.index = pd.to_datetime(df.index)
        try:
            sigs = _scan_symbol(sym, df, bench)
            signals.extend(sigs)
        except Exception as e:
            log.warning(f"{sym} scan failed: {e}")
        if i % 100 == 0:
            log.info(f"progress {i}/{len(syms)}, {len(signals)} signals")

    if own:
        conn.close()
    return signals
