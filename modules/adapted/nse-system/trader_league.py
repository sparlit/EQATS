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
Trader League — 14 famous-trader books + OUR system compete with
Rs 10,00,000 of play money each, on real NSE data.

WHY THIS EXISTS
  "We have to make something to backtest our system before deploying
  real money." This module is that something. For every player it answers:
    - What would Rs 10 lakh have become, AFTER real Indian costs?
    - How deep was the worst fall (max drawdown)?
    - Is the edge big enough to survive costs, slippage and bad luck?
    - Is OUR system ready for real money? (a plain checklist + verdict)
    - Which playbook/method/regime combinations held up under both exit modes?

THREE JOBS, ONE ENGINE
  1. BACKTEST ("pre-season"): replay history one day at a time. On each
     past day every trader sees ONLY prices up to that day (no peeking into
     the future) and its buy signals are stored in league_signals. Then a
     realistic portfolio simulator trades those signals: next-day fills,
     gaps through stops, costs, slippage, position sizing, max positions.
  2. LIVE LEAGUE: every weekday evening (scheduler 19:00 IST) today's
     signals from each trader + our Swing Desk are stored, and the paper
     portfolios are re-simulated from the league start. Weekly Telegram
     scorecard on Saturday.
  3. SIGNAL GENOME: closed trades are grouped by player, method and market
     regime. Shared exits provide a more entry-focused view; book exits show
     each implemented recipe. Minimum-sample cells are descriptive, not predictive.

HONEST LIMITS (read before trusting any number)
  - The 4 fundamentals books (O'Shaughnessy, Quantitative Value, Lowe,
    Parikh) and O'Neil's CAN SLIM earnings checks need point-in-time
    fundamentals, which we don't store (DR-01). They play in the LIVE
    league only. O'Neil's chart methods ARE backtested.
  - Universe = today's stock list (survivorship bias: stocks that died or
    shrank out of the band are missing), so backtests look better than
    reality. A point-in-time liquidity filter reduces the damage.
  - Our system's fundamentals veto and ALL-WEATHER mode use today's
    fundamentals, so the backtest skips them (HOME_USE_FUND_VETO switch).

USAGE (copy-paste, inside the venv)
  python trader_league.py status          # what's stored, replay progress
  python trader_league.py replay          # pre-season replay (3y, 300 stocks)
  python trader_league.py replay --years 5 --symbols 800 --workers 4
  python trader_league.py replay --players home,way_of_the_turtle
  python trader_league.py backtest        # simulate stored signals (fast)
  python trader_league.py table           # league table (backtest)
  python trader_league.py table --mode live
  python trader_league.py ready           # is OUR system ready for real money?
  python trader_league.py player home     # one player's details
  python trader_league.py live            # nightly job: collect + simulate
  python trader_league.py scorecard       # send the Telegram scorecard now
  python trader_league.py selftest        # accounting tests (no DB needed)

All tunables: strategy_config.LEAGUE (defaults below if missing).
"""
import argparse
import bisect
import contextlib
import datetime as dt
import hashlib
import importlib
import inspect
import json
import math
import os
import re
import sys
import threading
import time
from pathlib import Path

import db
import numpy as np
import pandas as pd
from log_utils import get_logger

log = get_logger("league")
BASE = Path(__file__).parent

# ============================================================
# CONFIG
# ============================================================
DEFAULTS = {
    "CAPITAL": 1_000_000,  # Rs 10 lakh per player
    "RISK_PER_TRADE": 0.01,  # 1% of equity at risk per trade
    "MAX_POSITIONS": 10,
    "MAX_POSITION_PCT": 0.20,  # no single stock > 20% of equity
    "MAX_PENDING": 30,  # open buy orders waiting to trigger
    "MIN_STOP_PCT": 0.01,  # size as if the stop is >= 1% away
    "MAX_STOP_PCT": 0.15,  # skip trades with a stop > 15% away
    "ORDER_VALID_BARS": 3,  # buy-stop / limit orders expire
    "MAX_HOLD_BARS": 60,  # safety time stop if a book has none
    "SLIPPAGE_PCT": 0.002,  # 0.2% per side (small/mid caps)
    # Daily bars can't say whether the high or the low came first.
    # "path": green candle = open>low>high>close, red = open>high>low>close
    # "worst": the stop always came first (harsh stress test)
    "INTRABAR": "path",
    # Indian equity-DELIVERY charges (verified Sep 2026: Zerodha)
    "BROKERAGE_PER_ORDER": 0.0,  # Rs 0 at Zerodha; set 20 for Rs 20/order
    "BROKERAGE_PCT": 0.0,  # e.g. 0.001 = 0.1% (min with per-order)
    "STT_PCT": 0.001,  # 0.1% buy AND sell
    "STAMP_PCT": 0.00015,  # 0.015% buy side
    "EXCH_PCT": 0.0000297,  # NSE transaction charge 0.00297%
    "SEBI_PCT": 0.000001,  # Rs 10 per crore
    "GST_PCT": 0.18,  # on brokerage + exchange + SEBI
    "DP_CHARGE": 15.93,  # per scrip per sell day (13.5 + GST)
    # tradeability (point-in-time, at the signal date)
    "MIN_PRICE": 20.0,
    "MIN_TURNOVER": 1e7,  # Rs 1 cr average daily traded value
    "LIQUIDITY_CAP_PCT": 0.05,  # position <= 5% of avg daily value
    # replay
    "REPLAY_YEARS": 3,
    "REPLAY_SYMBOLS": 300,  # band stocks (top by mcap) for books
    "HOME_BAND_LIMIT": 1000,  # our system: same universe as live
    "REPLAY_MAX_BARS": 600,  # history per call (Crane/Spears)
    "HOME_USE_FUND_VETO": False,  # today's fundamentals = lookahead
    # live league
    "LIVE_START": None,  # "YYYY-MM-DD" or None = first signal
    "BENCHMARK": "^NSEI",
    # real-money readiness checklist
    "READY_MIN_TRADES": 50,
    "READY_MIN_PF": 1.3,
    "READY_MAX_DD": 0.25,
    "READY_MC_DD95": 0.35,
    "READY_MIN_YEARS_POS": 0.6,
    "READY_MIN_LIVE_TRADES": 30,
    "MC_RUNS": 1000,
}


def config():
    c = dict(DEFAULTS)
    try:
        import strategy_config

        c.update(getattr(strategy_config, "LEAGUE", {}) or {})
    except Exception:
        pass
    return c


# ============================================================
# PLAYERS
# ============================================================
HOME = "home"
HOME_META = {
    "slug": HOME,
    "name": "Our System",
    "book": "Gabani Stage-2 pullback + regime/breadth/sector gates",
    "pillar": "swing",
}
FUNDA_LIVE_ONLY = {
    "oshaughnessy": "needs point-in-time fundamentals (DR-01)",
    "quantitative_value": "needs point-in-time fundamentals (DR-01)",
    "value_investing_made_easy": "needs point-in-time fundamentals (DR-01)",
    "apurva_parikh": "needs point-in-time fundamentals (DR-01)",
}
# How each chart book's _scan_symbol wants its data in the replay
ADAPTERS = {
    "way_of_the_turtle": {"fmt": "lower"},
    "nison": {"fmt": "lower"},
    "chande": {"fmt": "lower"},
    "mcallen": {"fmt": "lower"},
    "seven_simple_strategies": {"fmt": "lower"},
    "ishaan_agnihotri": {"fmt": "lower"},
    "singhal": {"fmt": "lower", "extra": "sector_rs"},
    "oneil": {"fmt": "lower", "extra": "oneil"},
    "john_crane": {"fmt": "upper", "min_rows": 260},
    "larry_spears": {"fmt": "upper", "min_rows": 60, "extra": "bench"},
}
BACKTESTABLE = [HOME, *list(ADAPTERS)]


def players():
    """All 15 players: our system + the 14 books in registry order."""
    out = [dict(HOME_META, backtest=True, why_not="")]
    try:
        import traders

        for t in traders.REGISTRY:
            out.append(
                {
                    "slug": t.SLUG,
                    "name": t.NAME,
                    "book": t.SOURCE,
                    "pillar": t.PILLAR,
                    "backtest": t.SLUG in ADAPTERS,
                    "why_not": FUNDA_LIVE_ONLY.get(t.SLUG, ""),
                }
            )
    except Exception as e:
        log.warning(f"traders registry unavailable: {e}")
    return out


def player_meta(slug):
    for p in players():
        if p["slug"] == slug:
            return p
    return {"slug": slug, "name": slug, "book": "", "pillar": "", "backtest": False, "why_not": ""}


def _trader_module(slug):
    return importlib.import_module(f"traders.{slug}")


# ============================================================
# SIGNAL CLASSIFICATION — which trader outputs are real BUY setups?
# Many trader "signals" are filters, forecasts or warnings, not trades.
# ============================================================
NON_ENTRY_TYPES = {
    "WATCH",
    "CONFIRMED",
    "DATE_PROJECTED",
    "LINE_PROJECTED",
    "WINDOW",
    "CONTINUATION",
    "PASS",
    "FAIL",
    "GAP",
    "NORMAL_OPEN",
    "UP",
    "DOWN",
    "PAUSE",
    "INVALIDATED",
    "TOO_SHORT",
    "TOP_WARNING",
    "SELL_STOP",
}


def classify(sig):
    """'ENTRY' (long setup), 'EXIT' (opposite signal) or None."""
    slug = sig.get("trader")
    d = str(sig.get("direction") or "").upper()
    t = str(sig.get("signal_type") or "").upper()
    m = sig.get("method")
    if slug == "mcallen":
        if t == "LONG_ENTRY":
            return "ENTRY"
        if t == "TOP_WARNING":
            return "EXIT"
        return None
    if slug == "john_crane":
        if t == "BUY_STOP":
            return "ENTRY"
        if d == "BEARISH" and t in ("SELL_STOP", "CONFIRMED"):
            return "EXIT"
        return None
    if slug == "larry_spears":
        if m == "setup" and t == "COMPOSITE_SETUP":
            return "ENTRY" if d == "BULLISH" else "EXIT"
        return None
    if d == "BULLISH" and t not in NON_ENTRY_TYPES:
        return "ENTRY"
    return None


def _parse_time_exit(sig):
    """(hold_sessions, entry_valid_sessions) from raw.exits.time_exit."""
    raw = sig.get("raw") if isinstance(sig.get("raw"), dict) else {}
    ex = raw.get("exits") if isinstance(raw.get("exits"), dict) else {}
    te = ex.get("time_exit")
    hold = valid = None
    if isinstance(te, dict):
        n = te.get("sessions")
        if isinstance(n, (int, float)) and n > 0:
            hold = int(n)
    elif isinstance(te, (int, float)) and not isinstance(te, bool) and te > 0:
        hold = int(te)
    elif isinstance(te, str):
        mm = re.search(r"(\d+)", te)
        if mm:
            n = int(mm.group(1))
            if "valid" in te.lower():
                valid = n
            else:
                hold = n
    return hold, valid


def _f(x):
    try:
        v = float(x)
        return v if math.isfinite(v) and v > 0 else None
    except (TypeError, ValueError):
        return None


# ============================================================
# COSTS — Indian equity delivery
# ============================================================
def trade_costs(side, value, C=None):
    """Statutory + broker costs in Rs for one order of `value` Rs."""
    C = C or config()
    value = abs(float(value))
    if value <= 0:
        return 0.0
    flat = float(C.get("BROKERAGE_PER_ORDER") or 0)
    pct = float(C.get("BROKERAGE_PCT") or 0)
    brok = min(flat, value * pct) if flat > 0 and pct > 0 else flat if flat > 0 else value * pct
    stt = value * C["STT_PCT"]
    exch = value * C["EXCH_PCT"]
    sebi = value * C["SEBI_PCT"]
    stamp = value * C["STAMP_PCT"] if side == "buy" else 0.0
    gst = C["GST_PCT"] * (brok + exch + sebi)
    dp = C["DP_CHARGE"] if side == "sell" else 0.0
    return brok + stt + exch + sebi + stamp + gst + dp


def inr(x, dec=0):
    """Indian digit grouping: 1045120 -> Rs 10,45,120."""
    if x is None or (isinstance(x, float) and not math.isfinite(x)):
        return "—"
    neg = x < 0
    s = f"{abs(x):.{dec}f}"
    whole, _, frac = s.partition(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        whole = ",".join([*parts, tail])
    return ("-" if neg else "") + "Rs " + whole + ("." + frac if frac else "")


# ============================================================
# DATABASE
# ============================================================
TABLES = """
CREATE TABLE IF NOT EXISTS league_signals (
  source TEXT, player TEXT, date TEXT, symbol TEXT, method TEXT,
  kind TEXT, entry REAL, stop REAL, target REAL, confidence TEXT,
  time_exit INTEGER, valid_bars INTEGER, close REAL, atr REAL,
  turnover REAL, size_mult REAL, created_at TEXT,
  PRIMARY KEY (source, player, date, symbol, method, kind)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS league_progress (
  player TEXT, symbol TEXT, first_date TEXT, last_date TEXT,
  n_signals INTEGER, code_hash TEXT, updated_at TEXT,
  PRIMARY KEY (player, symbol)
);
CREATE TABLE IF NOT EXISTS league_runs (
  run_id TEXT, player TEXT, mode TEXT, exit_mode TEXT,
  start TEXT, end TEXT, created_at TEXT, stats TEXT,
  PRIMARY KEY (run_id, player)
);
CREATE TABLE IF NOT EXISTS league_trades (
  run_id TEXT, player TEXT, symbol TEXT, method TEXT,
  entry_date TEXT, entry_price REAL, exit_date TEXT, exit_price REAL,
  shares INTEGER, pnl REAL, pnl_pct REAL, r_mult REAL, costs REAL,
  reason TEXT, bars INTEGER, regime TEXT
);
CREATE INDEX IF NOT EXISTS ix_league_trades_rp
  ON league_trades(run_id, player);
CREATE TABLE IF NOT EXISTS league_equity (
  run_id TEXT, player TEXT, date TEXT, equity REAL, cash REAL,
  n_pos INTEGER, PRIMARY KEY (run_id, player, date)
);
CREATE TABLE IF NOT EXISTS league_open (
  run_id TEXT, player TEXT, symbol TEXT, method TEXT,
  entry_date TEXT, entry_price REAL, shares INTEGER, stop REAL,
  last_close REAL, mtm_pnl REAL
);
CREATE TABLE IF NOT EXISTS league_index (
  symbol TEXT, date TEXT, close REAL, PRIMARY KEY (symbol, date)
);
"""


def ensure_tables(conn):
    conn.executescript(TABLES)
    conn.commit()


def _conn():
    conn = db.get_conn()
    ensure_tables(conn)
    return conn


def _now():
    return dt.datetime.now().isoformat(timespec="seconds")


def _jd(o):
    if isinstance(o, np.generic):
        return o.item()
    if isinstance(o, (set, tuple)):
        return list(o)
    return str(o)


def _dumps(obj):
    """json.dumps that turns numpy bools/floats into real JSON values
    (numpy False must never be saved as the truthy string "False")."""
    return json.dumps(obj, default=_jd)


def _last_price_date(conn):
    r = conn.execute("SELECT MAX(date) FROM prices_daily").fetchone()
    return r[0] if r and r[0] else None


def _chunks(seq, n):
    seq = list(seq)
    for i in range(0, len(seq), n):
        yield seq[i : i + n]


def _load_prices(conn, sym):
    rows = conn.execute(
        "SELECT date, open, high, low, close, volume FROM prices_daily WHERE symbol=? ORDER BY date", (sym,)
    ).fetchall()
    if not rows:
        return None
    df = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "volume"])
    for c in ["open", "high", "low", "close", "volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["close"]).reset_index(drop=True)
    df["date"] = df["date"].astype(str).str[:10]
    return df if len(df) else None


def _load_wide(conn, symbols, start_date=None):
    """dates x symbols matrix of closes (for breadth / sector ranks)."""
    frames = []
    for ch in _chunks(symbols, 400):
        q = f"SELECT symbol, date, close FROM prices_daily WHERE symbol IN ({','.join('?' * len(ch))})"
        args = list(ch)
        if start_date:
            q += " AND date >= ?"
            args.append(start_date)
        frames.append(pd.DataFrame(conn.execute(q, args).fetchall(), columns=["symbol", "date", "close"]))
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)
    if df.empty:
        return pd.DataFrame()
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df["date"] = df["date"].astype(str).str[:10]
    return df.pivot_table(index="date", columns="symbol", values="close", aggfunc="last").sort_index()


# ============================================================
# BENCHMARK + REGIME (point in time)
# ============================================================
INDEX_DB_CANDIDATES = ["NIFTY500", "NIFTY_50", "NIFTY50", "^NSEI", "NIFTY"]


def _covers(ser, start, end):
    if ser is None or len(ser) < 60:
        return False
    first, last = ser.index[0], ser.index[-1]
    ok_start = start is None or pd.Timestamp(first) <= pd.Timestamp(start) + pd.Timedelta(days=12)
    ok_end = end is None or pd.Timestamp(last) >= pd.Timestamp(end) - pd.Timedelta(days=10)
    return ok_start and ok_end


_FETCH_TRIED = set()


def _fetch_benchmark(conn, sym, start):
    """Download benchmark closes with yfinance into league_index (cache).
    Tried once per day per process; offline machines fall back silently."""
    key = (sym, dt.date.today().isoformat())
    if key in _FETCH_TRIED:
        return 0
    _FETCH_TRIED.add(key)
    try:
        import logging

        logging.getLogger("yfinance").setLevel(logging.CRITICAL)
        import yfinance as yf

        end = (dt.date.today() + dt.timedelta(days=1)).isoformat()
        d = yf.Ticker(sym).history(start=start, end=end, auto_adjust=True)
        if d is None or len(d) < 30:
            return 0
        rows = [
            (sym, idx.strftime("%Y-%m-%d"), float(c)) for idx, c in zip(d.index, d["Close"], strict=False) if c == c
        ]
        conn.executemany("INSERT OR REPLACE INTO league_index VALUES (?,?,?)", rows)
        conn.commit()
        return len(rows)
    except Exception as e:
        log.info(f"benchmark fetch skipped ({sym}): {e}")
        return 0


def load_benchmark(conn, start=None, end=None, fetch=True):
    """(pd.Series closes indexed by 'YYYY-MM-DD', label).
    Order: league_index cache (+yfinance refresh) -> index rows in
    prices_daily -> equal-weight index of the band universe."""
    C = config()
    sym = C["BENCHMARK"]
    q = "SELECT date, close FROM league_index WHERE symbol=? ORDER BY date"
    rows = conn.execute(q, (sym,)).fetchall()
    ser = pd.Series({r[0]: r[1] for r in rows}, dtype=float)
    if fetch and not _covers(ser, start, end):
        want = (pd.Timestamp(start or "2018-01-01") - pd.Timedelta(days=400)).strftime("%Y-%m-%d")
        if _fetch_benchmark(conn, sym, want):
            rows = conn.execute(q, (sym,)).fetchall()
            ser = pd.Series({r[0]: r[1] for r in rows}, dtype=float)
    if _covers(ser, start, end):
        return ser.sort_index(), sym
    for s in INDEX_DB_CANDIDATES:
        rows = conn.execute("SELECT date, close FROM prices_daily WHERE symbol=? ORDER BY date", (s,)).fetchall()
        ser2 = pd.Series({str(r[0])[:10]: r[1] for r in rows}, dtype=float)
        if _covers(ser2.dropna(), start, end):
            return ser2.dropna().sort_index(), s
    try:
        from universe_helper import band_universe

        syms = band_universe(conn, limit=300)
        w = _load_wide(conn, syms)
        if not w.empty:
            r = w.pct_change(fill_method=None).median(axis=1, skipna=True)
            r = r.fillna(0.0).clip(-0.2, 0.2)
            ew = 1000.0 * (1 + r).cumprod()
            return ew, "EW-universe"
    except Exception as e:
        log.warning(f"EW benchmark failed: {e}")
    return pd.Series(dtype=float), "none"


def regime_levels(bench):
    """date -> STRONG_BULL / BULL / NEUTRAL / WEAK / CAPITULATION
    (same rules as regime.MarketRegime.compute, point in time)."""
    from regime_spectrum import classify as rs_classify

    if bench is None or len(bench) == 0:
        return {}
    c = bench.astype(float)
    e10 = c.ewm(span=10, adjust=False).mean()
    e20 = c.ewm(span=20, adjust=False).mean()
    slope = (e10 / e10.shift(5) - 1) * 100
    out = {}
    for d, cv, a, b, s in zip(c.index, c.values, e10.values, e20.values, slope.values, strict=False):
        out[d] = rs_classify(
            close=float(cv), ema10=float(a), ema20=float(b), ema10_slope_pct=0.0 if s != s else float(s)
        )
    return out


def _asof(mapping_dates, mapping, d):
    """Value for date d, else the last known value before d."""
    if d in mapping:
        return mapping[d]
    k = bisect.bisect_right(mapping_dates, d) - 1
    return mapping[mapping_dates[k]] if k >= 0 else None


# ============================================================
# REPLAY CONTEXT — everything that depends only on the DATE
# ============================================================
def _sector_scores(conn, wide, dates):
    """Point-in-time version of sector_gate.sector_perf ranking.
    Returns ({date: [sectors best->worst]}, {sym: sector})."""
    try:
        import sector_gate

        min_n = getattr(sector_gate, "MIN_STOCKS_PER_SECTOR", 3)
    except Exception:
        min_n = 3
    rows = conn.execute(
        "SELECT s.symbol, s.sector FROM stocks s JOIN universe_broad u "
        "ON u.symbol=s.symbol WHERE s.sector IS NOT NULL AND s.sector!=''"
    ).fetchall()
    all_sec = dict(conn.execute("SELECT symbol, sector FROM stocks WHERE sector IS NOT NULL AND sector!=''").fetchall())
    sec_of = {s: sec for s, sec in rows if s in wide.columns}
    if not sec_of:
        return {}, all_sec
    p1 = {}
    p3 = {}
    for s in sec_of:
        ser = wide[s].dropna()
        if len(ser) < 25:
            continue
        p1[s] = (ser / ser.shift(21) - 1).reindex(wide.index)
        p3[s] = (ser / ser.shift(63) - 1).reindex(wide.index)
    if not p1:
        return {}, all_sec
    P1 = pd.DataFrame(p1)
    P3 = pd.DataFrame(p3)
    secs = pd.Series({s: sec_of[s] for s in P1.columns})
    m1 = P1.T.groupby(secs).mean()  # sectors x dates
    m3 = P3.T.groupby(secs).mean()
    n1 = P1.T.notna().groupby(secs).sum()
    score = 0.6 * m1 + 0.4 * m3
    out = {}
    for d in dates:
        if d not in score.columns:
            continue
        sc = score[d]
        ok = n1[d] >= min_n
        sc = sc[ok].dropna().sort_values(ascending=False)
        out[d] = list(sc.index)
    return out, all_sec


def _breadth_series(wide, sample, dates):
    """date -> (above50, adv, dec) like breadth.compute, point in time."""
    ab, ad, de, tot = [], [], [], []
    for s in sample:
        if s not in wide.columns:
            continue
        ser = wide[s].dropna()
        if len(ser) < 60:
            continue
        e50 = ser.ewm(span=50, adjust=False).mean()
        cnt = pd.Series(np.arange(1, len(ser) + 1), index=ser.index)
        valid = cnt >= 60
        prev = ser.shift(1)
        ab.append(((ser > e50) & valid).reindex(wide.index, fill_value=False))
        ad.append(((ser > prev) & valid).reindex(wide.index, fill_value=False))
        de.append(((ser < prev) & valid).reindex(wide.index, fill_value=False))
        tot.append(valid.reindex(wide.index, fill_value=False))
    if not tot:
        return {}
    A = pd.concat(ab, axis=1).sum(axis=1)
    AD = pd.concat(ad, axis=1).sum(axis=1)
    DE = pd.concat(de, axis=1).sum(axis=1)
    T = pd.concat(tot, axis=1).sum(axis=1)
    out = {}
    for d in dates:
        if d in T.index and T[d] > 0:
            out[d] = (round(float(A[d]) / float(T[d]), 3), int(AD[d]), int(DE[d]))
    return out


def _oneil_regimes(conn, dates):
    """O'Neil's own market-regime logic, fed only data up to each date."""
    try:
        O = _trader_module("oneil")
        full, sym = O._load_index_df(conn, limit=100000)
    except Exception:
        return dict.fromkeys(dates, "unavailable")
    if full is None or len(full) < 30:
        return dict.fromkeys(dates, "unavailable")
    full = full.copy()
    full["date"] = full["date"].astype(str).str[:10]
    ds = full["date"].tolist()
    orig = O._load_index_df
    out = {}
    try:
        for d in dates:
            k = bisect.bisect_right(ds, d)
            sub = full.iloc[max(0, k - 200) : k].reset_index(drop=True)
            O._load_index_df = lambda conn=None, limit=200, _s=sub: (_s if len(_s) else None, sym)
            try:
                out[d] = O._compute_market_regime(None)[0]
            except Exception:
                out[d] = "unavailable"
    finally:
        O._load_index_df = orig
    return out


def build_context(conn, start, end, slugs, book_syms, home_syms):
    """Precompute every date-only input the replay needs."""
    C = config()
    t0 = time.time()
    warm = (pd.Timestamp(start) - pd.Timedelta(days=560)).strftime("%Y-%m-%d")
    bench, label = load_benchmark(conn, warm, end, fetch=True)
    ctx = {"cfg": C, "start": start, "end": end, "bench_label": label}
    bench = bench[bench.index <= end]
    ctx["bench_dates"] = list(bench.index)
    ctx["bench_ret"] = bench.pct_change().dropna()
    ctx["bench_ret_dates"] = list(ctx["bench_ret"].index)

    need_gates = HOME in slugs
    need_sec = need_gates or "singhal" in slugs
    wide = pd.DataFrame()
    sample = []
    if need_gates or need_sec:
        try:
            import breadth

            sample_n = getattr(breadth, "SAMPLE", 400)
        except Exception:
            sample_n = 400
        sample = [
            r[0]
            for r in conn.execute(
                "SELECT symbol FROM universe_broad WHERE mcap_cr BETWEEN 1000 AND 8000 ORDER BY mcap_cr DESC LIMIT ?",
                (sample_n,),
            )
        ]
        sec_syms = [
            r[0]
            for r in conn.execute(
                "SELECT s.symbol FROM stocks s JOIN universe_broad u "
                "ON u.symbol=s.symbol WHERE s.sector IS NOT NULL "
                "AND s.sector!=''"
            )
        ]
        wide = _load_wide(conn, sorted(set(sample) | set(sec_syms)), warm)
    dates = sorted(
        d for d in (set(wide.index) if not wide.empty else set()) | set(ctx["bench_dates"]) if start <= d <= end
    )
    sec_rank, sym_sector = ({}, {})
    if need_sec and not wide.empty:
        sec_rank, sym_sector = _sector_scores(conn, wide, dates)
    ctx["sym_sector"] = sym_sector
    ctx["sector_rank"] = {
        d: {s: 1.0 - i / max(1, len(lst) - 1) for i, s in enumerate(lst)} for d, lst in sec_rank.items()
    }
    ctx["sector_rank_dates"] = sorted(ctx["sector_rank"])
    if need_gates:
        from regime_spectrum import ALLOWS_NORMAL_SWING, SIZE_MULT

        try:
            import sector_gate

            top_n = getattr(sector_gate, "TOP_N", 3)
        except Exception:
            top_n = 3
        lv = regime_levels(bench)
        lv_dates = sorted(lv)
        br = _breadth_series(wide, sample, dates) if not wide.empty else {}
        br_dates = sorted(br)
        gates = {}
        for d in dates:
            level = _asof(lv_dates, lv, d) or "NEUTRAL"
            b = _asof(br_dates, br, d) if br else None
            bok = True if b is None else (b[0] >= 0.5 and b[1] >= b[2])
            allowed = tuple(sec_rank.get(d, [])[:top_n])
            gates[d] = (level, SIZE_MULT.get(level, 1.0), ALLOWS_NORMAL_SWING.get(level, True), bok, allowed)
        ctx["home_gate"] = gates
        ctx["home_gate_dates"] = sorted(gates)
    if "oneil" in slugs:
        ctx["oneil_regime"] = _oneil_regimes(conn, dates)
    ctx["book_syms"] = set(book_syms)
    ctx["home_syms"] = set(home_syms)
    log.info(f"context ready in {time.time() - t0:.1f}s (benchmark {label}, {len(dates)} dates)")
    return ctx


# ============================================================
# REPLAY — one symbol, every historical day, only past data
# ============================================================
def _load_limit(m):
    try:
        p = inspect.signature(m._load_df).parameters.get("limit")
        if p is not None and isinstance(p.default, int):
            return p.default
    except Exception:
        pass
    return int(config()["REPLAY_MAX_BARS"])


def _prep(df):
    """Arrays + indicators for one symbol (full history)."""
    c = df["close"].values.astype(float)
    h = df["high"].values.astype(float)
    lo = df["low"].values.astype(float)
    v = df["volume"].fillna(0).values.astype(float)
    prev = np.concatenate([[np.nan], c[:-1]])
    tr = np.nanmax(np.vstack([h - lo, np.abs(h - prev), np.abs(lo - prev)]), axis=0)
    atr14 = pd.Series(tr).rolling(14).mean().values
    turn20 = pd.Series(c * v).rolling(20).mean().values
    dates = df["date"].tolist()
    return {
        "df": df,
        "dates": dates,
        "pos": {d: i for i, d in enumerate(dates)},
        "c": c,
        "h": h,
        "l": lo,
        "v": v,
        "atr14": atr14,
        "turn20": turn20,
        "up": None,
    }


def _upper(px):
    if px["up"] is None:
        df = px["df"]
        up = df.rename(columns={"open": "Open", "high": "High", "low": "Low", "close": "Close", "volume": "Volume"})
        up = up.set_index(pd.to_datetime(up["date"])).drop(columns=["date"])
        px["up"] = up
    return px["up"]


def _mk_row(
    source,
    player,
    d,
    sym,
    method,
    kind,
    px,
    i,
    entry=None,
    stop=None,
    target=None,
    conf="MED",
    hold=None,
    valid=None,
    size_mult=1.0,
):
    atr = px["atr14"][i]
    turn = px["turn20"][i]
    return (
        source,
        player,
        d,
        sym,
        str(method or "?"),
        kind,
        _f(entry),
        _f(stop),
        _f(target),
        str(conf or "MED"),
        hold,
        valid,
        round(float(px["c"][i]), 4),
        None if atr != atr else round(float(atr), 4),
        None if turn != turn else round(float(turn), 0),
        float(size_mult),
        None if source == "replay" else _now(),
    )


def _bench_upto(ctx, d, n=495):
    k = bisect.bisect_right(ctx["bench_ret_dates"], d)
    return ctx["bench_ret"].iloc[max(0, k - n) : k]


def _replay_book(slug, sym, px, dates, ctx):
    m = _trader_module(slug)
    ad = ADAPTERS[slug]
    C = ctx["cfg"]
    if ad["fmt"] == "lower":
        limit = _load_limit(m)
        min_bars = int(getattr(m, "MIN_BARS", 60))
        min_price = float(getattr(m, "MIN_PRICE", 0) or 0)
    else:
        limit = int(C["REPLAY_MAX_BARS"])
        min_bars = int(ad.get("min_rows", 60))
        min_price = 0.0
    extra = ad.get("extra")
    sector = ctx.get("sym_sector", {}).get(sym)
    rows, errors = [], 0
    for d in dates:
        i = px["pos"].get(d)
        if i is None:
            continue
        lo = max(0, i + 1 - limit)
        if i + 1 - lo < min_bars or px["c"][i] < min_price:
            continue
        w = px["df"].iloc[lo : i + 1].reset_index(drop=True) if ad["fmt"] == "lower" else _upper(px).iloc[lo : i + 1]
        try:
            if extra == "bench":
                sigs = m._scan_symbol(sym, w, _bench_upto(ctx, d))
            elif extra == "sector_rs":
                rs = None
                if sector:
                    rk = _asof(ctx["sector_rank_dates"], ctx["sector_rank"], d)
                    rs = rk.get(sector, 0.5) if rk else None
                sigs = m._scan_symbol(sym, w, rs)
            elif extra == "oneil":
                sigs = m._scan_symbol(sym, w, {}, ctx["oneil_regime"].get(d, "unavailable"))
            else:
                sigs = m._scan_symbol(sym, w)
        except Exception:
            errors += 1
            continue
        for s in sigs or []:
            kind = classify(s)
            if not kind:
                continue
            hold, valid = _parse_time_exit(s)
            rows.append(
                _mk_row(
                    "replay",
                    slug,
                    d,
                    sym,
                    s.get("method"),
                    kind,
                    px,
                    i,
                    s.get("entry"),
                    s.get("stop"),
                    s.get("target"),
                    s.get("confidence"),
                    hold,
                    valid,
                )
            )
    return rows, errors


def _replay_home(sym, px, dates, ctx):
    """Our Swing Desk pipeline, point in time: regime -> breadth ->
    sector gate -> Stage-2 screener -> Gabani SetupDetector -> fresh."""
    from setup import SetupDetector
    from strategy_config import SCREENER as S

    c, h, v = px["c"], px["h"], px["v"]
    n = len(c)
    if n < 280:
        return [], 0
    e200 = pd.Series(c).ewm(span=S["EMA200"], adjust=False).mean().values
    vavg = pd.Series(v).rolling(S["LIQ_DAYS"]).mean().values
    vs50 = pd.Series(v).rolling(50).mean().values
    expl = v > S["VOL_EXPLOSION_MULT"] * np.nan_to_num(vs50, nan=np.inf)
    expl60 = pd.Series(expl.astype(float)).rolling(S["VOL_LOOKBACK"], min_periods=1).max().values
    hh252 = pd.Series(h).rolling(252).max().values
    sector = ctx.get("sym_sector", {}).get(sym)
    gdates = ctx["home_gate_dates"]
    rows = []
    for d in dates:
        i = px["pos"].get(d)
        if i is None or i + 1 < 280:
            continue
        g = _asof(gdates, ctx["home_gate"], d)
        if g is None:
            continue
        _level, size_mult, allows, bok, allowed = g
        if not allows or not bok:
            continue
        if sector and allowed and sector not in allowed:
            continue
        if not (c[i] > e200[i] and e200[i] > e200[i - 20]):
            continue
        if vavg[i] * c[i] < S["MIN_AVG_TURNOVER"]:
            continue
        m1 = (c[i] - c[i - 21]) / c[i - 21] >= S["MOM_1M_MIN"]
        m3 = (c[i] - c[i - 63]) / c[i - 63] >= S["MOM_3M_MIN"]
        near = c[i] >= S["HIGH_52WK_MIN_RATIO"] * hh252[i]
        if not (m1 or m3 or near) or expl60[i] < 1:
            continue
        w = _upper(px).iloc[max(0, i + 1 - 400) : i + 1]
        st = SetupDetector.detect(w, sym)
        if not st.triggered or st.signal_date != d:
            continue
        conf = "HIGH" if st.shape_score >= 60 else "MED" if st.shape_score >= 40 else "LOW"
        rows.append(
            _mk_row(
                "replay",
                HOME,
                d,
                sym,
                "gabani_pullback",
                "ENTRY",
                px,
                i,
                st.entry_price,
                st.stop_loss,
                st.target_price,
                conf,
                None,
                None,
                size_mult,
            )
        )
    return rows, 0


# ---------- worker plumbing (also used in-process when workers=1)
_W = {}


def _worker_init(ctx, db_path):
    import logging

    logging.disable(logging.WARNING)  # traders log per symbol
    db.DB_PATH = db_path
    _W["ctx"] = ctx
    _W.pop("conn", None)


def _worker_conn():
    """One read-only-use connection per worker process."""
    if "conn" not in _W:
        import sqlite3

        _W["conn"] = sqlite3.connect(str(db.DB_PATH), timeout=60)
    return _W["conn"]


def _worker_task(task):
    sym, jobs = task
    ctx = _W["ctx"]
    t0 = time.time()
    df = _load_prices(_worker_conn(), sym)
    out = {"symbol": sym, "rows": [], "done": [], "errors": 0, "calls": 0}
    if df is None:
        out["done"] = [(p, segs) for p, segs in jobs]
        return out
    px = _prep(df)
    for player, segs in jobs:
        for seg in segs:
            dates = [d for d in px["dates"] if seg[0] <= d <= seg[1]]
            out["calls"] += len(dates)
            if player == HOME:
                r, e = _replay_home(sym, px, dates, ctx)
            else:
                r, e = _replay_book(player, sym, px, dates, ctx)
            out["rows"].extend(r)
            out["errors"] += e
        out["done"].append((player, segs))
    out["secs"] = time.time() - t0
    return out


def _code_hash(slug):
    try:
        if slug == HOME:
            from strategy_config import SCREENER, SETUP

            blob = json.dumps([SETUP, SCREENER], sort_keys=True).encode()
            for f in ("setup.py", "scanner.py"):
                p = BASE / f
                if p.exists():
                    blob += p.read_bytes()
        else:
            blob = (BASE / "traders" / f"{slug}.py").read_bytes()
        return hashlib.sha1(blob).hexdigest()[:12]
    except Exception:
        return ""


def _segments(start, end, first, last):
    """Date ranges of [start, end] not yet covered by [first, last]."""
    if not first or not last:
        return [(start, end)]
    segs = []
    if start < first:
        segs.append((start, min(end, _day_before(first))))
    if end > last:
        segs.append((max(start, _day_after(last)), end))
    return [s for s in segs if s[0] <= s[1]]


def _day_before(d):
    return (pd.Timestamp(d) - pd.Timedelta(days=1)).strftime("%Y-%m-%d")


def _day_after(d):
    return (pd.Timestamp(d) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")


def replay(years=None, n_symbols=None, slugs=None, workers=1, fresh=False, simulate_after=True, quiet=False):
    """Pre-season replay. Resumable: re-running only fills the gaps."""
    C = config()
    years = float(years or C["REPLAY_YEARS"])
    n_symbols = int(n_symbols or C["REPLAY_SYMBOLS"])
    slugs = [s for s in (slugs or BACKTESTABLE) if s in BACKTESTABLE]
    say = (lambda *a: None) if quiet else print
    conn = _conn()
    end = _last_price_date(conn)
    if not end:
        say("No prices in prices_daily — run the data pipeline first.")
        return {"error": "no prices"}
    start = (pd.Timestamp(end) - pd.Timedelta(days=int(365.25 * years))).strftime("%Y-%m-%d")
    from universe_helper import band_universe, combined_universe

    book_syms = band_universe(conn, limit=n_symbols)
    home_syms = combined_universe(conn, band_limit=int(C["HOME_BAND_LIMIT"])) if HOME in slugs else []
    if fresh:
        for s in slugs:
            conn.execute("DELETE FROM league_signals WHERE source='replay' AND player=?", (s,))
            conn.execute("DELETE FROM league_progress WHERE player=?", (s,))
        conn.commit()
    prog = {
        (p, s): (f, l)
        for p, s, f, l in conn.execute("SELECT player, symbol, first_date, last_date FROM league_progress")
    }
    tasks = {}
    for p in slugs:
        univ = home_syms if p == HOME else book_syms
        for s in univ:
            f, l = prog.get((p, s), (None, None))
            segs = _segments(start, end, f, l)
            if segs:
                tasks.setdefault(s, []).append((p, segs))
    todo = sorted(tasks.items())
    say("TRADER LEAGUE — pre-season replay")
    say(f"  window    : {start} -> {end}  ({years:g} years)")
    say(f"  players   : {len(slugs)}  ({', '.join(slugs)})")
    say(
        f"  universe  : books {len(book_syms)} stocks" + (f" · our system {len(home_syms)} stocks" if home_syms else "")
    )
    say(f"  work      : {len(todo)} stocks to replay" + ("" if todo else "  (nothing new — already up to date)"))
    if todo:
        ctx = build_context(conn, start, end, slugs, book_syms, home_syms)
        say(f"  benchmark : {ctx['bench_label']}")
        hashes = {p: _code_hash(p) for p in slugs}
        t0 = time.time()
        n_rows = n_err = n_calls = 0
        done_syms = 0

        def _store(res):
            nonlocal n_rows, n_err, n_calls, done_syms
            rows = res["rows"]
            if rows:
                conn.executemany(
                    "INSERT OR REPLACE INTO league_signals VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows
                )
            cnt = {}
            for r in rows:
                cnt[r[1]] = cnt.get(r[1], 0) + 1
            for p, segs in res["done"]:
                f, l = prog.get((p, res["symbol"]), (None, None))
                nf = min([x for x in [f] + [s[0] for s in segs] if x])
                nl = max([x for x in [l] + [s[1] for s in segs] if x])
                prog[(p, res["symbol"])] = (nf, nl)
                old = conn.execute(
                    "SELECT n_signals FROM league_progress WHERE player=? AND symbol=?", (p, res["symbol"])
                ).fetchone()
                conn.execute(
                    "INSERT OR REPLACE INTO league_progress VALUES (?,?,?,?,?,?,?)",
                    (
                        p,
                        res["symbol"],
                        nf,
                        nl,
                        (old[0] if old and old[0] else 0) + cnt.get(p, 0),
                        hashes.get(p, ""),
                        _now(),
                    ),
                )
            conn.commit()
            n_rows += len(rows)
            n_err += res["errors"]
            n_calls += res.get("calls", 0)
            done_syms += 1
            if done_syms % 10 == 0 or done_syms == len(todo):
                el = time.time() - t0
                eta = el / done_syms * (len(todo) - done_syms)
                msg = (
                    f"  [{done_syms * 100 // len(todo):3d}%] "
                    f"{done_syms}/{len(todo)} stocks · {n_rows:,} signals"
                    f" · {_hms(el)} elapsed · ETA {_hms(eta)}"
                )
                say(msg)
                log.info(msg)

        db_path = db.DB_PATH
        if workers and workers > 1:
            import multiprocessing as mp

            with mp.get_context("spawn").Pool(workers, initializer=_worker_init, initargs=(ctx, db_path)) as pool:
                for res in pool.imap_unordered(_worker_task, todo, chunksize=1):
                    _store(res)
        else:
            import logging

            prev = logging.root.manager.disable
            _worker_init(ctx, db_path)
            try:
                for t in todo:
                    _store(_worker_task(t))
            finally:
                logging.disable(prev)
                c = _W.pop("conn", None)
                if c is not None:
                    c.close()
        say(
            f"  done: {n_rows:,} signals from {n_calls:,} stock-days in "
            f"{_hms(time.time() - t0)}" + (f" ({n_err} scanner errors skipped)" if n_err else "")
        )
    conn.close()
    out = {"start": start, "end": end, "players": slugs, "stocks": len(todo)}
    if simulate_after:
        for ex in ("book", "common"):
            res = simulate_all("backtest", ex, quiet=True)
            out[ex] = bool(res and not res.get("error"))
        if not quiet:
            print_table("backtest", "book")
            print_ready()
    return out


def _hms(sec):
    sec = int(max(0, sec))
    h, r = divmod(sec, 3600)
    m, s = divmod(r, 60)
    return f"{h}h{m:02d}m" if h else f"{m}m{s:02d}s"


# ============================================================
# EXIT PROFILES — each book's own exit logic (EXIT_LOGIC.md)
# ============================================================
def _home_profile():
    from strategy_config import BACKTEST as BT

    p = {
        "stop": ("signal",),
        "entry_tick": BT.get("TICK_SIZE", 0.05),
        "entry_kind": "STOP",
        "valid_bars": BT.get("ORDER_EXPIRY_BARS", 3),
        "max_hold": None,
        "max_hold_days": BT.get("HOLD_DAYS_MAX", 30),
    }
    if BT.get("TRANCHES_ENABLED"):
        p["partials"] = [(BT["T_LEVEL_1"], BT["T_PCT_1"], "be"), (BT["T_LEVEL_2"], BT["T_PCT_2"], "trail")]
        p["trail_ma"] = ("ema", BT.get("TRAIL_EMA", 10))
        p["trail_needs_flag"] = True
        p["why"] = (
            f"Stop at the pattern-day low. Sell {BT['T_PCT_1']:.0%} at "
            f"+{BT['T_LEVEL_1']:g}R (stop to breakeven), "
            f"{BT['T_PCT_2']:.0%} at +{BT['T_LEVEL_2']:g}R, trail the "
            f"rest below the {BT.get('TRAIL_EMA', 10)} EMA; "
            f"{BT.get('HOLD_DAYS_MAX', 30)}-day time stop "
            "(strategy_config.BACKTEST)."
        )
    else:
        p["target"] = ("r", BT.get("TARGET_R", 3.0))
        p["why"] = (
            f"Buy-stop above the mother bar (valid "
            f"{BT.get('ORDER_EXPIRY_BARS', 3)} days), stop at the "
            f"pattern-day low, target +{BT.get('TARGET_R', 3.0):g}R, "
            f"{BT.get('HOLD_DAYS_MAX', 30)}-day time stop — same "
            "rules as backtest.py / strategy_config.BACKTEST."
        )
    return p


BOOK_PROFILES = {
    "john_crane": {
        "stop": ("signal_or_low", 10),
        "trail_low": 5,
        "max_hold": 20,
        "opposite": True,
        "entry_kind": "STOP",
        "why": "Structural stop below the swing low; an opposite trail-day "
        "or reaction-swing confirmation kills the trade; ~20-session "
        "reversal window; a 5-day-low trail stands in for the "
        "trail-day confirmation.",
    },
    "larry_spears": {
        "stop": ("atr", 2.0, 14),
        "max_hold": 5,
        "time_mode": "loss_only",
        "trail_low": 10,
        "opposite": True,
        "why": "Book leaves the stop to the owner -> 2xATR safety stop. "
        "5-day invalidation: not working by day 5 = exit. Winners "
        "trail the 10-day low; an opposite setup exits.",
    },
    "way_of_the_turtle": {
        "stop": ("atr", 2.0, 20),
        "max_hold": None,
        "trail_low": 20,
        "trail_low_by_method": {"turtle_system_1_20d": 10, "turtle_system_2_55d": 20},
        "why": "2N stop (2x 20-day ATR). Exit on the opposite breakout: "
        "10-day low for System 1, 20-day low for System 2 and the "
        "other trend systems. No target, no time stop.",
    },
    "seven_simple_strategies": {
        "stop": ("signal_or_atr", 2.0, 14),
        "target": ("signal",),
        "trail_ma": ("ema", 9),
        "trail_after_r": 0.0,
        "max_hold": 60,
        "why": "2xATR stop (or the setup's own). Target at the next "
        "resistance when given. Once in profit, a close below the "
        "9 EMA exits ('love your small losses').",
    },
    "ishaan_agnihotri": {
        "stop": ("signal_or_low", 10),
        "target": ("signal",),
        "trail_ma": ("ema", 9),
        "trail_after_r": 0.0,
        "max_hold": 60,
        "why": "Mental stop below the swing low, profits at resistance, "
        "exit on a close below the 9 EMA once in profit.",
    },
    "nison": {
        "stop": ("signal_or_low", 5),
        "target": ("signal",),
        "max_hold": 40,
        "valid_from_signal": True,
        "why": "Stop at the reversal candle's low, target at the next "
        "resistance; setup validity windows (3-10 sessions) limit "
        "how long an entry order waits.",
    },
    "chande": {
        "stop": ("signal_or_atr", 2.0, 20),
        "target": ("signal",),
        "trail_low": 10,
        "trail_after_r": 2.0,
        "max_hold": ("signal", 20),
        "why": "2-3xATR stop; method targets; after +2R trail the 10-day low; per-method time exits (14-50 sessions).",
    },
    "oneil": {
        "stop": ("pct_cap", 0.08),
        "target": ("pct", 0.20),
        "oneil": True,
        "be_pct": 0.15,
        "max_hold": None,
        "why": "Cut every loss at 7-8%. Take profits at +20% — but if +20% "
        "comes within 3 weeks, hold at least 8 weeks, then trail the "
        "50-day line. Never let a 15% gain turn into a loss.",
    },
    "mcallen": {
        "stop": ("signal_or_low", 10),
        "target": ("signal",),
        "max_hold": ("signal", 20),
        "opposite": True,
        "why": "Stop at the pattern low right after entry, measured-move "
        "target, setup time windows; a top-warning pattern exits.",
    },
    "singhal": {
        "stop": ("signal_or_atr", 2.0, 14),
        "target": ("signal_or_r", 2.0),
        "trail_ma": ("ema", 9),
        "trail_after_r": 1.0,
        "max_hold": ("signal", 10),
        "why": "Structural stop, minimum 1:2 target, trail the 9 EMA once "
        "+1R, strict per-method time windows (3-20 sessions).",
    },
    "oshaughnessy": {
        "stop": None,
        "sizing": "equal",
        "max_hold": None,
        "rebalance": 252,
        "why": "Annual rebalance: hold a year, re-rank, keep only names the book still selects. No stops.",
    },
    "quantitative_value": {
        "stop": None,
        "sizing": "equal",
        "max_hold": None,
        "rebalance": 252,
        "why": "Annual rebalance; never override the model. No stops.",
    },
    "value_investing_made_easy": {
        "stop": None,
        "sizing": "equal",
        "target": ("pct", 0.50),
        "max_hold": 504,
        "rebalance": 63,
        "why": "Graham: sell at +50% or after two years; quarterly check "
        "sells names that dropped out of the screen (deterioration).",
    },
    "apurva_parikh": {
        "stop": None,
        "sizing": "equal",
        "max_hold": None,
        "rebalance": 63,
        "why": "Quarterly review: hold what still qualifies, sell what deteriorated.",
    },
}

COMMON_PROFILE = {
    "stop": ("signal_or_atr", 2.0, 14),
    "target": ("r", 2.0),
    "max_hold": 20,
    "why": "Same exits for everyone: the setup's stop (or 2xATR), a 2R "
    "target and a 20-session time stop. This isolates the quality of "
    "each book's ENTRIES.",
}


ENTRY_KEYS = ("entry_kind", "entry_tick", "valid_bars", "valid_from_signal")


def exit_profile(player, exit_mode="book"):
    """Book mode: the book's own exits. Common mode: same exits for all,
    but each book keeps its own ENTRY rules (order type, validity)."""
    book = _home_profile() if player == HOME else dict(BOOK_PROFILES.get(player, COMMON_PROFILE))
    if exit_mode != "common":
        return book
    p = dict(COMMON_PROFILE)
    for k in ENTRY_KEYS:
        if k in book:
            p[k] = book[k]
    return p


# ============================================================
# PRICE BOOK — OHLC arrays + lazily computed indicators
# ============================================================
class PriceBook:
    def __init__(self, frames):
        self.s = {}
        for sym, df in frames.items():
            if df is None or not len(df):
                continue
            d = df["date"].astype(str).str[:10].tolist()
            self.s[sym] = {
                "dates": d,
                "pos": {x: i for i, x in enumerate(d)},
                "o": df["open"].values.astype(float),
                "h": df["high"].values.astype(float),
                "l": df["low"].values.astype(float),
                "c": df["close"].values.astype(float),
                "v": df["volume"].fillna(0).values.astype(float),
            }
            for k in ("o", "h", "l"):  # repair missing OHLC
                a = self.s[sym][k]
                bad = ~np.isfinite(a)
                if bad.any():
                    a[bad] = self.s[sym]["c"][bad]
        self._ind = {}

    @classmethod
    def from_db(cls, conn, symbols, start, warmup_days=520):
        since = (pd.Timestamp(start) - pd.Timedelta(days=warmup_days)).strftime("%Y-%m-%d")
        frames = {}
        for ch in _chunks(sorted(symbols), 300):
            q = (
                "SELECT symbol, date, open, high, low, close, volume FROM "
                f"prices_daily WHERE date >= ? AND symbol IN "
                f"({','.join('?' * len(ch))}) ORDER BY symbol, date"
            )
            df = pd.DataFrame(
                conn.execute(q, [since, *ch]).fetchall(),
                columns=["symbol", "date", "open", "high", "low", "close", "volume"],
            )
            for c in ["open", "high", "low", "close", "volume"]:
                df[c] = pd.to_numeric(df[c], errors="coerce")
            df = df.dropna(subset=["close"])
            for sym, g in df.groupby("symbol", sort=False):
                frames[sym] = g.reset_index(drop=True)
        return cls(frames)

    def has(self, sym):
        return sym in self.s

    def idx(self, sym, d):
        x = self.s.get(sym)
        return None if x is None else x["pos"].get(d)

    def dates(self):
        out = set()
        for x in self.s.values():
            out.update(x["dates"])
        return sorted(out)

    def ind(self, sym, name):
        key = (sym, name)
        if key in self._ind:
            return self._ind[key]
        x = self.s[sym]
        c = pd.Series(x["c"])
        if name.startswith("atr"):
            n = int(name[3:])
            prev = c.shift(1).values
            tr = np.nanmax(np.vstack([x["h"] - x["l"], np.abs(x["h"] - prev), np.abs(x["l"] - prev)]), axis=0)
            a = pd.Series(tr).rolling(n, min_periods=1).mean().values
        elif name.startswith("ema"):
            a = c.ewm(span=int(name[3:]), adjust=False).mean().values
        elif name.startswith("sma"):
            a = c.rolling(int(name[3:]), min_periods=1).mean().values
        elif name.startswith("low"):
            a = pd.Series(x["l"]).rolling(int(name[3:]), min_periods=1).min().values
        elif name.startswith("turn"):
            a = (c * pd.Series(x["v"])).rolling(int(name[4:]), min_periods=1).mean().values
        else:
            raise KeyError(name)
        self._ind[key] = a
        return a


# ============================================================
# PORTFOLIO SIMULATOR
# ============================================================
CONF_RANK = {"HIGH": 0, "MED": 1, "MEDIUM": 1, "LOW": 2}


class _Pos:
    __slots__ = (
        "actions",
        "bars",
        "be_done",
        "buy_cost",
        "costs",
        "entry",
        "entry_date",
        "equity_at_entry",
        "exit_next",
        "hold_until",
        "init_shares",
        "init_stop",
        "max_close",
        "max_high",
        "max_hold",
        "method",
        "parts_done",
        "proceeds",
        "prof",
        "rb_due",
        "reason",
        "risk_ps",
        "shares",
        "sig_date",
        "sold_qty",
        "sold_value",
        "stop",
        "stop_reason",
        "sym",
        "target",
        "target_off",
        "trail_on",
    )

    def __init__(self, **kw):
        for k in self.__slots__:
            setattr(self, k, kw.get(k))


def _resolve_stop(prof, od, fill, book, sym, jsig):
    rule = prof.get("stop")
    if rule is None:
        return None
    s = od["stop"] if od.get("stop") and 0 < od["stop"] < fill else None
    kind = rule[0]
    if kind == "signal":
        return s
    if kind == "pct_cap":
        floor = fill * (1 - rule[1])
        return max(s, floor) if s else floor
    if kind == "signal_or_atr":
        if s:
            return s
        atr = book.ind(sym, f"atr{rule[2]}")[jsig]
        return fill - rule[1] * atr if atr == atr and atr > 0 else None
    if kind == "atr":
        atr = book.ind(sym, f"atr{rule[2]}")[jsig]
        return fill - rule[1] * atr if atr == atr and atr > 0 else None
    if kind == "signal_or_low":
        if s:
            return s
        low = book.ind(sym, f"low{rule[1]}")[jsig]
        if low == low and 0 < low < fill:
            return low
        atr = book.ind(sym, "atr14")[jsig]
        return fill - 2 * atr if atr == atr and atr > 0 else None
    return s


def _resolve_target(prof, od, fill, stop):
    rule = prof.get("target")
    if not rule:
        return None
    t = od.get("target")
    sig_t = t if t and t > fill else None
    risk = (fill - stop) if stop else None
    if rule[0] == "signal":
        return sig_t
    if rule[0] == "r":
        return fill + rule[1] * risk if risk else None
    if rule[0] == "signal_or_r":
        return sig_t or (fill + rule[1] * risk if risk else None)
    if rule[0] == "pct":
        return fill * (1 + rule[1])
    return None


def _resolve_hold(prof, od, C):
    if "max_hold" not in prof:
        return int(C["MAX_HOLD_BARS"])
    mh = prof["max_hold"]
    if isinstance(mh, tuple):
        return int(od.get("time_exit") or mh[1])
    return mh


def simulate(player, entries, exits, book, dates, profile, C=None, capital=None, levels=None):
    """Trade one player's signals. Pure function (no DB) so it can be
    unit-tested. entries: list of signal dicts; exits: set of
    (date, symbol) opposite signals; book: PriceBook; dates: calendar."""
    C = C or config()
    cap0 = float(capital or C["CAPITAL"])
    slip = float(C["SLIPPAGE_PCT"])
    max_pos = int(C["MAX_POSITIONS"])
    levels = levels or {}
    state = {"cash": cap0}
    positions, pending, trades, curve = {}, [], [], []
    last_close = {}

    by_date = {}
    for e in entries:
        by_date.setdefault(e["date"], []).append(e)
    selected = {d: {e["symbol"] for e in lst} for d, lst in by_date.items()}

    def sell(pos, qty, raw_px, d, reason):
        qty = int(min(qty, pos.shares))
        if qty <= 0:
            return
        px = float(raw_px) * (1 - slip)
        value = qty * px
        cost = trade_costs("sell", value, C)
        state["cash"] += value - cost
        pos.shares -= qty
        pos.proceeds += value - cost
        pos.costs += cost
        pos.sold_qty += qty
        pos.sold_value += value
        pos.reason = reason
        if pos.shares <= 0:
            invested = pos.init_shares * pos.entry
            pnl = pos.proceeds - invested - pos.buy_cost
            risk_rs = pos.init_shares * pos.risk_ps if pos.risk_ps else None
            reason_txt = reason if not pos.parts_done else f"PARTIAL+{reason}"
            trades.append(
                {
                    "symbol": pos.sym,
                    "method": pos.method,
                    "entry_date": pos.entry_date,
                    "entry_price": round(pos.entry, 4),
                    "exit_date": d,
                    "exit_price": round(pos.sold_value / pos.sold_qty, 4),
                    "shares": pos.init_shares,
                    "pnl": round(pnl, 2),
                    "pnl_pct": round(pnl / invested, 5) if invested else 0.0,
                    "r_mult": round(pnl / risk_rs, 3) if risk_rs else None,
                    "costs": round(pos.buy_cost + pos.costs, 2),
                    "reason": reason_txt,
                    "bars": pos.bars,
                    "regime": levels.get(pos.sig_date) or levels.get(pos.entry_date),
                    "equity_at_entry": pos.equity_at_entry,
                }
            )
            positions.pop(pos.sym, None)

    worst = str(C.get("INTRABAR", "path")).lower() == "worst"

    def bar_exits(pos, j, d, entry=None):
        """Stops / targets on one daily bar. entry=None for a normal bar,
        else how the position was bought on this bar: 'OPEN' (at the open),
        'STOP' (buy-stop hit during the day) or 'LIMIT' (dip-buy fill).
        Only price moves AFTER the fill can hit the stop or the target."""
        x = book.s[pos.sym]
        o, h, lo, c = x["o"][j], x["h"][j], x["l"][j], x["c"][j]
        if pos.exit_next and entry is None:
            sell(pos, pos.shares, o, d, pos.exit_next)
            return
        if entry is None and pos.stop is not None and o <= pos.stop:
            sell(pos, pos.shares, o, d, pos.stop_reason + "_GAP")
            return
        green = c > o
        if entry == "STOP" and not worst:
            # bought on the way up: a green day's low came BEFORE the fill
            low_after, high_after, first = (c if green else lo), h, "target"
        elif entry == "LIMIT" and not worst:
            # bought on the way down: a red day's high came BEFORE the fill
            low_after, high_after, first = lo, (h if green else c), "stop"
        else:
            low_after, high_after = lo, h
            first = "stop" if (worst or green) else "target"
        gap_ok = entry is None  # only a fresh bar can gap past a level
        for step in ("stop", "target") if first == "stop" else ("target", "stop"):
            if step == "stop":
                if pos.stop is not None and low_after <= pos.stop:
                    sell(pos, pos.shares, pos.stop, d, pos.stop_reason)
                    return
                continue
            for k, (r_lvl, frac, action) in enumerate(pos.prof.get("partials") or []):
                if k in pos.parts_done or not pos.risk_ps:
                    continue
                lvl = pos.entry + r_lvl * pos.risk_ps
                if high_after >= lvl:
                    qty = max(1, math.floor(pos.init_shares * frac))
                    pos.parts_done.add(k)
                    pos.actions.append(action)
                    sell(pos, qty, max(o, lvl) if gap_ok else lvl, d, f"T{r_lvl:g}R")
                    if pos.shares <= 0:
                        return
            if pos.target and not pos.target_off and high_after >= pos.target:
                if pos.prof.get("oneil") and pos.bars < 15:
                    pos.target_off = True  # big leader: hold 8 weeks
                    pos.hold_until = pos.bars + 40
                else:
                    sell(pos, pos.shares, max(o, pos.target) if gap_ok else pos.target, d, "TARGET")
                    return

    def eod(pos, j, d):
        x = book.s[pos.sym]
        c, h = x["c"][j], x["h"][j]
        prof = pos.prof
        pos.bars += 1
        pos.max_high = max(pos.max_high, h)
        pos.max_close = max(pos.max_close, c)
        for a in pos.actions:
            if a == "be" and pos.stop is not None and pos.entry > pos.stop:
                pos.stop, pos.stop_reason = pos.entry, "BREAKEVEN"
            elif a == "trail":
                pos.trail_on = True
        pos.actions = []
        if pos.stop is not None and not pos.be_done:
            hit = (prof.get("be_r") and pos.risk_ps and pos.max_high >= pos.entry + prof["be_r"] * pos.risk_ps) or (
                prof.get("be_pct") and pos.max_high >= pos.entry * (1 + prof["be_pct"])
            )
            if hit:
                pos.be_done = True
                if pos.entry > pos.stop:
                    pos.stop, pos.stop_reason = pos.entry, "BREAKEVEN"
        active = True
        if prof.get("trail_needs_flag"):
            active = bool(pos.trail_on)
        elif prof.get("trail_after_r") is not None:
            need = pos.entry + prof["trail_after_r"] * (pos.risk_ps or 0)
            active = pos.max_close > max(need, pos.entry * 1.0005)
        n_low = (prof.get("trail_low_by_method") or {}).get(pos.method, prof.get("trail_low"))
        if n_low and active and pos.stop is not None:
            lvl = book.ind(pos.sym, f"low{n_low}")[j]
            if lvl == lvl and lvl > pos.stop and lvl < c:
                pos.stop, pos.stop_reason = lvl, "TRAIL_STOP"
        tm = prof.get("trail_ma")
        if tm and active and not pos.exit_next:
            ma = book.ind(pos.sym, f"{tm[0]}{tm[1]}")[j]
            if c < ma:
                pos.exit_next = "TRAIL_MA"
        if pos.hold_until is not None and pos.bars >= pos.hold_until:
            if c < book.ind(pos.sym, "sma50")[j] and not pos.exit_next:
                pos.exit_next = "TRAIL_50DMA"
        if pos.max_hold and pos.bars >= pos.max_hold and pos.hold_until is None:
            if prof.get("time_mode") != "loss_only" or c <= pos.entry:
                sell(pos, pos.shares, c, d, "TIME")
                return
        mhd = prof.get("max_hold_days")
        if mhd and (pd.Timestamp(d) - pd.Timestamp(pos.entry_date)).days >= mhd:
            sell(pos, pos.shares, c, d, "TIME")
            return
        if prof.get("opposite") and (d, pos.sym) in exits and not pos.exit_next:
            pos.exit_next = "OPPOSITE"
        rb = prof.get("rebalance")
        if rb and pos.bars % rb == 0:
            pos.rb_due = True
        if pos.rb_due and d in selected:  # book reported picks today
            pos.rb_due = False
            if pos.sym not in selected[d] and not pos.exit_next:
                pos.exit_next = "REBALANCE"

    def open_pos(od, j, d, raw_fill, equity_ref):
        sym = od["symbol"]
        prof = od["prof"]
        fill = float(raw_fill) * (1 + slip)
        jsig = book.idx(sym, od["date"])
        if jsig is None:
            jsig = max(0, j - 1)
        stop = _resolve_stop(prof, od, fill, book, sym, jsig)
        if prof.get("stop") is not None:
            if stop is None or stop >= fill:
                return None
            if (fill - stop) / fill > C["MAX_STOP_PCT"]:
                return None
        if prof.get("sizing") == "equal" or stop is None:
            shares = int(equity_ref / max_pos / fill)
        else:
            risk_ps = max(fill - stop, fill * C["MIN_STOP_PCT"])
            budget = equity_ref * C["RISK_PER_TRADE"] * float(od.get("size_mult") or 1.0)
            shares = int(budget / risk_ps)
        shares = min(shares, int(C["MAX_POSITION_PCT"] * equity_ref / fill))
        turn = od.get("turnover")
        if turn and turn > 0:
            shares = min(shares, int(C["LIQUIDITY_CAP_PCT"] * turn / fill))
        while shares > 0:
            cost = trade_costs("buy", shares * fill, C)
            if shares * fill + cost <= state["cash"]:
                break
            shares = int((state["cash"] - cost) / fill) if shares > 1 else 0
        if shares < 1:
            return None
        value = shares * fill
        cost = trade_costs("buy", value, C)
        state["cash"] -= value + cost
        pos = _Pos(
            sym=sym,
            method=od["method"],
            entry_date=d,
            entry=fill,
            shares=shares,
            init_shares=shares,
            stop=stop,
            stop_reason="STOP",
            init_stop=stop,
            target=_resolve_target(prof, od, fill, stop),
            risk_ps=(fill - stop) if stop else None,
            bars=0,
            max_high=fill,
            max_close=fill,
            be_done=False,
            parts_done=set(),
            trail_on=False,
            exit_next=None,
            buy_cost=cost,
            proceeds=0.0,
            costs=0.0,
            sold_qty=0,
            sold_value=0.0,
            reason="",
            max_hold=_resolve_hold(prof, od, C),
            hold_until=None,
            target_off=False,
            prof=prof,
            sig_date=od["date"],
            equity_at_entry=equity_ref,
            actions=[],
            rb_due=False,
        )
        positions[sym] = pos
        return pos

    equity_prev = cap0
    for d in dates:
        # A) exits on today's bar for positions opened before today
        for sym in list(positions):
            j = book.idx(sym, d)
            if j is not None:
                bar_exits(positions[sym], j, d)
        # B) fills of pending buy orders
        keep = []
        for od in sorted(pending, key=lambda o: o["prio"]):
            sym = od["symbol"]
            if sym in positions:
                continue
            j = book.idx(sym, d)
            od["age"] = od.get("age", 0) + 1
            if j is None:
                if od["age"] <= od["valid"] + 5:
                    keep.append(od)
                continue
            x = book.s[sym]
            o, h, lo = x["o"][j], x["h"][j], x["l"][j]
            how = "OPEN"
            if od["kind"] == "MKT":
                raw = o
            elif od["kind"] == "STOP":
                raw = max(o, od["price"]) if h >= od["price"] else None
                how = "OPEN" if o >= od["price"] else "STOP"
            else:
                raw = min(o, od["price"]) if lo <= od["price"] else None
                how = "OPEN" if o <= od["price"] else "LIMIT"
            if raw is None:
                od["waited"] += 1
                if od["waited"] < od["valid"]:
                    keep.append(od)
                continue
            if len(positions) >= max_pos:
                continue
            pos = open_pos(od, j, d, raw, equity_prev)
            if pos is not None:
                bar_exits(pos, j, d, entry=how)
        pending = keep
        # C) end-of-day management
        for sym in list(positions):
            j = book.idx(sym, d)
            if j is not None:
                eod(positions[sym], j, d)
        # D) mark to market
        inv = 0.0
        for sym, pos in positions.items():
            j = book.idx(sym, d)
            if j is not None:
                last_close[sym] = book.s[sym]["c"][j]
            inv += pos.shares * last_close.get(sym, pos.entry)
        equity = state["cash"] + inv
        curve.append((d, round(equity, 2), round(state["cash"], 2), len(positions), round(inv, 2)))
        equity_prev = equity
        # E) new buy orders from today's signals (fill from tomorrow)
        todays = by_date.get(d, [])
        if todays:
            n_meth = {}
            for e in todays:
                n_meth[e["symbol"]] = n_meth.get(e["symbol"], 0) + 1
            best = {}
            for e in todays:
                k = (CONF_RANK.get(str(e.get("confidence")).upper(), 1), e.get("method") or "")
                if e["symbol"] not in best or k < best[e["symbol"]][0]:
                    best[e["symbol"]] = (k, e)
            waiting = {o["symbol"] for o in pending}
            for sym, (k, e) in best.items():
                if sym in positions or sym in waiting or not book.has(sym):
                    continue
                jd = book.idx(sym, d)
                close = e.get("close") or (book.s[sym]["c"][jd] if jd is not None else 0)
                turn = e.get("turnover")
                if turn is None and jd is not None:
                    turn = float(book.ind(sym, "turn20")[jd])
                if not close or close < C["MIN_PRICE"]:
                    continue
                if turn is not None and turn < C["MIN_TURNOVER"]:
                    continue
                prof = profile(e.get("method"))
                entry = e.get("entry")
                tick = prof.get("entry_tick") or 0.0
                if not entry or entry <= 0:
                    kind, price = "MKT", None
                elif prof.get("entry_kind") == "STOP" or entry > close * 1.002:
                    kind, price = "STOP", entry + tick
                elif entry < close * 0.98:
                    kind, price = "LIMIT", entry
                else:
                    kind, price = "MKT", None
                valid = int(prof.get("valid_bars") or C["ORDER_VALID_BARS"])
                if prof.get("valid_from_signal") and e.get("valid_bars"):
                    valid = int(e["valid_bars"])
                pending.append(
                    {
                        "symbol": sym,
                        "method": e.get("method"),
                        "date": d,
                        "kind": kind,
                        "price": price,
                        "stop": e.get("stop"),
                        "target": e.get("target"),
                        "time_exit": e.get("time_exit"),
                        "size_mult": e.get("size_mult") or 1.0,
                        "turnover": turn,
                        "prof": prof,
                        "waited": 0,
                        "valid": max(1, valid),
                        "prio": (d, k[0], -n_meth[sym], -(turn or 0), sym),
                    }
                )
            if len(pending) > C["MAX_PENDING"]:
                pending.sort(key=lambda o: o["prio"])
                pending = pending[: int(C["MAX_PENDING"])]
    open_list = []
    for sym, pos in positions.items():
        lc = last_close.get(sym, pos.entry)
        open_list.append(
            {
                "symbol": sym,
                "method": pos.method,
                "entry_date": pos.entry_date,
                "entry_price": round(pos.entry, 2),
                "shares": pos.shares,
                "stop": round(pos.stop, 2) if pos.stop else None,
                "last_close": round(float(lc), 2),
                "mtm_pnl": round(pos.shares * lc + pos.proceeds - pos.init_shares * pos.entry - pos.buy_cost, 2),
            }
        )
    return {"trades": trades, "curve": curve, "open": open_list, "capital": cap0}


# ============================================================
# STATS, MONTE CARLO, READINESS
# ============================================================
def _max_dd(values):
    peak = -1e18
    mdd = 0.0
    for v in values:
        v = float(v)
        peak = max(peak, v)
        if peak > 0:
            mdd = max(mdd, 1 - v / peak)
    return float(mdd)


def _pf(pnls):
    g = float(sum(p for p in pnls if p > 0))
    l_ = float(-sum(p for p in pnls if p < 0))
    if l_ == 0:
        return None if g == 0 else 99.0
    return g / l_


def _group(trades, key):
    out = {}
    for t in trades:
        out.setdefault(t.get(key) or "—", []).append(t)
    rows = []
    for k, lst in out.items():
        pn = [t["pnl"] for t in lst]
        rs = [t["r_mult"] for t in lst if t.get("r_mult") is not None]
        rows.append(
            {
                key: k,
                "trades": len(lst),
                "win_rate": round(sum(p > 0 for p in pn) / len(lst), 3),
                "pf": None if _pf(pn) is None else round(_pf(pn), 2),
                "avg_r": round(float(np.mean(rs)), 2) if rs else None,
                "pnl": round(sum(pn), 0),
            }
        )
    rows.sort(key=lambda r: -r["pnl"])
    return rows


def monte_carlo_dd(trades, runs=1000, seed=42):
    """Bad-luck test: reshuffle trade outcomes (with replacement) and
    measure the worst drawdown. Returns (dd95, worst_final_5pct)."""
    rets = [t["pnl"] / t["equity_at_entry"] for t in trades if t.get("equity_at_entry")]
    if len(rets) < 10 or int(runs) <= 0:
        return None, None
    rng = np.random.default_rng(seed)
    arr = np.array(rets)
    dds, finals = [], []
    for _ in range(int(runs)):
        path = np.cumprod(1 + rng.choice(arr, size=len(arr), replace=True))
        peak = np.maximum.accumulate(np.concatenate([[1.0], path]))
        dd = 1 - np.concatenate([[1.0], path]) / peak
        dds.append(float(dd.max()))
        finals.append(float(path[-1] - 1))
    return float(np.percentile(dds, 95)), float(np.percentile(finals, 5))


def compute_stats(res, bench=None, C=None):
    C = C or config()
    cap0 = res["capital"]
    trades = res["trades"]
    curve = res["curve"]
    st = {"capital": cap0, "trades": len(trades), "open": len(res["open"])}
    if not curve:
        st.update(final_equity=cap0, return_pct=0.0)
        return st
    eq = pd.Series([c[1] for c in curve], index=[c[0] for c in curve])
    inv = pd.Series([c[4] for c in curve], index=eq.index)
    final = float(eq.iloc[-1])
    days = max(1, (pd.Timestamp(eq.index[-1]) - pd.Timestamp(eq.index[0])).days)
    yrs = days / 365.25
    st["start"], st["end"] = eq.index[0], eq.index[-1]
    st["final_equity"] = round(final, 0)
    st["return_pct"] = round(final / cap0 - 1, 4)
    st["cagr"] = round((final / cap0) ** (1 / yrs) - 1, 4) if yrs >= 0.25 and final > 0 else None
    st["max_dd"] = round(_max_dd(eq.values), 4)
    r = eq.pct_change().dropna()
    if len(r) > 20 and r.std() > 0:
        st["sharpe"] = round(float(r.mean() / r.std() * math.sqrt(252)), 2)
        neg = r[r < 0]
        st["sortino"] = (
            round(float(r.mean() / neg.std() * math.sqrt(252)), 2) if len(neg) > 5 and neg.std() > 0 else None
        )
    st["calmar"] = round(st["cagr"] / st["max_dd"], 2) if st.get("cagr") is not None and st["max_dd"] > 0 else None
    st["exposure"] = round(float((inv / eq).mean()), 3)
    under = eq < eq.cummax()
    longest = cur = 0
    for u in under.values:
        cur = cur + 1 if u else 0
        longest = max(longest, cur)
    st["longest_underwater_days"] = int(longest)
    pn = [t["pnl"] for t in trades]
    if trades:
        wins = [t for t in trades if t["pnl"] > 0]
        losses = [t for t in trades if t["pnl"] <= 0]
        rs = [t["r_mult"] for t in trades if t.get("r_mult") is not None]
        st["win_rate"] = round(len(wins) / len(trades), 3)
        st["avg_win_pct"] = round(float(np.mean([t["pnl_pct"] for t in wins])), 4) if wins else None
        st["avg_loss_pct"] = round(float(np.mean([t["pnl_pct"] for t in losses])), 4) if losses else None
        pf = _pf(pn)
        st["pf"] = None if pf is None else round(pf, 2)
        st["expectancy_r"] = round(float(np.mean(rs)), 3) if rs else None
        st["expectancy_rs"] = round(float(np.mean(pn)), 0)
        st["avg_bars"] = round(float(np.mean([t["bars"] for t in trades])), 1)
        st["total_costs"] = round(sum(t["costs"] for t in trades), 0)
        st["best"] = max(trades, key=lambda t: t["pnl"])
        st["worst"] = min(trades, key=lambda t: t["pnl"])
        streak = mx = 0
        for t in sorted(trades, key=lambda t: t["exit_date"]):
            streak = streak + 1 if t["pnl"] <= 0 else 0
            mx = max(mx, streak)
        st["max_losing_streak"] = mx
        dd95, worst5 = monte_carlo_dd(trades, C["MC_RUNS"])
        st["mc_dd95"] = None if dd95 is None else round(dd95, 4)
        st["mc_worst5_return"] = None if worst5 is None else round(worst5, 4)
    yearly = {}
    for y, g in eq.groupby(eq.index.str[:4]):
        prev = eq[eq.index < g.index[0]]
        base = float(prev.iloc[-1]) if len(prev) else cap0
        yearly[y] = {"return": round(float(g.iloc[-1]) / base - 1, 4), "days": len(g)}
    st["yearly"] = yearly
    monthly = {}
    for m_, g in eq.groupby(eq.index.str[:7]):
        prev = eq[eq.index < g.index[0]]
        base = float(prev.iloc[-1]) if len(prev) else cap0
        monthly[m_] = round(float(g.iloc[-1]) / base - 1, 4)
    st["monthly"] = monthly
    if bench is not None and len(bench):
        b = bench[(bench.index >= eq.index[0]) & (bench.index <= eq.index[-1])]
        if len(b) > 20:
            br = float(b.iloc[-1] / b.iloc[0] - 1)
            st["bench_return"] = round(br, 4)
            st["bench_cagr"] = round((1 + br) ** (1 / yrs) - 1, 4) if yrs >= 0.25 else None
            st["bench_max_dd"] = round(_max_dd(b.values), 4)
    return st


def readiness(st, live=None, C=None):
    """Plain-English real-money checklist."""
    C = C or config()
    checks = []

    def add(name, ok, value, need, why):
        if isinstance(value, np.generic):
            value = value.item()
        checks.append({"name": name, "ok": bool(ok), "value": value, "need": need, "why": why})

    n = st.get("trades", 0)
    add(
        "Enough trades",
        n >= C["READY_MIN_TRADES"],
        n,
        f">= {C['READY_MIN_TRADES']}",
        "Fewer trades = the result could be luck.",
    )
    pf = st.get("pf")
    add(
        "Profit factor after costs",
        pf is not None and pf >= C["READY_MIN_PF"],
        pf,
        f">= {C['READY_MIN_PF']}",
        "Rs won per Rs lost, after STT, charges and slippage.",
    )
    dd = st.get("max_dd")
    add(
        "Worst fall (max drawdown)",
        dd is not None and dd <= C["READY_MAX_DD"],
        None if dd is None else f"{dd:.1%}",
        f"<= {C['READY_MAX_DD']:.0%}",
        "Could you sit through this fall without quitting?",
    )
    if st.get("bench_cagr") is not None and st.get("cagr") is not None:
        add(
            "Beats Nifty buy-and-hold",
            st["cagr"] > st["bench_cagr"],
            f"{st['cagr']:.1%} vs {st['bench_cagr']:.1%}",
            "higher",
            "If not, an index fund is less work.",
        )
    yrs = [v for v in (st.get("yearly") or {}).values() if v["days"] >= 60]
    if len(yrs) >= 2:
        share = sum(v["return"] > 0 for v in yrs) / len(yrs)
        add(
            "Profitable in most years",
            share >= C["READY_MIN_YEARS_POS"],
            f"{sum(v['return'] > 0 for v in yrs)}/{len(yrs)} years",
            f">= {C['READY_MIN_YEARS_POS']:.0%}",
            "One lucky year should not carry the whole result.",
        )
    mc = st.get("mc_dd95")
    add(
        "Bad-luck test (Monte Carlo)",
        mc is not None and mc <= C["READY_MC_DD95"],
        None if mc is None else f"{mc:.1%}",
        f"<= {C['READY_MC_DD95']:.0%}",
        "95% of reshuffled trade orders stay above this drawdown.",
    )
    wc = st.get("worst_case")
    if wc and n:
        wpf = wc.get("pf")
        add(
            "Survives worst-case fills",
            wpf is not None and wpf >= 1.0,
            f"PF {wpf} ({_pct(wc.get('return_pct'))})",
            "PF >= 1.0",
            "Daily bars hide whether the high or the low came first; this "
            "re-runs every trade assuming the stop always came first.",
        )
    backtest_ok = all(c["ok"] for c in checks)
    ln = (live or {}).get("trades", 0)
    lpf = (live or {}).get("pf")
    live_ok = ln >= C["READY_MIN_LIVE_TRADES"] and (lpf or 0) >= 1.0
    add(
        "Live paper trading confirms it",
        live_ok,
        f"{ln} trades" + (f", PF {lpf}" if lpf is not None else ""),
        f">= {C['READY_MIN_LIVE_TRADES']} trades, PF >= 1.0",
        "The future must agree with the past before real money.",
    )
    if n == 0:
        verdict, code = "NO DATA — no trades yet", "NO_DATA"
    elif backtest_ok and live_ok:
        verdict, code = ("READY — start small (25% of planned capital), scale up after 3 good months"), "READY"
    elif backtest_ok:
        verdict, code = (
            (f"PAPER-TRADE FIRST — backtest passed; needs {C['READY_MIN_LIVE_TRADES']}+ live paper trades"),
            "PAPER",
        )
    else:
        failed = [c["name"] for c in checks[:-1] if not c["ok"]]
        verdict, code = "NOT READY — fix: " + "; ".join(failed), "NOT_READY"
    return {"verdict": verdict, "code": code, "checks": checks}


# ============================================================
# RUN ALL PLAYERS + PERSIST
# ============================================================
def _load_signals(conn, source, slugs=None, start=None, end=None):
    q = (
        "SELECT player, date, symbol, method, kind, entry, stop, target, "
        "confidence, time_exit, valid_bars, close, atr, turnover, size_mult "
        "FROM league_signals WHERE source=?"
    )
    args = [source]
    if slugs:
        q += f" AND player IN ({','.join('?' * len(slugs))})"
        args += list(slugs)
    if start:
        q += " AND date >= ?"
        args.append(start)
    if end:
        q += " AND date <= ?"
        args.append(end)
    cols = [
        "player",
        "date",
        "symbol",
        "method",
        "kind",
        "entry",
        "stop",
        "target",
        "confidence",
        "time_exit",
        "valid_bars",
        "close",
        "atr",
        "turnover",
        "size_mult",
    ]
    out = {}
    for r in conn.execute(q, args):
        d = dict(zip(cols, r, strict=False))
        out.setdefault(d["player"], []).append(d)
    return out


def _run_id(mode, exit_mode):
    return f"{mode}-{exit_mode}"


def simulate_all(mode="backtest", exit_mode="book", slugs=None, quiet=False, save=True):
    """Simulate every player from stored signals and save the run."""
    C = config()
    conn = _conn()
    source = "replay" if mode == "backtest" else "live"
    start = None
    if mode == "live" and C.get("LIVE_START"):
        start = C["LIVE_START"]
    q = (
        "SELECT player, MIN(date), COUNT(*) FROM league_signals "
        "WHERE source=?" + (" AND date >= ?" if start else "") + " GROUP BY player"
    )
    have = {p: (f, n) for p, f, n in conn.execute(q, [source] + ([start] if start else []))}
    if slugs:
        have = {p: v for p, v in have.items() if p in slugs}
    if not have:
        conn.close()
        return {"error": f"no {source} signals stored yet"}
    # who plays: live = everyone (flat Rs 10 lakh until the first signal);
    # backtest = every player that was replayed, even with 0 signals
    if mode == "live":
        entrants = {p["slug"] for p in players()}
    else:
        entrants = set(have) | {r[0] for r in conn.execute("SELECT DISTINCT player FROM league_progress")}
    if slugs:
        entrants &= set(slugs)
    start = start or min(v[0] for v in have.values())
    end = _last_price_date(conn)
    q = "SELECT DISTINCT symbol FROM league_signals WHERE source=? AND date >= ?"
    args = [source, start]
    if slugs:
        q += f" AND player IN ({','.join('?' * len(slugs))})"
        args += list(slugs)
    syms = {r[0] for r in conn.execute(q, args)}
    book = PriceBook.from_db(conn, syms, start)
    cal = [d for d in book.dates() if start <= d <= end]
    bench, label = load_benchmark(conn, start, end, fetch=True)
    levels = regime_levels(bench)
    live_stats = {}
    if mode == "backtest":
        for p, stats_json in conn.execute(
            "SELECT player, stats FROM league_runs WHERE run_id=?", (_run_id("live", exit_mode),)
        ):
            with contextlib.suppress(Exception):
                live_stats[p] = json.loads(stats_json)
    results = {}
    roster = [p["slug"] for p in players()]
    for slug in roster:
        if slugs and slug not in slugs:
            continue
        if mode == "backtest" and slug not in BACKTESTABLE:
            continue
        if slug not in entrants:
            continue
        lst = _load_signals(conn, source, [slug], start=start).get(slug, []) if slug in have else []
        entries = [s for s in lst if s["kind"] == "ENTRY"]
        exits = {(s["date"], s["symbol"]) for s in lst if s["kind"] == "EXIT"}
        base = exit_profile(slug, exit_mode)

        def prof(method, _b=base):
            return _b

        res = simulate(slug, entries, exits, book, cal, prof, C, levels=levels)
        st = compute_stats(res, bench, C)
        if mode == "backtest" and str(C.get("INTRABAR")).lower() != "worst":
            Cw = dict(C, INTRABAR="worst", MC_RUNS=0)
            sw = compute_stats(simulate(slug, entries, exits, book, cal, prof, Cw, levels=levels), bench, Cw)
            st["worst_case"] = {k: sw.get(k) for k in ("pf", "return_pct", "cagr", "max_dd", "win_rate", "trades")}
        st["signals"] = len(entries)
        st["by_method"] = _group(res["trades"], "method")
        st["by_regime"] = _group(res["trades"], "regime")
        st["by_reason"] = _group(res["trades"], "reason")
        rd = readiness(st, live_stats.get(slug), C)
        st["readiness"] = rd
        st["exit_rules"] = base.get("why", "")
        results[slug] = (res, st)
    if save:
        rid = _run_id(mode, exit_mode)
        now = _now()
        for t in ("league_runs", "league_trades", "league_equity", "league_open"):
            conn.execute(f"DELETE FROM {t} WHERE run_id=?", (rid,))
        meta = {
            "benchmark": label,
            "start": start,
            "end": end,
            "days": len(cal),
            "stocks": len(syms),
            "config": C,
            "bench_return": None,
        }
        if len(bench):
            b = bench[(bench.index >= start) & (bench.index <= end)]
            if len(b) > 1:
                meta["bench_return"] = round(float(b.iloc[-1] / b.iloc[0] - 1), 4)
        conn.execute(
            "INSERT OR REPLACE INTO league_runs VALUES (?,?,?,?,?,?,?,?)",
            (rid, "_meta", mode, exit_mode, start, end, now, _dumps(meta)),
        )
        for slug, (res, st) in results.items():
            conn.execute(
                "INSERT OR REPLACE INTO league_runs VALUES (?,?,?,?,?,?,?,?)",
                (rid, slug, mode, exit_mode, start, end, now, _dumps(st)),
            )
            conn.executemany(
                "INSERT INTO league_trades VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [
                    (
                        rid,
                        slug,
                        t["symbol"],
                        t["method"],
                        t["entry_date"],
                        t["entry_price"],
                        t["exit_date"],
                        t["exit_price"],
                        t["shares"],
                        t["pnl"],
                        t["pnl_pct"],
                        t["r_mult"],
                        t["costs"],
                        t["reason"],
                        t["bars"],
                        t["regime"],
                    )
                    for t in res["trades"]
                ],
            )
            conn.executemany(
                "INSERT OR REPLACE INTO league_equity VALUES (?,?,?,?,?,?)",
                [(rid, slug, c[0], c[1], c[2], c[3]) for c in res["curve"]],
            )
            conn.executemany(
                "INSERT INTO league_open VALUES (?,?,?,?,?,?,?,?,?,?)",
                [
                    (
                        rid,
                        slug,
                        o["symbol"],
                        o["method"],
                        o["entry_date"],
                        o["entry_price"],
                        o["shares"],
                        o["stop"],
                        o["last_close"],
                        o["mtm_pnl"],
                    )
                    for o in res["open"]
                ],
            )
        conn.commit()
    conn.close()
    if not quiet:
        print_table(mode, exit_mode)
    return {"run_id": _run_id(mode, exit_mode), "players": len(results), "start": start, "end": end}


# ============================================================
# READ BACK (CLI + API)
# ============================================================
def _run_rows(conn, mode, exit_mode):
    rid = _run_id(mode, exit_mode)
    meta, per = None, {}
    for p, start, end, created, stats in conn.execute(
        "SELECT player, start, end, created_at, stats FROM league_runs WHERE run_id=?", (rid,)
    ):
        try:
            d = json.loads(stats)
        except Exception:
            d = {}
        if p == "_meta":
            meta = dict(d, created_at=created, start=start, end=end)
        else:
            per[p] = d
    return meta, per


def signal_genome(conn, mode="backtest", min_trades=10):
    """Compare method/regime outcomes under common and book exits.

    This is descriptive, not predictive: it only includes closed, executed
    trades and never treats small samples as established evidence.
    """
    grouped = {}
    for exit_mode in ("common", "book"):
        run_id = _run_id(mode, exit_mode)
        rows = conn.execute(
            "SELECT player, method, COALESCE(regime, 'unclassified'), "
            "COUNT(*), SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END), "
            "SUM(pnl), SUM(CASE WHEN pnl > 0 THEN pnl ELSE 0 END), "
            "SUM(CASE WHEN pnl < 0 THEN -pnl ELSE 0 END), AVG(r_mult) "
            "FROM league_trades WHERE run_id=? "
            "GROUP BY player, method, COALESCE(regime, 'unclassified')",
            (run_id,),
        ).fetchall()
        for player, method, regime, count, wins, pnl, gross_win, gross_loss, avg_r in rows:
            cell = grouped.setdefault((player, method, regime), {})
            cell[exit_mode] = {
                "trades": int(count),
                "win_rate": round(wins / count, 3) if count else None,
                "pf": (round(gross_win / gross_loss, 2) if gross_loss else (99.0 if gross_win else None)),
                "avg_r": round(avg_r, 3) if avg_r is not None else None,
                "pnl": round(pnl, 0),
            }

    names = {p["slug"]: p["name"] for p in players()}
    cells = []
    for (player, method, regime), outcomes in grouped.items():
        common = outcomes.get("common")
        if not common or common["trades"] < min_trades:
            continue
        cells.append(
            {
                "player": player,
                "name": names.get(player, player),
                "method": method,
                "regime": regime,
                "common": common,
                "book": outcomes.get("book"),
            }
        )
    cells.sort(
        key=lambda cell: (cell["common"]["avg_r"] is None, -(cell["common"]["avg_r"] or 0), -cell["common"]["trades"])
    )
    ranked = [cell for cell in cells if cell["common"]["avg_r"] is not None]
    return {
        "minimum_trades": min_trades,
        "cells": cells,
        "leaders": ranked[:8],
        "weak_spots": list(reversed(ranked[-6:])),
        "note": (
            "Historical descriptive results, not a forecast. Shared exits "
            "make entry styles more comparable, but portfolio capacity and "
            "fill timing still affect realized trades. The replay uses "
            "today's listed universe and does not have point-in-time "
            "fundamentals."
        ),
    }


def overview(mode="backtest", exit_mode="book"):
    """League table + our system's readiness, for the API / UI."""
    conn = _conn()
    try:
        meta, per = _run_rows(conn, mode, exit_mode)
        genome = signal_genome(conn, mode)
    finally:
        conn.close()
    rows = []
    for p in players():
        st = per.get(p["slug"])
        base = {
            "slug": p["slug"],
            "name": p["name"],
            "book": p["book"],
            "pillar": p["pillar"],
            "backtest": p["backtest"],
        }
        if st is None:
            why = p["why_not"] if (mode == "backtest" and not p["backtest"]) else "no signals yet"
            rows.append(dict(base, playing=False, why_not=why))
            continue
        rd = st.get("readiness") or {}
        rows.append(
            dict(
                base,
                playing=True,
                final_equity=st.get("final_equity"),
                return_pct=st.get("return_pct"),
                cagr=st.get("cagr"),
                max_dd=st.get("max_dd"),
                win_rate=st.get("win_rate"),
                pf=st.get("pf"),
                trades=st.get("trades", 0),
                open=st.get("open", 0),
                signals=st.get("signals", 0),
                exposure=st.get("exposure"),
                sharpe=st.get("sharpe"),
                expectancy_r=st.get("expectancy_r"),
                total_costs=st.get("total_costs"),
                mc_dd95=st.get("mc_dd95"),
                verdict=rd.get("verdict"),
                verdict_code=rd.get("code"),
            )
        )
    playing = sorted([r for r in rows if r["playing"]], key=lambda r: -(r.get("final_equity") or 0))
    for i, r in enumerate(playing, 1):
        r["rank"] = i
    rows = playing + [r for r in rows if not r["playing"]]
    home = per.get(HOME)
    return {
        "mode": mode,
        "exit": exit_mode,
        "run": meta,
        "rows": rows,
        "genome": genome,
        "home": None
        if home is None
        else {
            "readiness": home.get("readiness"),
            "stats": {
                k: home.get(k)
                for k in (
                    "final_equity",
                    "return_pct",
                    "cagr",
                    "max_dd",
                    "pf",
                    "win_rate",
                    "trades",
                    "expectancy_r",
                    "mc_dd95",
                    "bench_cagr",
                    "bench_return",
                    "total_costs",
                    "sharpe",
                )
            },
            "exit_rules": home.get("exit_rules"),
        },
        "capital": config()["CAPITAL"],
    }


def player_detail(slug, mode="backtest", exit_mode="book", n_trades=150):
    conn = _conn()
    try:
        rid = _run_id(mode, exit_mode)
        meta, per = _run_rows(conn, mode, exit_mode)
        st = per.get(slug)
        pm = player_meta(slug)
        if st is None:
            return {
                "slug": slug,
                "name": pm["name"],
                "book": pm["book"],
                "playing": False,
                "run": meta,
                "exit_rules": exit_profile(slug, exit_mode).get("why", ""),
            }
        eq = conn.execute(
            "SELECT date, equity FROM league_equity WHERE run_id=? AND player=? ORDER BY date", (rid, slug)
        ).fetchall()
        step = max(1, len(eq) // 500)
        curve = [[d, round(v, 0)] for d, v in eq[::step]]
        if eq and curve[-1][0] != eq[-1][0]:
            curve.append([eq[-1][0], round(eq[-1][1], 0)])
        bench_curve = []
        if eq:
            bench, _label = load_benchmark(conn, eq[0][0], eq[-1][0], fetch=False)
            b = bench[(bench.index >= eq[0][0]) & (bench.index <= eq[-1][0])]
            if len(b) > 1:
                cap = st.get("capital") or config()["CAPITAL"]
                bstep = max(1, len(b) // 500)
                bench_curve = [[d, round(cap * v / b.iloc[0], 0)] for d, v in b.iloc[::bstep].items()]
        cols = [
            "symbol",
            "method",
            "entry_date",
            "entry_price",
            "exit_date",
            "exit_price",
            "shares",
            "pnl",
            "pnl_pct",
            "r_mult",
            "costs",
            "reason",
            "bars",
            "regime",
        ]
        trades = [
            dict(zip(cols, r, strict=False))
            for r in conn.execute(
                f"SELECT {', '.join(cols)} FROM league_trades WHERE run_id=? AND "
                "player=? ORDER BY exit_date DESC LIMIT ?",
                (rid, slug, n_trades),
            )
        ]
        ocols = ["symbol", "method", "entry_date", "entry_price", "shares", "stop", "last_close", "mtm_pnl"]
        opens = [
            dict(zip(ocols, r, strict=False))
            for r in conn.execute(
                f"SELECT {', '.join(ocols)} FROM league_open WHERE run_id=? AND player=? ORDER BY entry_date",
                (rid, slug),
            )
        ]
    finally:
        conn.close()
    return {
        "slug": slug,
        "name": pm["name"],
        "book": pm["book"],
        "pillar": pm["pillar"],
        "playing": True,
        "run": meta,
        "stats": {
            k: v for k, v in st.items() if k not in ("by_method", "by_regime", "by_reason", "readiness", "monthly")
        },
        "monthly": st.get("monthly"),
        "readiness": st.get("readiness"),
        "by_method": st.get("by_method"),
        "by_regime": st.get("by_regime"),
        "by_reason": st.get("by_reason"),
        "exit_rules": st.get("exit_rules"),
        "equity": curve,
        "bench": bench_curve,
        "bench_label": (meta or {}).get("benchmark"),
        "trades": trades,
        "open": opens,
    }


def status():
    """Coverage of stored signals, replay progress, runs, background jobs."""
    conn = _conn()
    try:
        last = _last_price_date(conn)
        sig = {}
        for src, p, n, f, l in conn.execute(
            "SELECT source, player, COUNT(*), MIN(date), MAX(date) FROM "
            "league_signals WHERE kind='ENTRY' GROUP BY source, player"
        ):
            sig[(src, p)] = (n, f, l)
        prog = {}
        for p, n, f, l, h in conn.execute(
            "SELECT player, COUNT(*), MIN(first_date), MAX(last_date), "
            "GROUP_CONCAT(DISTINCT code_hash) FROM league_progress "
            "GROUP BY player"
        ):
            prog[p] = (n, f, l, h or "")
        runs = [
            {"run_id": r, "created_at": c, "start": s, "end": e}
            for r, c, s, e in conn.execute(
                "SELECT run_id, created_at, start, end FROM league_runs WHERE player='_meta' ORDER BY run_id"
            )
        ]
    finally:
        conn.close()
    out = []
    for p in players():
        s = p["slug"]
        rp = sig.get(("replay", s), (0, None, None))
        lv = sig.get(("live", s), (0, None, None))
        pr = prog.get(s)
        stale = bool(pr and pr[3] and _code_hash(s) not in pr[3].split(","))
        out.append(
            {
                "slug": s,
                "name": p["name"],
                "backtest": p["backtest"],
                "replay_signals": rp[0],
                "replay_first": rp[1],
                "replay_last": rp[2],
                "replay_stocks": pr[0] if pr else 0,
                "replay_from": pr[1] if pr else None,
                "replay_to": pr[2] if pr else None,
                "code_changed": stale,
                "live_signals": lv[0],
                "live_first": lv[1],
                "live_last": lv[2],
            }
        )
    return {
        "last_price_date": last,
        "players": out,
        "runs": runs,
        "replay_job": replay_job_state(),
        "sim_job": dict(_SIM_STATE),
    }


def _pct(x, dec=1):
    return "—" if x is None else f"{x * 100:+.{dec}f}%"


def print_table(mode="backtest", exit_mode="book"):
    ov = overview(mode, exit_mode)
    run = ov["run"]
    if not run:
        print(
            f"No {mode} run yet. "
            + ("Run: python trader_league.py replay" if mode == "backtest" else "Run: python trader_league.py live")
        )
        return
    br = run.get("bench_return")
    print()
    print(
        f"TRADER LEAGUE — {mode.upper()} · {exit_mode} exits · "
        f"{run['start']} -> {run['end']} ({run.get('days')} days) · "
        f"benchmark {run.get('benchmark')} {_pct(br)}"
    )
    print(
        f"{'#':>2}  {'Player':<28}{'Final value':>15}{'Return':>9}"
        f"{'CAGR':>8}{'MaxDD':>8}{'Win%':>6}{'PF':>6}{'Trades':>7}  Verdict"
    )
    for r in ov["rows"]:
        if not r["playing"]:
            continue
        pf = "—" if r["pf"] is None else f"{r['pf']:.2f}"
        wr = "—" if r["win_rate"] is None else f"{r['win_rate'] * 100:.0f}"
        cg = "—" if r["cagr"] is None else f"{r['cagr'] * 100:.1f}%"
        dd = "—" if r["max_dd"] is None else f"{r['max_dd'] * 100:.1f}%"
        name = ("* " if r["slug"] == HOME else "") + r["name"]
        print(
            f"{r['rank']:>2}  {name[:28]:<28}{inr(r['final_equity']):>15}"
            f"{_pct(r['return_pct']):>9}{cg:>8}{dd:>8}{wr:>6}{pf:>6}"
            f"{r['trades']:>7}  {(r['verdict'] or '').split(' — ')[0]}"
        )
    idle = [r["name"] for r in ov["rows"] if not r["playing"]]
    if idle:
        print(f"Not playing here: {', '.join(idle)}")
    print(
        "(* = our system. Costs: STT, stamp, exchange, SEBI, GST, DP, "
        f"{config()['SLIPPAGE_PCT']:.1%} slippage per side)"
    )


def print_ready(mode="backtest", exit_mode="book"):
    _meta, per = (lambda c: (_run_rows(c, mode, exit_mode), c.close())[0])(_conn())
    st = per.get(HOME)
    print()
    if not st:
        print("Our system has no backtest yet. Run: python trader_league.py replay --players home")
        return
    rd = st["readiness"]
    print("IS OUR SYSTEM READY FOR REAL MONEY?")
    print(
        f"  Rs 10,00,000 -> {inr(st.get('final_equity'))} "
        f"({_pct(st.get('return_pct'))}) over {st.get('start')} -> "
        f"{st.get('end')}, {st.get('trades')} trades"
    )
    for c in rd["checks"]:
        print(f"  [{'PASS' if c['ok'] else 'FAIL'}] {c['name']:<32} {c['value']!s:<22} need {c['need']}")
    print(f"  VERDICT: {rd['verdict']}")
    print(f"  Exit rules used: {st.get('exit_rules')}")


def print_player(slug, mode="backtest", exit_mode="book"):
    d = player_detail(slug, mode, exit_mode, n_trades=15)
    print()
    if not d.get("playing"):
        print(f"{d['name']}: no {mode} results yet.")
        return
    s = d["stats"]
    print(f"{d['name']} — {d['book']}")
    print(f"  Exit rules: {d['exit_rules']}")
    print(
        f"  Final {inr(s.get('final_equity'))} ({_pct(s.get('return_pct'))})"
        f" · CAGR {_pct(s.get('cagr'))} · max DD {_pct(s.get('max_dd'))}"
        f" · Sharpe {s.get('sharpe')} · PF {s.get('pf')}"
    )
    print(
        f"  Trades {s.get('trades')} · win {_pct(s.get('win_rate'), 0)} · "
        f"avg R {s.get('expectancy_r')} · costs {inr(s.get('total_costs'))}"
        f" · exposure {_pct(s.get('exposure'), 0)}"
    )
    print("  By method:")
    for m in (d["by_method"] or [])[:12]:
        print(
            f"    {str(m['method'])[:40]:<40} n={m['trades']:<4} "
            f"win {m['win_rate'] * 100:3.0f}%  PF {m['pf']}  "
            f"avgR {m['avg_r']}  {inr(m['pnl'])}"
        )
    print("  By market mood at entry:")
    for m in d["by_regime"] or []:
        print(
            f"    {m['regime']!s:<14} n={m['trades']:<4} win {m['win_rate'] * 100:3.0f}%  PF {m['pf']}  {inr(m['pnl'])}"
        )
    print("  Last trades:")
    for t in d["trades"][:10]:
        print(f"    {t['exit_date']} {t['symbol']:<12} {t['reason']:<18} {_pct(t['pnl_pct'])}  R {t['r_mult']}")


# ============================================================
# LIVE LEAGUE — nightly
# ============================================================
def _sym_info(conn, sym, d, cache):
    if sym in cache:
        return cache[sym]
    rows = conn.execute(
        "SELECT date, high, low, close, volume FROM prices_daily WHERE "
        "symbol=? AND date<=? ORDER BY date DESC LIMIT 25",
        (sym, d),
    ).fetchall()
    info = None
    if rows and str(rows[0][0])[:10] == d:
        rows = list(reversed(rows))
        c = np.array([r[3] or 0 for r in rows], float)
        h = np.array([r[1] or 0 for r in rows], float)
        lo = np.array([r[2] or 0 for r in rows], float)
        v = np.array([r[4] or 0 for r in rows], float)
        prev = np.concatenate([[c[0]], c[:-1]])
        tr = np.maximum.reduce([h - lo, np.abs(h - prev), np.abs(lo - prev)])
        info = (float(c[-1]), float(tr[-14:].mean()), float((c[-20:] * v[-20:]).mean()))
    cache[sym] = info
    return info


def collect_live(slugs=None):
    """Store today's signals from every trader + our Swing Desk."""
    conn = _conn()
    d = _last_price_date(conn)
    report = {"date": d}
    cache = {}
    try:
        import traders

        for t in traders.REGISTRY:
            if slugs and t.SLUG not in slugs:
                continue
            t0 = time.time()
            try:
                sigs = t.scan(conn=conn)
            except Exception as e:
                report[t.SLUG] = f"error: {e}"
                log.warning(f"live scan {t.SLUG} failed: {e}")
                continue
            rows = []
            for s in sigs or []:
                kind = classify(s)
                if not kind or not s.get("symbol"):
                    continue
                info = _sym_info(conn, s["symbol"], d, cache)
                if info is None:
                    continue
                hold, valid = _parse_time_exit(s)
                rows.append(
                    (
                        "live",
                        t.SLUG,
                        d,
                        s["symbol"],
                        str(s.get("method") or "?"),
                        kind,
                        _f(s.get("entry")),
                        _f(s.get("stop")),
                        _f(s.get("target")),
                        str(s.get("confidence") or "MED"),
                        hold,
                        valid,
                        info[0],
                        info[1],
                        info[2],
                        1.0,
                        _now(),
                    )
                )
            conn.execute("DELETE FROM league_signals WHERE source='live' AND player=? AND date=?", (t.SLUG, d))
            conn.executemany("INSERT OR REPLACE INTO league_signals VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
            conn.commit()
            report[t.SLUG] = f"{len(rows)} signals ({time.time() - t0:.0f}s)"
        if not slugs or HOME in slugs:
            try:
                rs = conn.execute(
                    "SELECT symbol, entry_trigger, stop, target, "
                    "COALESCE(mode,'SWING') FROM swing_signals "
                    "WHERE signal_date=?",
                    (d,),
                ).fetchall()
            except Exception:
                rs = conn.execute(
                    "SELECT symbol, entry_trigger, stop, target, 'SWING' FROM swing_signals WHERE signal_date=?", (d,)
                ).fetchall()
            size_mult = 1.0
            try:
                from regime import MarketRegime

                size_mult = float(MarketRegime.compute().size_mult)
            except Exception:
                pass
            rows = []
            for sym, trig, stop, tgt, mode in rs:
                info = _sym_info(conn, sym, d, cache)
                if info is None:
                    continue
                method = "all_weather" if str(mode).upper() == "ALL_WEATHER" else "gabani_pullback"
                rows.append(
                    (
                        "live",
                        HOME,
                        d,
                        sym,
                        method,
                        "ENTRY",
                        _f(trig),
                        _f(stop),
                        _f(tgt),
                        "HIGH",
                        None,
                        None,
                        info[0],
                        info[1],
                        info[2],
                        size_mult,
                        _now(),
                    )
                )
            conn.execute("DELETE FROM league_signals WHERE source='live' AND player=? AND date=?", (HOME, d))
            conn.executemany("INSERT OR REPLACE INTO league_signals VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
            conn.commit()
            report[HOME] = f"{len(rows)} signals from swing_signals"
    finally:
        conn.close()
    log.info(f"league live collect: {report}")
    return report


def run_live():
    """Nightly job: collect today's signals, re-simulate the live league."""
    rep = collect_live()
    for ex in ("book", "common"):
        try:
            simulate_all("live", ex, quiet=True)
        except Exception as e:
            log.exception(f"live simulate ({ex}) failed: {e}")
    return rep


def scorecard_text(mode=None):
    """Plain-text weekly scorecard (Telegram)."""
    for m in [mode] if mode else ["live", "backtest"]:
        ov = overview(m, "book")
        if ov["run"]:
            break
    else:
        return None
    run = ov["run"]
    play = [r for r in ov["rows"] if r["playing"]]
    if not play:
        return None
    title = "LIVE paper league" if m == "live" else "BACKTEST (pre-season)"
    lines = [f"🏆 TRADER LEAGUE — {title}", f"{run['start']} → {run['end']} · ₹10 lakh each · after costs", ""]
    if len({round(r.get("final_equity") or 0) for r in play}) == 1 and not any(
        r.get("trades") or r.get("open") for r in play
    ):
        lines += [
            f"Everyone is level at ₹10,00,000 ({len(play)} players).",
            "First paper trades fill on the next trading day.",
            "Terminal → 🏆 League tab for details.",
        ]
        return "\n".join(lines)
    for r in play[:6]:
        lines.append(
            f"{r['rank']:>2}. {r['name'][:22]:<22} {inr(r['final_equity']).replace('Rs ', '₹')} {_pct(r['return_pct'])}"
        )
    home = next((r for r in play if r["slug"] == HOME), None)
    if home:
        lines += [
            "",
            f"Our System: #{home['rank']} of {len(play)} · "
            f"{inr(home['final_equity']).replace('Rs ', '₹')} "
            f"({_pct(home['return_pct'])}) · {home['trades']} trades"
            + (f" · win {home['win_rate'] * 100:.0f}%" if home.get("win_rate") is not None else ""),
            f"Verdict: {(home.get('verdict') or '').split(' — ')[0]}",
        ]
    if run.get("bench_return") is not None:
        lines.append(f"{run.get('benchmark')} same period: {_pct(run['bench_return'])}")
    lines.append("Terminal → 🏆 League tab for details.")
    return "\n".join(lines)


def send_scorecard(mode=None):
    txt = scorecard_text(mode)
    if not txt:
        return False
    try:
        import alerts

        return bool(alerts.send(txt))
    except Exception as e:
        log.warning(f"scorecard send failed: {e}")
        return False


# ============================================================
# BACKGROUND JOBS (started from the web terminal)
# ============================================================
_SIM_STATE = {"running": False, "mode": None, "started": None, "finished": None, "error": None}
_REPLAY_PID = BASE / "data" / "league_replay.pid"
_REPLAY_LOG = BASE / "data" / "logs" / "league_replay.out"
_REPLAY_PROC = {}  # Popen of a replay started by this process


def start_simulation(mode="backtest"):
    """Re-simulate from stored signals in a thread (seconds, not hours)."""
    if _SIM_STATE["running"]:
        return {"started": False, "reason": "already running", "state": dict(_SIM_STATE)}

    def _run():
        _SIM_STATE.update(running=True, mode=mode, started=_now(), finished=None, error=None)
        try:
            for ex in ("book", "common"):
                r = simulate_all(mode, ex, quiet=True)
                if r and r.get("error"):
                    _SIM_STATE["error"] = r["error"]
        except Exception as e:
            _SIM_STATE["error"] = str(e)
            log.exception(f"simulation failed: {e}")
        finally:
            _SIM_STATE.update(running=False, finished=_now())

    threading.Thread(target=_run, daemon=True).start()
    return {"started": True, "state": dict(_SIM_STATE)}


def _pid_alive(pid):
    if not pid:
        return False
    if os.name == "nt":
        try:
            import ctypes

            h = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(pid))
            if not h:
                return False
            code = ctypes.c_ulong()
            ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(code))
            ctypes.windll.kernel32.CloseHandle(h)
            return code.value == 259  # STILL_ACTIVE
        except Exception:
            return False
    try:
        os.kill(int(pid), 0)
    except OSError:
        return False
    # kill(pid, 0) also "finds" a finished child nobody reaped (zombie) and,
    # after a reboot, an unrelated program that got the same pid. On Linux,
    # make sure it really is a live trader_league process.
    try:
        with open(f"/proc/{int(pid)}/cmdline", "rb") as fh:
            return b"trader_league" in fh.read()
    except OSError:
        return not os.path.isdir("/proc")  # no /proc (macOS): trust kill


def replay_job_state():
    st = {"running": False}
    proc = _REPLAY_PROC.get("proc")
    if proc is not None and proc.poll() is not None:
        _REPLAY_PROC.pop("proc", None)  # finished: reaped, pid is free
    try:
        if _REPLAY_PID.exists():
            info = json.loads(_REPLAY_PID.read_text())
            st.update(info)
            st["running"] = _pid_alive(info.get("pid"))
    except Exception:
        pass
    try:
        if _REPLAY_LOG.exists():
            tail = _REPLAY_LOG.read_text(encoding="utf-8", errors="replace").splitlines()[-6:]
            st["log_tail"] = tail
    except Exception:
        pass
    return st


def start_replay_process(years=None, symbols=None, workers=1, slugs=None, fresh=False):
    """Launch the (hours-long) replay as a low-priority background
    process so the web terminal stays responsive. Used by the League tab
    button and by `python trader_league.py replay --background` (SSH)."""
    import subprocess

    st = replay_job_state()
    if st.get("running"):
        return {"started": False, "reason": "a replay is already running", "state": st}
    C = config()
    years = float(years or C["REPLAY_YEARS"])
    symbols = int(symbols or C["REPLAY_SYMBOLS"])
    workers = max(1, int(workers or 1))
    cmd = [
        sys.executable,
        str(BASE / "trader_league.py"),
        "replay",
        "--years",
        f"{years:g}",
        "--symbols",
        str(symbols),
        "--workers",
        str(workers),
    ]
    if slugs:
        cmd += ["--players", ",".join(slugs)]
    if fresh:
        cmd.append("--fresh")
    _REPLAY_LOG.parent.mkdir(parents=True, exist_ok=True)
    out = open(_REPLAY_LOG, "w", encoding="utf-8")
    kw = {"cwd": str(BASE), "stdout": out, "stderr": subprocess.STDOUT}
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
    if os.name == "nt":
        kw["creationflags"] = 0x00004000  # BELOW_NORMAL_PRIORITY_CLASS
    else:
        # own session: closing SSH doesn't stop it. Low priority is set by
        # the replay itself (os.nice in main) — no preexec_fn in a
        # multi-threaded web server.
        kw["start_new_session"] = True
    try:
        proc = subprocess.Popen(cmd, env=env, **kw)
    finally:
        out.close()  # the child has its own copy
    _REPLAY_PROC["proc"] = proc
    info = {"pid": proc.pid, "started": _now(), "years": years, "symbols": symbols, "workers": workers}
    _REPLAY_PID.write_text(json.dumps(info))
    return {"started": True, "state": dict(info, running=True)}


def _claim_replay(years=None, symbols=None, workers=1):
    """A replay typed in SSH registers in the same pid file as the web
    button: the League tab shows it, and two replays never run at once."""
    st = replay_job_state()
    me = os.getpid()
    if st.get("running") and int(st.get("pid") or 0) != me:
        print(
            f"A replay is already running (pid {st.get('pid')}, started "
            f"{st.get('started')}). Not starting a second one."
        )
        print("See its progress: python trader_league.py status")
        return False
    if int(st.get("pid") or 0) != me:  # not launched by the button
        C = config()
        info = {
            "pid": me,
            "started": _now(),
            "years": float(years or C["REPLAY_YEARS"]),
            "symbols": int(symbols or C["REPLAY_SYMBOLS"]),
            "workers": max(1, int(workers or 1)),
        }
        try:
            _REPLAY_PID.parent.mkdir(parents=True, exist_ok=True)
            _REPLAY_PID.write_text(json.dumps(info))
        except Exception:
            pass
    return True


# ============================================================
# SELF-TEST — accounting must be right before real money
# ============================================================
def selftest(verbose=True):
    C = dict(DEFAULTS)
    results = []

    def check(name, cond, detail=""):
        results.append((name, bool(cond), detail))
        if verbose:
            print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))

    def mk_book(sym, bars):
        dates = [f"2025-01-{i + 1:02d}" for i in range(len(bars))]
        df = pd.DataFrame(bars, columns=["open", "high", "low", "close"])
        df["volume"] = 1e6
        df["date"] = dates
        return PriceBook({sym: df}), dates

    def run(bars, sig, prof, capital=1_000_000, extra_sigs=(), exits=()):
        book, dates = mk_book("TEST", bars)
        sigs = [
            dict(
                {
                    "date": dates[0],
                    "symbol": "TEST",
                    "method": "m",
                    "confidence": "HIGH",
                    "close": bars[0][3],
                    "turnover": 1e12,
                    "size_mult": 1.0,
                },
                **sig,
            )
        ]
        sigs += list(extra_sigs)
        return simulate("t", sigs, set(exits), book, dates, lambda m: prof, C, capital=capital), dates

    if verbose:
        print("Signal Genome:")
    import sqlite3

    genome_conn = sqlite3.connect(":memory:")
    genome_conn.execute(
        "CREATE TABLE league_trades (run_id TEXT, player TEXT, method TEXT, regime TEXT, pnl REAL, r_mult REAL)"
    )
    genome_conn.executemany(
        "INSERT INTO league_trades VALUES (?,?,?,?,?,?)",
        [
            ("backtest-common", "way_of_the_turtle", "breakout", "BULL", 100, 1.0),
            ("backtest-common", "way_of_the_turtle", "breakout", "BULL", -50, -0.5),
            ("backtest-book", "way_of_the_turtle", "breakout", "BULL", 200, 2.0),
        ],
    )
    genome = signal_genome(genome_conn, "backtest", min_trades=2)
    cell = genome["cells"][0] if genome["cells"] else {}
    check(
        "genome compares shared and book exits",
        cell.get("common", {}).get("trades") == 2
        and cell.get("book", {}).get("trades") == 1
        and cell.get("common", {}).get("win_rate") == 0.5
        and cell.get("common", {}).get("pf") == 2.0
        and cell.get("common", {}).get("avg_r") == 0.25,
    )
    check(
        "genome hides contexts below its sample floor",
        not signal_genome(genome_conn, "backtest", min_trades=3)["cells"],
    )
    genome_conn.close()
    if verbose:
        print("Costs (Rs 1,00,000 order):")
    buy = trade_costs("buy", 100000, C)
    sell = trade_costs("sell", 100000, C)
    exp_buy = 100 + 15 + 2.97 + 0.1 + 0.18 * (2.97 + 0.1)
    exp_sell = 100 + 2.97 + 0.1 + 0.18 * (2.97 + 0.1) + 15.93
    check("buy-side charges", abs(buy - exp_buy) < 0.01, f"{buy:.2f}")
    check("sell-side charges (incl. DP)", abs(sell - exp_sell) < 0.01, f"{sell:.2f}")
    C2 = dict(C, BROKERAGE_PER_ORDER=20, BROKERAGE_PCT=0.001)
    check(
        "brokerage = min(Rs 20, 0.1%)",
        abs(trade_costs("buy", 5000, C2) - trade_costs("buy", 5000, C) - 5 * 1.18) < 0.01,
    )
    check("Indian digit grouping", inr(1045120) == "Rs 10,45,120", inr(1045120))

    if verbose:
        print("Fills, stops, targets:")
    prof = {"stop": ("signal",), "target": ("signal",), "max_hold": None}
    flat = [(100, 101, 99, 100)]
    # 1) stop hit intraday
    res, _ = run(
        [*flat, (100, 101, 99.5, 100), (99, 99.5, 94, 95), *flat], {"entry": None, "stop": 95.0, "target": 120.0}, prof
    )
    t = res["trades"][0] if res["trades"] else {}
    fill = 100 * (1 + C["SLIPPAGE_PCT"])
    shares = min(int(10000 / (fill - 95)), int(200000 / fill))
    check("market entry at next open + slippage", abs(t.get("entry_price", 0) - fill) < 1e-6, f"{t.get('entry_price')}")
    check("1% risk sizing", t.get("shares") == shares, f"{t.get('shares')}")
    check("stop exit at stop price - slippage", abs(t.get("exit_price", 0) - 95 * (1 - C["SLIPPAGE_PCT"])) < 1e-6)
    exp_pnl = (
        shares * 95 * (1 - C["SLIPPAGE_PCT"])
        - trade_costs("sell", shares * 95 * (1 - C["SLIPPAGE_PCT"]), C)
        - shares * fill
        - trade_costs("buy", shares * fill, C)
    )
    check("P&L includes every charge", abs(t.get("pnl", 0) - exp_pnl) < 0.02, f"{t.get('pnl')} vs {exp_pnl:.2f}")
    check("loss is a bit worse than -1R", -1.15 < (t.get("r_mult") or 0) < -1.0, f"R {t.get('r_mult')}")
    # 2) gap through the stop
    res, _ = run([*flat, (100, 101, 99.5, 100), (90, 92, 89, 91), *flat], {"entry": None, "stop": 95.0}, prof)
    t = res["trades"][0]
    check(
        "gap below stop fills at the open (worse)",
        abs(t["exit_price"] - 90 * (1 - C["SLIPPAGE_PCT"])) < 1e-6 and t["reason"] == "STOP_GAP",
        t["reason"],
    )
    # 3) target
    res, _ = run(
        [*flat, (100, 101, 99.5, 100), (104, 111, 103, 110), *flat],
        {"entry": None, "stop": 95.0, "target": 110.0},
        prof,
    )
    t = res["trades"][0]
    check("target exit", t["reason"] == "TARGET" and abs(t["exit_price"] - 110 * (1 - C["SLIPPAGE_PCT"])) < 1e-6)
    # 4) stop AND target inside one bar: which came first?
    both = {"entry": None, "stop": 95.0, "target": 110.0}
    res, _ = run([*flat, (100, 101, 99.5, 100), (100, 111, 94, 105), *flat], both, prof)
    check("green bar (open-low-high-close): stop first", res["trades"][0]["reason"] == "STOP")
    res, _ = run([*flat, (100, 101, 99.5, 100), (100, 111, 94, 96), *flat], both, prof)
    check("red bar (open-high-low-close): target first", res["trades"][0]["reason"] == "TARGET")
    C["INTRABAR"] = "worst"
    res, _ = run([*flat, (100, 101, 99.5, 100), (100, 111, 94, 96), *flat], both, prof)
    C["INTRABAR"] = "path"
    check("INTRABAR=worst: stop always first", res["trades"][0]["reason"] == "STOP")
    # 4b) buy-stop filled during a green day whose low came before the fill
    bs = {"entry": 105.0, "stop": 100.0}
    res, _ = run(flat + [(102, 108, 99, 107)] + [(107, 108, 106, 107)] * 2, bs, prof)
    check("buy-stop day: a low BEFORE the fill can't stop you out", not res["trades"] and len(res["open"]) == 1)
    res, _ = run(flat + [(102, 108, 99, 101)] + [(107, 108, 106, 107)] * 2, bs, prof)
    check(
        "buy-stop day: a red day's later low does stop you out",
        len(res["trades"]) == 1 and res["trades"][0]["reason"] == "STOP",
    )
    # 5) buy-stop never triggers -> order expires, no trade
    res, _ = run(flat * 6, {"entry": 105.0, "stop": 95.0}, prof)
    check("untriggered buy-stop expires", not res["trades"] and not res["open"])
    # 6) buy-stop with a gap above the trigger fills at the open
    res, _ = run([*flat, (107, 108, 106, 107), *flat], {"entry": 105.0, "stop": 95.0}, prof)
    op = (res["open"] or [{}])[0]
    check(
        "gap above buy-stop fills at the open",
        abs(op.get("entry_price", 0) - round(107 * (1 + C["SLIPPAGE_PCT"]), 2)) < 0.011,
        f"{op.get('entry_price')}",
    )
    # 7) position cap: tight stop is capped at 20% of equity
    res, _ = run(flat + [(100, 101, 99.9, 100)] * 3, {"entry": None, "stop": 99.8}, prof)
    op = res["open"][0]
    check("20% position cap", op["shares"] == int(200000 / fill), op["shares"])
    # 8) time stop after N sessions at the close
    res, _ = run(flat * 8, {"entry": None, "stop": 90.0}, {"stop": ("signal",), "max_hold": 3})
    t = res["trades"][0]
    check("time stop at the close of session 3", t["reason"] == "TIME" and t["bars"] == 3, f"{t['reason']} {t['bars']}")
    # 9) turtle-style trailing low ratchets the stop up
    up = [(100 + i, 101 + i, 99.5 + i, 100.5 + i) for i in range(12)]
    down = [(110, 110, 100, 101), (101, 102, 95, 96)]
    res, _ = run(
        [(100, 101, 99, 100), *up, *down],
        {"entry": None, "stop": None},
        {"stop": ("atr", 2.0, 14), "trail_low": 3, "max_hold": None},
    )
    t = res["trades"][0]
    check("trailing-low stop exits in profit", t["reason"].startswith("TRAIL_STOP") and t["pnl"] > 0, t["reason"])
    # 10) tranche exits: 1/3 at +2R (stop to breakeven), then breakeven stop
    tr = [(100, 101, 99.5, 100), (100, 104, 99.8, 103.5), (103, 111, 102, 110), (109, 109.5, 99, 100)]
    res, _ = run(
        [(100, 101, 99, 100), *tr],
        {"entry": None, "stop": 97.0},
        {
            "stop": ("signal",),
            "max_hold": None,
            "partials": [(2.0, 0.33, "be"), (3.0, 0.33, "trail")],
            "trail_ma": ("ema", 10),
            "trail_needs_flag": True,
        },
    )
    t = res["trades"][0]
    check(
        "partial profits + breakeven stop", "PARTIAL" in t["reason"] and t["pnl"] > 0, f"{t['reason']} pnl {t['pnl']}"
    )
    # 11) max positions: 2 slots, 3 signals -> the 2 best confidence fill
    book = PriceBook(
        {
            s: pd.DataFrame(
                {
                    "date": [f"2025-02-0{i + 1}" for i in range(4)],
                    "open": [100.0] * 4,
                    "high": [101.0] * 4,
                    "low": [99.0] * 4,
                    "close": [100.0] * 4,
                    "volume": [1e6] * 4,
                }
            )
            for s in "ABC"
        }
    )
    dts = [f"2025-02-0{i + 1}" for i in range(4)]
    sigs = [
        {
            "date": dts[0],
            "symbol": s,
            "method": "m",
            "confidence": c,
            "close": 100.0,
            "turnover": 1e12,
            "stop": 95.0,
            "entry": None,
        }
        for s, c in (("A", "LOW"), ("B", "HIGH"), ("C", "MED"))
    ]
    res = simulate("t", sigs, set(), book, dts, lambda m: prof, dict(C, MAX_POSITIONS=2))
    check(
        "max positions + confidence priority",
        sorted(o["symbol"] for o in res["open"]) == ["B", "C"],
        str([o["symbol"] for o in res["open"]]),
    )
    # 12) O'Neil: +20% inside 3 weeks -> hold (no quick profit-taking)
    rocket = [(100 + 5 * i, 106 + 5 * i, 99 + 5 * i, 105 + 5 * i) for i in range(8)]
    res, _ = run([(100, 101, 99, 100), *rocket], {"entry": None, "stop": None}, dict(BOOK_PROFILES["oneil"]))
    check("O'Neil 8-week rule keeps a fast winner", not res["trades"] and len(res["open"]) == 1)
    # 13) cash is never negative and equity reconciles
    res, _ = run([*flat, (100, 101, 99.5, 100), (99, 99.5, 94, 95), *flat], {"entry": None, "stop": 95.0}, prof)
    end_eq = res["curve"][-1][1]
    check(
        "equity = capital + sum of trade P&L",
        abs(end_eq - (1_000_000 + sum(t["pnl"] for t in res["trades"]))) < 0.05,
        f"{end_eq}",
    )

    if verbose:
        print("No peeking into the future:")
    try:
        rng = np.random.default_rng(3)
        n = 700
        c = 200 * np.exp(np.cumsum(rng.normal(0.0007, 0.02, n)))
        df = pd.DataFrame(
            {
                "date": pd.bdate_range("2022-01-03", periods=n).strftime("%Y-%m-%d"),
                "open": c * (1 + rng.normal(0, 0.005, n)),
                "high": c * (1 + np.abs(rng.normal(0, 0.01, n))),
                "low": c * (1 - np.abs(rng.normal(0, 0.01, n))),
                "close": c,
                "volume": rng.integers(1e5, 1e6, n).astype(float),
            }
        )
        ctx = {"cfg": C, "sym_sector": {}, "sector_rank": {}, "sector_rank_dates": []}
        px = _prep(df)
        days = px["dates"][-80:]
        full, _ = _replay_book("way_of_the_turtle", "X", px, days, ctx)
        cut = []
        for d in days:
            k = px["pos"][d]
            r, _ = _replay_book("way_of_the_turtle", "X", _prep(df.iloc[: k + 1].reset_index(drop=True)), [d], ctx)
            cut += r

        def strip(rows):
            return sorted(r[:16] for r in rows)

        check(
            "replay = scanning a chart that ends on that day",
            strip(full) == strip(cut),
            f"{len(full)} signals compared",
        )
    except Exception as e:
        check("replay no-lookahead test ran", False, str(e))

    ok = all(r[1] for r in results)
    if verbose:
        print(
            f"\n{sum(r[1] for r in results)}/{len(results)} checks passed"
            + ("" if ok else " — DO NOT TRUST RESULTS UNTIL FIXED")
        )
    return ok


# ============================================================
# CLI
# ============================================================
def main(argv=None):
    with contextlib.suppress(Exception):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="Trader League: 14 books + our system, Rs 10 lakh each.")
    sub = ap.add_subparsers(dest="cmd")
    r = sub.add_parser("replay", help="pre-season replay (slow, resumable)")
    r.add_argument("--years", type=float)
    r.add_argument("--symbols", type=int)
    r.add_argument("--players", type=str, help="comma list, e.g. home,nison")
    r.add_argument("--workers", type=int, default=1)
    r.add_argument("--fresh", action="store_true", help="forget stored replay signals for these players")
    r.add_argument(
        "--changed",
        action="store_true",
        help="redo (fresh) only players whose code or settings changed since their replay",
    )
    r.add_argument(
        "--background",
        action="store_true",
        help="start in the background at low priority and return (same as the League tab button; survives SSH logout)",
    )
    b = sub.add_parser("backtest", help="simulate stored signals (fast)")
    b.add_argument("--exit", default="book", choices=["book", "common"])
    b.add_argument("--players", type=str)
    sm = sub.add_parser("simulate", help="re-simulate backtest or live")
    sm.add_argument("--mode", default="backtest", choices=["backtest", "live"])
    sm.add_argument("--exit", default="both", choices=["book", "common", "both"])
    for name in ("table", "ready"):
        p = sub.add_parser(name)
        p.add_argument("--mode", default="backtest", choices=["backtest", "live"])
        p.add_argument("--exit", default="book", choices=["book", "common"])
    pl = sub.add_parser("player")
    pl.add_argument("slug")
    pl.add_argument("--mode", default="backtest", choices=["backtest", "live"])
    pl.add_argument("--exit", default="book", choices=["book", "common"])
    sub.add_parser("live", help="collect today's signals + simulate")
    sc = sub.add_parser("scorecard", help="send the Telegram scorecard")
    sc.add_argument("--print", action="store_true", help="print, don't send")
    sub.add_parser("status")
    sub.add_parser("selftest")
    a = ap.parse_args(argv)

    def lst(s):
        return [x.strip() for x in s.split(",") if x.strip()] if s else None

    if a.cmd == "replay":
        slugs, fresh = lst(a.players), a.fresh
        if a.changed:
            slugs = [p["slug"] for p in status()["players"] if p["code_changed"]]
            if not slugs:
                print("No player's code or settings changed since its replay — nothing to redo.")
                return
            fresh = True
            print("Code/settings changed for: " + ", ".join(slugs) + " — replaying them fresh.")
        if a.background:
            res = start_replay_process(a.years, a.symbols, a.workers, slugs, fresh)
            st = res.get("state") or {}
            if res.get("started"):
                print(
                    f"Replay started in the background (pid {st.get('pid')}"
                    f", {st.get('years'):g} years, {st.get('symbols')} "
                    f"stocks)."
                )
                print("You can close SSH now — it keeps running.")
                print("Progress: python trader_league.py status")
                print(f"Log file: {_REPLAY_LOG}")
            else:
                print(f"Not started: {res.get('reason')} (pid {st.get('pid')}, started {st.get('started')}).")
                print("See its progress: python trader_league.py status")
            return
        if not _claim_replay(a.years, a.symbols, a.workers):
            sys.exit(1)
        try:
            os.nice(10)  # low priority: the web terminal stays fast
        except Exception:
            pass
        replay(a.years, a.symbols, slugs, a.workers, fresh)
    elif a.cmd == "backtest":
        res = simulate_all("backtest", a.exit, lst(a.players))
        if res.get("error"):
            print(res["error"] + " — run: python trader_league.py replay")
        else:
            print_ready("backtest", a.exit)
    elif a.cmd == "simulate":
        for ex in ["book", "common"] if a.exit == "both" else [a.exit]:
            res = simulate_all(a.mode, ex, quiet=True)
            if res.get("error"):
                print(res["error"])
                break
        print_table(a.mode, "book" if a.exit == "both" else a.exit)
    elif a.cmd == "table":
        print_table(a.mode, a.exit)
    elif a.cmd == "ready":
        print_ready(a.mode, a.exit)
    elif a.cmd == "player":
        print_player(a.slug, a.mode, a.exit)
    elif a.cmd == "live":
        rep = run_live()
        for k, v in rep.items():
            print(f"  {k:<28} {v}")
        print_table("live", "book")
    elif a.cmd == "scorecard":
        txt = scorecard_text()
        print(txt or "No league run yet.")
        if txt and not a.print:
            print("sent" if send_scorecard() else "not sent (Telegram off?)")
    elif a.cmd == "status":
        s = status()
        print(f"Last price date: {s['last_price_date']}")
        print(f"{'Player':<28}{'Replay signals':>15}{'Stocks':>8}  {'Replayed':<25}{'Live signals':>13}")
        for p in s["players"]:
            rng_txt = (
                f"{p['replay_from']} -> {p['replay_to']}"
                if p["replay_from"]
                else ("—" if p["backtest"] else "live only")
            )
            flag = "  (code changed: replay --changed)" if p["code_changed"] else ""
            print(
                f"{p['name'][:28]:<28}{p['replay_signals']:>15,}"
                f"{p['replay_stocks']:>8}  {rng_txt:<25}"
                f"{p['live_signals']:>13,}{flag}"
            )
        j = s["replay_job"]
        if j.get("running"):
            print(f"Replay running (pid {j.get('pid')}, since {j.get('started')})")
        for rr in s["runs"]:
            print(f"Run {rr['run_id']:<16} {rr['start']} -> {rr['end']} (saved {rr['created_at']})")
    elif a.cmd == "selftest":
        sys.exit(0 if selftest() else 1)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
