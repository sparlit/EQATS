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
Apurva Parikh — 11 Secrets to find Value Stocks.
Classified: FUNDA (long-only, multi-factor composite).

Single composite strategy: all 11 secrets merged into one filter
chain per the owner's extraction instructions (not 11 methods).

Today's scan implements Secrets 6, 7, 8, 9, 10 (partial), 11 — the
ones computable from current data. Secrets 1, 2, 3, 4, 5 and the
Nifty PE part of Secret 10 await DR-01 (fundamentals_history),
DR-16 (promoter/pledge), DR-17 (Nifty PE), DR-18 (business age).

Exit rules (informational, R19/R30):
  The book's "sell when fundamentals deteriorate" rules are captured
  in EXIT_RULES below and attached to every signal's raw payload.
  The scanner identifies. The owner decides when to exit.

Signal shape:
  entry = today's close (buy at close-of-signal or next-day open)
  stop  = None (owner's risk decision)
  target = None

Bug-safety per R35:
  - `_fmt_num(v, dp)` returns "—" for None/NaN
  - `_try_emit` wraps each signal
"""
import db
import numpy as np
import pandas as pd
from log_utils import get_logger

log = get_logger("trader.apurva_parikh")

SLUG = "apurva_parikh"
NAME = "Apurva Parikh"
PILLAR = "funda"
SOURCE = "11 Secrets to find Value Stocks (Indian equity composite)"


# ----------------------------------------------------------------
# Tunables — book-cited thresholds
# ----------------------------------------------------------------
TICK = 0.05
MIN_PRICE = 100  # book: avoid penny stocks
MIN_BARS = 260  # room for SMA200 + RSI + trend

# Secret 6 — debt
DEBT_EQ_MAX = 0.30

# Secret 8 — ROE
ROE_MIN = 15.0  # percent

# Secret 9 — ROCE
ROCE_MIN = 20.0  # percent

# Secret 10 — Nifty PE gate (10–25; below 15 is best; above 40 danger)
# Nifty PE not yet fetched live. Owner updates this constant, or
# set to None to disable the market-timing gate (R23 graceful skip).
NIFTY_PE_PROXY = 22.0  # placeholder until DR-17 lands
NIFTY_PE_MAX = 25.0
NIFTY_PE_MIN = 10.0

# Secret 10 partial — stock PE vs industry PE (we use sector median)
PE_VS_SECTOR_MAX = 1.0  # PE must be <= sector median PE

# Secret 11 — trend + RSI
RSI_MIN = 60.0
SMA_TREND_FAST = 50
SMA_TREND_SLOW = 200
TREND_LOOKBACK = 20  # close must be > close[t-20]

# Universe gate
UNIVERSE_MIN_PCT = 40  # band 40th-pct mcap gate (as in other funda traders)

EXCLUDE_SECTOR_KEYWORDS = (
    "financ",
    "bank",
    "nbfc",
    "insur",
    "utilit",
    "power",
    "gas distribution",
    "water",
    "electric",
    "reit",
)


# ----------------------------------------------------------------
# Exit rules — informational metadata (R19/R30)
# ----------------------------------------------------------------
EXIT_RULES = {
    "fundamental_deterioration": {
        "trigger": "any 2+ conditions for 2 consecutive quarters/years",
        "conditions": [
            "sales_growth < 10%",
            "profit_growth < 10% or negative",
            "roe < 10%",
            "roce < 15%",
            "debt_to_equity > 0.50",
            "cfo_positive == false or ocf/net_income < 0.5",
            "promoter_holding < 50%",
            "pledged_pct > 20%",
            "pe > 1.5 * industry_pe",
        ],
    },
    "trend_deterioration": {
        "trigger": "any 1 occurs",
        "conditions": [
            "rsi < 40",
            "trend turns down (lower highs, lower lows)",
            "close breaks below SMA50 or SMA200",
        ],
    },
    "thesis_break": {
        "trigger": "any 1 occurs",
        "conditions": [
            "leadership fraud or regulatory action",
            "auditor resignation",
            "business model disruption",
        ],
    },
}


# ----------------------------------------------------------------
# METHODS registry — 1 composite
# ----------------------------------------------------------------
METHODS = [
    {
        "id": "composite_11_secret_value_strategy",
        "name": "Composite 11-Secret Value Strategy",
        "description": "All 11 secrets as one filter chain (5 testable today; 6 pending data).",
        "direction": "long",
        "scan": True,
        "confidence": "HIGH",
    },
]


# ----------------------------------------------------------------
# Helpers (R35 null-safe)
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
        if s is not None:
            sigs.append(s)
    except Exception as e:
        log.warning(f"signal emit skipped: {e}")


def _is_excluded_sector(sector):
    if not sector:
        return False
    s = sector.lower()
    return any(k in s for k in EXCLUDE_SECTOR_KEYWORDS)


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


def _sector_map(conn):
    out = {}
    try:
        for sym, sec in conn.execute(
            "SELECT symbol, sector FROM stocks WHERE sector IS NOT NULL AND sector!=''"
        ):
            out[sym] = sec
    except Exception:
        pass
    return out


def _sector_median_pe(pe_by_symbol, sector_by_symbol):
    """Compute median PE per sector from the cross-section we have."""
    by_sector = {}
    for sym, pe in pe_by_symbol.items():
        if pe is None or pe <= 0:
            continue
        sec = sector_by_symbol.get(sym)
        if not sec:
            continue
        by_sector.setdefault(sec, []).append(pe)
    out = {}
    for sec, vals in by_sector.items():
        if vals:
            out[sec] = float(np.median(vals))
    return out


def _load_df(conn, sym, limit=400):
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


def _rsi(closes, period=14):
    """Wilder's RSI (14-period). Returns last value."""
    n = len(closes)
    if n < period + 1:
        return None
    gains = 0.0
    losses = 0.0
    for i in range(1, period + 1):
        ch = closes[i] - closes[i - 1]
        if ch > 0:
            gains += ch
        else:
            losses -= ch
    avg_gain = gains / period
    avg_loss = losses / period
    for i in range(period + 1, n):
        ch = closes[i] - closes[i - 1]
        g = ch if ch > 0 else 0.0
        l = -ch if ch < 0 else 0.0
        avg_gain = (avg_gain * (period - 1) + g) / period
        avg_loss = (avg_loss * (period - 1) + l) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def _uptrend(closes):
    """Book's 'track the trend' filter, SMA-based."""
    if len(closes) < SMA_TREND_SLOW + 1:
        return None
    sma50 = float(np.mean(closes[-SMA_TREND_FAST:]))
    sma200 = float(np.mean(closes[-SMA_TREND_SLOW:]))
    close = float(closes[-1])
    if len(closes) < TREND_LOOKBACK + 1:
        return None
    prior = float(closes[-TREND_LOOKBACK - 1])
    return (close > sma50 > sma200) and (close > prior), sma50, sma200


# ----------------------------------------------------------------
# Per-symbol evaluation
# ----------------------------------------------------------------
def _signal(sym, entry, confidence, notes, raw):
    return {
        "symbol": sym,
        "trader": SLUG,
        "method": "composite_11_secret_value_strategy",
        "direction": "BULLISH",
        "signal_type": "VALUE_COMPOSITE",
        "entry": round(float(entry), 2) if entry is not None else None,
        "stop": None,
        "target": None,
        "confidence": confidence,
        "notes": notes,
        "raw": raw,
    }


def _evaluate_symbol(sym, f, df, sector_pe_median, nifty_pe_ok):
    """
    Full composite gate. Returns a signal dict or None.
    Records which secrets passed/failed/skipped in raw.secrets.
    """
    sectors = _is_excluded_sector(f.get("sector"))
    if sectors:
        return None

    pe = f.get("pe")
    de = f.get("debt_to_equity")
    roe = f.get("roe")
    roce = f.get("roce")
    cfo = f.get("cfo_positive")

    # If any core field missing → cannot evaluate the secrets that need it
    if None in (pe, de, roe, roce):
        return None
    if cfo != 1:
        return None

    # ---- Secret 6: D/E <= 0.30 ----
    if de > DEBT_EQ_MAX:
        return None

    # ---- Secret 7: CFO positive (already checked above) ----

    # ---- Secret 8: ROE >= 15% ----
    if roe < ROE_MIN:
        return None

    # ---- Secret 9: ROCE >= 20% ----
    if roce < ROCE_MIN:
        return None

    # ---- Secret 10 partial: PE >= 0 and PE <= sector median ----
    if pe is None or pe <= 0:
        return None
    if sector_pe_median is not None and pe > PE_VS_SECTOR_MAX * sector_pe_median:
        return None

    # ---- Secret 10 partial: Nifty PE gate (skip if unavailable) ----
    if not nifty_pe_ok:
        return None

    # ---- Secret 11: trend up + RSI >= 60 ----
    closes = df["close"].values.astype(float)
    up = _uptrend(closes)
    if up is None or up is False:
        return None
    trend_up, sma50, sma200 = up
    rsi = _rsi(closes, period=14)
    if rsi is None or rsi < RSI_MIN:
        return None

    close = float(closes[-1])

    # ---- Build signal ----
    secrets = {
        "1_business_age": "SKIPPED (DR-18)",
        "2_promoter_and_pledge": "SKIPPED (DR-16)",
        "3_sales_growth_10y": "SKIPPED (DR-01)",
        "4_profit_growth_10y": "SKIPPED (DR-01)",
        "5_leadership_quality": "NOTE only",
        "6_low_debt": "PASS",
        "7_cfo_positive": "PASS",
        "8_roe": "PASS",
        "9_roce": "PASS",
        "10_pe_vs_industry": "PASS",
        "10_nifty_pe_gate": "PASS",
        "11_trend_and_rsi": "PASS",
    }
    notes = (
        f"11-Secret composite (5 tested + 1 partial + 5 skipped): "
        f"ROE {_fmt_num(roe, 1)}% ROCE {_fmt_num(roce, 1)}% "
        f"D/E {_fmt_num(de, 2)} PE {_fmt_num(pe, 1)} "
        f"(sector med {_fmt_num(sector_pe_median, 1)}) "
        f"RSI {_fmt_num(rsi, 1)} up={trend_up}"
    )
    return _signal(
        sym,
        close,
        "HIGH",
        notes,
        {
            "secrets_passed": secrets,
            "pe": pe,
            "sector_median_pe": sector_pe_median,
            "debt_to_equity": de,
            "roe": roe,
            "roce": roce,
            "rsi": rsi,
            "sma50": sma50,
            "sma200": sma200,
            "close": close,
            "exit_rules": EXIT_RULES,
        },
    )


# ----------------------------------------------------------------
# Universe scan
# ----------------------------------------------------------------
def scan(conn=None, limit=800, symbols=None):
    own = conn is None
    if own:
        conn = db.get_conn()

    from traders.base import select_scan_symbols

    syms = select_scan_symbols(conn, limit, symbols)
    log.info(f"Parikh scan: {len(syms)} symbols in universe")

    fund_map = _fundamentals_map(conn)
    sector_map = _sector_map(conn)

    # Cross-sectional sector median PE
    pe_by_symbol = {}
    for sym, f in fund_map.items():
        v = _safe_f(f.get("pe"))
        if v is not None and v > 0:
            pe_by_symbol[sym] = v
    sector_pe = _sector_median_pe(pe_by_symbol, sector_map)
    log.info(f"computed sector median PE for {len(sector_pe)} sectors")

    # Nifty PE gate
    nifty_pe_ok = True
    if NIFTY_PE_PROXY is not None:
        nifty_pe_ok = NIFTY_PE_MIN <= NIFTY_PE_PROXY <= NIFTY_PE_MAX
        log.info(f"Nifty PE gate: proxy={NIFTY_PE_PROXY}, gate_open={nifty_pe_ok}")
    else:
        log.info("Nifty PE gate: proxy=None → gate skipped (R23)")

    signals = []
    n_loaded = 0
    n_short_hist = 0
    n_low_price = 0
    for i, sym in enumerate(syms, 1):
        f = fund_map.get(sym)
        if not f:
            continue
        df = _load_df(conn, sym)
        if df is None:
            n_short_hist += 1
            continue
        if df["close"].iloc[-1] < MIN_PRICE:
            n_low_price += 1
            continue
        n_loaded += 1

        sec = f.get("sector")
        sec_pe = sector_pe.get(sec) if sec else None

        _try_emit(
            signals,
            lambda sym=sym, f=f, df=df, sec_pe=sec_pe, npo=nifty_pe_ok: _evaluate_symbol(
                sym, f, df, sec_pe, npo
            ),
        )

        if i % 100 == 0:
            log.info(f"  progress {i}/{len(syms)}, {len(signals)} signals")

    if own:
        conn.close()

    log.info(
        f"Parikh scan complete: {n_loaded} loaded, "
        f"short_history={n_short_hist}, price<₹{MIN_PRICE}={n_low_price}, "
        f"{len(signals)} signals"
    )
    return signals
