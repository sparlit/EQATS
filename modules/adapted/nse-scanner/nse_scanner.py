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


#!/usr/bin/env python3
"""
NSE Inside Bar Scanner — local Python version, writes results into Google Sheets.

WHAT IT DOES
    Scans NSE symbols (no price cap — every symbol is eligible) while
    skipping low-liquidity names using --min-avg-volume and
    --min-turnover-lakhs, for the "inside bar" pattern on either a daily or
    hourly timeframe, and writes color-coded signals into a worksheet tab of
    your Google Sheet:
        WATCH              -> latest candle is an inside bar (amber). No
                               trade yet, a name to watch for the next
                               candle's breakout.
        BULLISH (green)    -> previous candle was an inside bar, and the
        BEARISH (red)         LATEST candle closed beyond the mother bar's
                               high/low (close-based confirmation).
    Confirmed breakouts get scored 0-3 against false-breakout filters:
        trend  - close on the correct side of the 50-period EMA
        volume - breakout candle volume >= 1.5x the prior 20-period average
        RSI    - RSI(14) in a sane momentum band, not already at an extreme
    Entry / Stop Loss / Target are computed off the mother bar's range:
        BULLISH: entry = mother high, stop = mother low,
                 target = mother high + (mother high - mother low)
        BEARISH: entry = mother low,  stop = mother high,
                 target = mother low  - (mother high - mother low)
        WATCH:   both potential trigger levels are shown; direction isn't
                 known yet so no stop/target until it actually breaks out.

PATTERN LOGIC (3-candle window, newest = candle[-1]):
    candle[-3] = mother bar candidate (for confirmed breakout check)
    candle[-2] = inside bar candidate (must be inside candle[-3] high/low)
    candle[-1] = breakout/signal candle:
        - If candle[-2] was inside candle[-3] AND candle[-1] closes
          beyond candle[-3] high/low => BULLISH / BEARISH
        - If candle[-1] is inside candle[-2]  => WATCH (fresh inside bar)

TWO-STAGE SCAN (keeps this fast even across the whole NSE list)
    Stage 1: a quick liquidity check on every symbol (~1 month of daily
             data) to drop anything that isn't actively traded — average
             volume and average rupee turnover both have to clear your
             --min-avg-volume / --min-turnover-lakhs thresholds — before
             doing any real work. There is no price cap; a stock can be at
             any price as long as it trades enough volume/turnover.
    Stage 2: full historical fetch + indicator calc, only on what's left.
             analyze_symbol() re-checks the same liquidity thresholds
             against the timeframe-specific data, so Stage 1 is purely a
             speed optimization, not the source of truth.

SECTOR COLUMN
    Once a symbol produces a signal (WATCH/BULLISH/BEARISH), its sector is
    looked up via yfinance's `Ticker.info` and written into the sheet. This
    lookup only happens for the (small) list of symbols with signals, not
    the whole NSE universe, since per-symbol `.info` calls are slow.

DATA SOURCE
    Yahoo Finance via the `yfinance` package (SYMBOL.NS). Free, no key.
    60-minute intraday data is typically ~15 min delayed and can be patchy
    for illiquid names — treat it as "near-live" for spotting setups, not
    as a tick-accurate execution feed.

SYMBOL UNIVERSE (fixed — see load_symbols)
    NSE's archives host (nsearchives.nseindia.com) blocks plain scripted
    requests without a warmed-up session/cookies, which used to cause a
    SILENT fallback to a 47-stock Nifty-50 list — meaning most of the NSE
    universe (incl. mid/small caps like ELGIEQUIP) was never scanned, with
    no obvious error. load_symbols() now:
        1. Warms up a requests.Session against nseindia.com to collect the
           cookies NSE expects, then requests the CSV with proper headers.
        2. Retries a few times with backoff before giving up.
        3. Falls back to the NSE company master API as a second source.
        4. Falls back to a bundled/cached local symbol file if you keep one
           (--symbols-file always wins if you pass it).
        5. Only as an absolute last resort does it use the 47-stock
           Nifty-50 list — and when it does, it now prints a loud WARNING
           (not a quiet stderr note) and requires --allow-fallback-list to
           proceed, so you can never silently under-scan again.

USAGE
    python nse_scanner.py --timeframe daily
    python nse_scanner.py --timeframe hourly
    python nse_scanner.py --timeframe daily --min-avg-volume 200000 --min-turnover-lakhs 100
    python nse_scanner.py --timeframe daily --symbols-file my_symbols.txt

See SETUP.md for one-time Google Sheets credential setup and how to
schedule this with cron so it runs automatically, hourly and daily.
"""

import argparse
import csv
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import yfinance as yf

# ============================== CONFIG ======================================
SPREADSHEET_ID = "1YDfmA6wa8t8uqPsavOfsvPzM8SpOTFgxql9wp-07uKk"  # from your sheet URL

CONFIG = {
    "vol_ratio_min": 1.5,
    # Liquidity gate — raised from the old defaults since there's no more
    # price cap to naturally thin out illiquid penny stocks. Tune these with
    # --min-avg-volume / --min-turnover-lakhs as needed.
    "min_avg_volume": 150_000,
    "min_turnover_lakhs": 100.0,
    "rsi_bull_min": 40,
    "rsi_bull_max": 80,
    "rsi_bear_min": 20,
    "rsi_bear_max": 60,
}

TIMEFRAMES = {
    "daily": {
        "interval": "1d",
        "period": "6mo",
        "min_candles": 60,
        "sheet_name": "Scan Results - Daily",
        "ema_trend": 50,
        "rsi_period": 14,
        "vol_avg_period": 20,
        # Drop the live intraday candle? No — daily candles close EOD; scanner
        # runs post-market (16:00 IST), so the last candle IS a closed candle.
        "drop_live_candle": False,
    },
    "hourly": {
        "interval": "60m",
        "period": "60d",
        "min_candles": 60,
        "sheet_name": "Scan Results - Hourly",
        "ema_trend": 50,
        "rsi_period": 14,
        "vol_avg_period": 20,
        # yfinance always includes the LIVE (still-open) hourly candle
        # as the last row. Checking its close for a breakout gives false signals
        # (price may be above the mother bar intrasession but close back inside).
        # Drop it so candle_1 is always the last COMPLETED candle.
        "drop_live_candle": True,
    },
    "weekly": {
        "interval": "1wk",
        "period": "5y",
        "min_candles": 60,
        "sheet_name": "Scan Results - Weekly",
        "ema_trend": 50,
        "rsi_period": 14,
        "vol_avg_period": 20,
        # Weekly candles close on Friday; run scanner Friday post-market.
        "drop_live_candle": False,
    },
}

NIFTY50_FALLBACK = [
    "RELIANCE",
    "TCS",
    "HDFCBANK",
    "ICICIBANK",
    "INFY",
    "HINDUNILVR",
    "ITC",
    "SBIN",
    "BHARTIARTL",
    "KOTAKBANK",
    "LT",
    "AXISBANK",
    "BAJFINANCE",
    "ASIANPAINT",
    "MARUTI",
    "SUNPHARMA",
    "TITAN",
    "ULTRACEMCO",
    "WIPRO",
    "ONGC",
    "NTPC",
    "POWERGRID",
    "NESTLEIND",
    "HCLTECH",
    "TATAMOTORS",
    "TATASTEEL",
    "ADANIENT",
    "ADANIPORTS",
    "JSWSTEEL",
    "COALINDIA",
    "BAJAJFINSV",
    "TECHM",
    "INDUSINDBK",
    "DRREDDY",
    "GRASIM",
    "CIPLA",
    "EICHERMOT",
    "BRITANNIA",
    "DIVISLAB",
    "HEROMOTOCO",
    "BPCL",
    "HDFCLIFE",
    "SBILIFE",
    "APOLLOHOSP",
    "TATACONSUM",
    "UPL",
    "BAJAJ-AUTO",
]  # Absolute last-resort only — this is NOT full NSE coverage (mid/small caps
# like ELGIEQUIP are NOT in this list). See load_symbols().

SIGNAL_RANK = {"BULLISH": 0, "BEARISH": 1, "WATCH": 2}
SIGNAL_COLOR = {
    "BULLISH": {"red": 0.80, "green": 0.94, "blue": 0.80},
    "BEARISH": {"red": 0.97, "green": 0.80, "blue": 0.80},
    "WATCH": {"red": 1.00, "green": 0.95, "blue": 0.75},
}
WHITE = {"red": 1.0, "green": 1.0, "blue": 1.0}

HEADER = [
    "Symbol",
    "Sector",
    "Signal",
    "Pattern",
    "Mother High",
    "Mother Low",
    "Last Close",
    "Avg Volume",
    "Turnover (L)",
    "Vol Ratio",
    "Trend vs EMA",
    "RSI",
    "Score",
    "Entry",
    "Stop Loss",
    "Target",
    "Updated At",
]


# ============================ MARKET HOURS ==================================
def is_market_hours() -> bool:
    now = datetime.now(ZoneInfo("Asia/Kolkata"))
    if now.weekday() >= 5:  # Sat/Sun
        return False
    hm = now.strftime("%H%M")
    return "0915" <= hm <= "1530"


# ============================ SYMBOL LIST ===================================
NSE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/market-data/securities-available-for-trading",
}

# Local on-disk cache so a successful fetch survives NSE being unreachable
# on a later run. Refresh automatically if older than CACHE_MAX_AGE_DAYS.
SYMBOL_CACHE_PATH = Path(__file__).resolve().parent / "nse_symbols_cache.txt"
CACHE_MAX_AGE_DAYS = 7


def _nse_session() -> requests.Session:
    """NSE's archives host rejects cold requests with no cookies. Warming up
    against the main site first (like a real browser landing on the page
    before the CSV downloads) is what actually earns a 200 instead of a
    403/999 block."""
    s = requests.Session()
    s.headers.update(NSE_HEADERS)
    try:
        s.get("https://www.nseindia.com", timeout=10)
        s.get("https://www.nseindia.com/market-data/securities-available-for-trading", timeout=10)
    except Exception:
        pass  # even if the warm-up fails, still attempt the real request below
    return s


def _fetch_equity_list_csv(session: requests.Session) -> list[str] | None:
    url = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"
    resp = session.get(url, timeout=15)
    if resp.status_code != 200 or not resp.text.strip():
        return None
    reader = csv.reader(resp.text.splitlines())
    next(reader, None)  # header row
    syms = [row[0].strip() for row in reader if row and row[0].strip()]
    return syms or None


def _fetch_equity_list_api(session: requests.Session) -> list[str] | None:
    """Secondary source: NSE's equity master API. Different endpoint, same
    domain — sometimes available when the archives CSV path is rate-limited."""
    url = "https://www.nseindia.com/api/equity-master"
    resp = session.get(url, timeout=15)
    if resp.status_code != 200:
        return None
    try:
        data = resp.json()
    except ValueError:
        return None
    syms: list[str] = []
    if isinstance(data, dict):
        for group in data.values():
            if isinstance(group, list):
                syms.extend(str(s).strip() for s in group if str(s).strip())
    return sorted(set(syms)) or None


def _read_cache() -> list[str] | None:
    if not SYMBOL_CACHE_PATH.exists():
        return None
    age_days = (time.time() - SYMBOL_CACHE_PATH.stat().st_mtime) / 86400
    with SYMBOL_CACHE_PATH.open() as f:
        syms = [line.strip() for line in f if line.strip()]
    if not syms:
        return None
    if age_days > CACHE_MAX_AGE_DAYS:
        print(
            f"  (cached symbol list is {age_days:.0f} days old — using it, but "
            f"consider refreshing with a fresh --symbols-file)",
            file=sys.stderr,
        )
    return syms


def _write_cache(symbols: list[str]) -> None:
    try:
        with SYMBOL_CACHE_PATH.open("w") as f:
            f.write("\n".join(symbols))
    except Exception:
        pass  # cache is a nice-to-have, never fatal


def load_symbols(
    symbols_file: str | None, allow_fallback_list: bool, max_retries: int = 3
) -> list[str]:
    """
    Resolution order (first success wins), so a full NSE scan is the default
    and the tiny Nifty-50 list is only ever used deliberately, never silently:
        1. --symbols-file, if given (always wins — you're explicit).
        2. NSE archives CSV (full listed-equity universe), with a warmed-up
           session, proper headers, and retries.
        3. NSE equity-master API as a second live source.
        4. Local on-disk cache from a previous successful run.
        5. NIFTY50_FALLBACK — ONLY if --allow-fallback-list was passed;
           otherwise this raises so you can't accidentally under-scan.
    """
    if symbols_file:
        path = Path(symbols_file)
        with path.open() as f:
            syms = [line.strip() for line in f if line.strip()]
        print(f"Loaded {len(syms)} symbols from {symbols_file}.")
        return syms

    session = _nse_session()

    for attempt in range(1, max_retries + 1):
        try:
            syms = _fetch_equity_list_csv(session)
            if syms:
                print(f"Fetched {len(syms)} symbols from NSE archives CSV (attempt {attempt}).")
                _write_cache(syms)
                return syms
        except Exception as e:
            print(f"  NSE CSV fetch attempt {attempt}/{max_retries} failed: {e}", file=sys.stderr)
        if attempt < max_retries:
            time.sleep(2 * attempt)  # backoff: 2s, 4s, ...

    try:
        syms = _fetch_equity_list_api(session)
        if syms:
            print(f"Fetched {len(syms)} symbols from NSE equity-master API (fallback source).")
            _write_cache(syms)
            return syms
    except Exception as e:
        print(f"  NSE equity-master API fetch failed: {e}", file=sys.stderr)

    cached = _read_cache()
    if cached:
        print(
            f"NSE is unreachable right now — using {len(cached)} symbols from local cache "
            f"({SYMBOL_CACHE_PATH})."
        )
        return cached

    if not allow_fallback_list:
        print(
            "\nERROR: Could not fetch the live NSE symbol list from any source "
            "(archives CSV, equity-master API), and no local cache exists yet.\n"
            "Refusing to silently fall back to the 47-stock Nifty-50 list, since "
            "that would scan only large caps and miss most of NSE (mid/small caps "
            "like ELGIEQUIP included).\n\n"
            "Options:\n"
            "  1. Re-run later / check your network — NSE occasionally rate-limits.\n"
            "  2. Download EQUITY_L.csv yourself from nseindia.com in a browser and "
            "pass it with --symbols-file EQUITY_L.csv\n"
            "  3. Pass --allow-fallback-list to explicitly accept scanning only the "
            "47-stock Nifty-50 starter list (NOT recommended for full coverage).\n",
            file=sys.stderr,
        )
        sys.exit(1)

    print(
        "\nWARNING: Falling back to the 47-stock Nifty-50 starter list because "
        "--allow-fallback-list was passed. This is NOT full NSE coverage — "
        "mid/small caps will be skipped.\n",
        file=sys.stderr,
    )
    return NIFTY50_FALLBACK


# ============================ DATA FETCH ====================================
def chunked(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i : i + n]


def fetch_batch(symbols: list[str], interval: str, period: str) -> pd.DataFrame:
    tickers = [s + ".NS" for s in symbols]
    return yf.download(
        tickers=tickers,
        period=period,
        interval=interval,
        group_by="ticker",
        threads=True,
        progress=False,
        auto_adjust=False,
    )


def extract_symbol_df(data: pd.DataFrame, symbol: str, chunk_len: int) -> pd.DataFrame | None:
    """
    Extract per-symbol OHLCV DataFrame from a yfinance batch download result.

    yfinance >= 0.2 returns a MultiIndex with (field, ticker) at the column level,
    i.e. level-0 = field ('Open','High','Low','Close','Volume','Adj Close'),
         level-1 = ticker ('RELIANCE.NS', ...).
    Older versions used (ticker, field) OR flat columns when only 1 ticker was fetched.
    We handle all three cases explicitly to avoid the most common source of false signals.
    """
    ticker = symbol + ".NS"

    if isinstance(data.columns, pd.MultiIndex):
        level0_vals = data.columns.get_level_values(0).unique().tolist()
        level1_vals = data.columns.get_level_values(1).unique().tolist()

        # Modern yfinance: level-0 = field, level-1 = ticker  e.g. ('Close', 'RELIANCE.NS')
        if ticker in level1_vals:
            df = data.xs(ticker, level=1, axis=1).copy()
        # Legacy yfinance: level-0 = ticker, level-1 = field  e.g. ('RELIANCE.NS', 'Close')
        elif ticker in level0_vals:
            df = data[ticker].copy()
        else:
            return None
    else:
        # Single-ticker download — yfinance returns flat columns directly
        df = data.copy()

    if df is None or len(df) == 0:
        return None

    # If there are still nested column levels (edge-case), flatten them
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    try:
        df = df.dropna(subset=["Open", "High", "Low", "Close"])
    except KeyError:
        return None

    return df if len(df) > 0 else None


def prefilter_by_liquidity(
    symbols: list[str], min_avg_volume: int, min_turnover_lakhs: float, chunk_size: int
) -> list[str]:
    """Stage 1: quick liquidity check to drop anything that isn't actively
    traded, before the expensive full-history fetch + indicator calc. Pulls
    ~1 month of daily candles (cheap) and checks average volume + average
    rupee turnover — the same two gates analyze_symbol() re-applies later
    with timeframe-accurate data, so this is a speed filter, not the final
    word. No price cap is applied here or anywhere else in the scanner."""
    keep = []
    chunks = list(chunked(symbols, chunk_size))
    for idx, chunk in enumerate(chunks, 1):
        try:
            data = fetch_batch(chunk, "1d", "1mo")
        except Exception as e:
            print(f"  liquidity-check batch {idx}/{len(chunks)} failed: {e}", file=sys.stderr)
            continue
        for sym in chunk:
            try:
                df = extract_symbol_df(data, sym, len(chunk))
                if df is None or len(df) < 5:
                    continue
                avg_vol = float(df["Volume"].mean())
                last_close = float(df["Close"].iloc[-1])
                if pd.isna(avg_vol) or pd.isna(last_close):
                    continue
                turnover_lakhs = (last_close * avg_vol) / 100_000
                if avg_vol >= min_avg_volume and turnover_lakhs >= min_turnover_lakhs:
                    keep.append(sym)
            except Exception:
                continue
        print(
            f"  liquidity-check batch {idx}/{len(chunks)} done — {len(keep)} actively traded so far"
        )
        time.sleep(0.5)
    return keep


# ============================ INDICATORS ====================================
def calc_rsi(close: pd.Series, period: int) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


# ============================ CORE LOGIC ====================================
def analyze_symbol(
    symbol: str,
    df: pd.DataFrame,
    tf: dict,
    min_avg_volume: int,
    min_turnover_lakhs: float,
) -> dict | None:
    """
    Evaluate the last 3 completed candles for inside-bar breakout signals.

    Candle window (newest last, after dropping any live candle for hourly TF):
        df.iloc[-3]  = candle_3  (mother bar for confirmed-breakout check)
        df.iloc[-2]  = candle_2  (inside bar candidate / mother bar for WATCH)
        df.iloc[-1]  = candle_1  (the most-recently CLOSED candle)

    CONFIRMED BREAKOUT  (BULLISH / BEARISH):
        Condition:  candle_2 is fully inside candle_3 (high ≤ mother high,
                    low ≥ mother low) AND candle_1 CLOSES beyond the MOTHER
                    bar's range (not just the inside bar's edges).
        Rationale:  Requiring a close outside the MOTHER bar's range filters
                    out weak intrabar pokes that reverse by session end.

    WATCH  — two sub-cases:
        Case A (simple IB):  candle_1 is inside candle_2 (which is NOT inside
                    candle_3).  Trigger = candle_2 high / low.
        Case B (nested IB):  candle_2 is inside candle_3 AND candle_1 is inside
                    candle_2.  The dominant mother bar is candle_3, so the true
                    breakout trigger = candle_3 high / low.

    Scoring (0-3, applied only to confirmed breakouts):
        +1  trend  — close is on the correct side of the 50-period EMA
        +1  volume — breakout-candle volume >= 1.5× the 20-period average
        +1  RSI    — RSI(14) is in a momentum-sane band (not overbought/oversold)

    Liquidity gate (applied before any pattern checks):
        Skips stocks where the 20-period average volume < min_avg_volume OR
        average rupee turnover < min_turnover_lakhs.
    """
    if df is None or len(df) < tf["min_candles"]:
        return None

    # Drop the live/incomplete candle for intraday timeframes. yfinance
    # always appends the currently-open candle as the last row when the
    # market is open. Checking its close for a breakout mid-session
    # produces false BULLISH/BEARISH hits that reverse by close.
    if tf.get("drop_live_candle", False):
        df = df.iloc[:-1]
        if len(df) < tf["min_candles"]:
            return None

    n = len(df)
    closes = df["Close"]
    ema = closes.ewm(span=tf["ema_trend"], adjust=False, min_periods=tf["ema_trend"]).mean()
    rsi = calc_rsi(closes, tf["rsi_period"])
    vol = df["Volume"]

    ema_last = ema.iloc[-1]
    rsi_last = rsi.iloc[-1]
    if pd.isna(ema_last) or pd.isna(rsi_last):
        return None

    # Volume average over the 20 candles BEFORE the current one (exclude current)
    avg_vol = vol.iloc[max(0, n - 1 - tf["vol_avg_period"]) : n - 1].mean()

    # ----- 3-candle window -----
    # candle_1 = most recent (the signal / breakout candle)
    # candle_2 = one before that (inside bar candidate or mother bar for WATCH)
    # candle_3 = two before that (mother bar candidate for confirmed breakout)
    candle_1 = df.iloc[-1]
    candle_2 = df.iloc[-2]
    candle_3 = df.iloc[-3]

    # Guard: ensure OHLC values are usable floats
    try:
        c1_high = float(candle_1["High"])
        c1_low = float(candle_1["Low"])
        c1_close = float(candle_1["Close"])
        c1_vol = float(candle_1["Volume"])
        c2_high = float(candle_2["High"])
        c2_low = float(candle_2["Low"])
        c3_high = float(candle_3["High"])
        c3_low = float(candle_3["Low"])
    except (TypeError, ValueError):
        return None

    if any(pd.isna(v) for v in [c1_high, c1_low, c1_close, c2_high, c2_low, c3_high, c3_low]):
        return None

    # ── Liquidity gate ──────────────────────────────────────────────────────
    # Compute daily turnover in lakhs using last close × avg volume
    avg_vol_safe = float(avg_vol) if (avg_vol is not None and not pd.isna(avg_vol)) else 0.0
    turnover_lakhs = (c1_close * avg_vol_safe) / 100_000 if avg_vol_safe > 0 else 0.0

    if avg_vol_safe < min_avg_volume or turnover_lakhs < min_turnover_lakhs:
        return None
    # ────────────────────────────────────────────────────────────────────────

    result = {
        "symbol": symbol,
        "sector": "N/A",
        "pattern": "",
        "signal": "NONE",
        "mother_high": None,
        "mother_low": None,
        "last_close": round(c1_close, 2),
        "avg_volume": int(round(avg_vol_safe)),
        "turnover_lakhs": round(turnover_lakhs, 2),
        "vol_ratio": None,
        "trend": "",
        "rsi": round(float(rsi_last), 2),
        "score": 0,
        "entry": "",
        "stop_loss": "",
        "target": "",
        "updated_at": datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%Y-%m-%d %H:%M"),
    }

    # ------------------------------------------------------------------ #
    #  Case 1: CONFIRMED BREAKOUT                                         #
    #    candle_2 is an inside bar relative to candle_3 (mother bar),     #
    #    AND candle_1 (current) closes beyond the mother bar's range.     #
    # ------------------------------------------------------------------ #
    candle_2_is_inside_candle_3 = (c2_high <= c3_high) and (c2_low >= c3_low)

    # Pre-compute vol ratio for candle_1 (used in both confirmed and WATCH)
    c1_vol_safe = c1_vol if not pd.isna(c1_vol) else 0.0
    vol_ratio_raw = (c1_vol_safe / avg_vol_safe) if avg_vol_safe > 0 else None
    safe_vol_ratio = (
        round(float(vol_ratio_raw), 2)
        if (vol_ratio_raw is not None and not pd.isna(vol_ratio_raw))
        else None
    )

    if candle_2_is_inside_candle_3:
        mother_high = round(c3_high, 2)
        mother_low = round(c3_low, 2)
        rng = round(mother_high - mother_low, 2)

        if c1_close > c3_high:  # ── BULLISH breakout ──────────────
            result.update(
                pattern="Breakout confirmed",
                signal="BULLISH",
                mother_high=mother_high,
                mother_low=mother_low,
                entry=mother_high,
                stop_loss=mother_low,
                target=round(mother_high + rng, 2),
                vol_ratio=safe_vol_ratio,
            )
            result["trend"] = (
                f"above EMA{tf['ema_trend']}"
                if c1_close > float(ema_last)
                else f"below EMA{tf['ema_trend']}"
            )
            if c1_close > float(ema_last):
                result["score"] += 1
            if safe_vol_ratio is not None and safe_vol_ratio >= CONFIG["vol_ratio_min"]:
                result["score"] += 1
            if CONFIG["rsi_bull_min"] <= float(rsi_last) <= CONFIG["rsi_bull_max"]:
                result["score"] += 1

        elif c1_close < c3_low:  # ── BEARISH breakout ──────────────
            result.update(
                pattern="Breakout confirmed",
                signal="BEARISH",
                mother_high=mother_high,
                mother_low=mother_low,
                entry=mother_low,
                stop_loss=mother_high,
                target=round(mother_low - rng, 2),
                vol_ratio=safe_vol_ratio,
            )
            result["trend"] = (
                f"below EMA{tf['ema_trend']}"
                if c1_close < float(ema_last)
                else f"above EMA{tf['ema_trend']}"
            )
            if c1_close < float(ema_last):
                result["score"] += 1
            if safe_vol_ratio is not None and safe_vol_ratio >= CONFIG["vol_ratio_min"]:
                result["score"] += 1
            if CONFIG["rsi_bear_min"] <= float(rsi_last) <= CONFIG["rsi_bear_max"]:
                result["score"] += 1

    # ------------------------------------------------------------------ #
    #  Case 2: FRESH INSIDE BAR → WATCH                                   #
    #                                                                      #
    #  Sub-case A (simple IB):                                            #
    #    candle_1 is inside candle_2, and candle_2 is NOT inside candle_3 #
    #    → trigger = candle_2 high/low (the immediate mother bar)         #
    #                                                                      #
    #  Sub-case B (nested IB):                                            #
    #    candle_2 is inside candle_3 AND candle_1 is inside candle_2.     #
    #    The dominant mother bar is candle_3. A breakout above candle_2   #
    #    is still WITHIN candle_3's range, so the true trigger must be    #
    #    candle_3's high/low.                                             #
    # ------------------------------------------------------------------ #
    if result["signal"] == "NONE":
        candle_1_is_inside_candle_2 = (c1_high <= c2_high) and (c1_low >= c2_low)
        if candle_1_is_inside_candle_2:
            if candle_2_is_inside_candle_3:
                # Nested inside bar — use the dominant (outer) mother bar's levels
                mother_high = round(c3_high, 2)
                mother_low = round(c3_low, 2)
                watch_pattern = "Nested inside bar (watchlist)"
            else:
                # Simple inside bar — use candle_2 as the mother bar
                mother_high = round(c2_high, 2)
                mother_low = round(c2_low, 2)
                watch_pattern = "Inside bar (watchlist)"

            # Show vol_ratio for WATCH so the sheet shows whether the
            # compression candle formed on low volume (healthy) or high
            # volume (potentially suspicious reversal pressure).
            result.update(
                pattern=watch_pattern,
                signal="WATCH",
                mother_high=mother_high,
                mother_low=mother_low,
                entry=f"Buy>{mother_high} / Sell<{mother_low}",
                vol_ratio=safe_vol_ratio,
            )
            result["trend"] = (
                f"above EMA{tf['ema_trend']}"
                if c1_close > float(ema_last)
                else f"below EMA{tf['ema_trend']}"
            )

    return result if result["signal"] != "NONE" else None


# ============================ SECTOR LOOKUP ==================================
def attach_sectors(results: list[dict]) -> None:
    """Look up each signal's sector via yfinance Ticker.info and fill it into
    result['sector'] in place. Only called on the (small) final results list,
    since .info triggers a separate network call per symbol and is too slow
    to run across the whole NSE universe."""
    for r in results:
        try:
            info = yf.Ticker(r["symbol"] + ".NS").info
            sector = info.get("sector") or info.get("sectorDisp") or "N/A"
            r["sector"] = sector
        except Exception:
            r["sector"] = "N/A"
        time.sleep(0.2)  # polite pacing — this is a per-symbol call


# ============================ GOOGLE SHEETS =================================
def get_gspread_client(credentials_path: str):
    import gspread
    from google.oauth2.service_account import Credentials

    if not Path(credentials_path).exists():
        print(
            f"\nCredentials file not found: {credentials_path}\n"
            "See SETUP.md for how to create a Google service account key.",
            file=sys.stderr,
        )
        sys.exit(1)

    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_file(credentials_path, scopes=scopes)
    return gspread.authorize(creds)


def result_sort_key(result: dict) -> tuple:
    """Rank actionable, liquid, high-confirmation setups first."""
    return (
        SIGNAL_RANK.get(result["signal"], 9),
        -result["score"],
        -float(result.get("vol_ratio") or 0),
        -float(result.get("turnover_lakhs") or 0),
        result["symbol"],
    )


def write_results(gc, spreadsheet_id: str, sheet_name: str, results: list[dict]):
    import gspread

    sh = gc.open_by_key(spreadsheet_id)
    try:
        ws = sh.worksheet(sheet_name)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=sheet_name, rows=2000, cols=len(HEADER) + 2)

    results_sorted = sorted(results, key=result_sort_key)
    rows = [
        [
            r["symbol"],
            r["sector"],
            r["signal"],
            r["pattern"],
            r["mother_high"],
            r["mother_low"],
            r["last_close"],
            r["avg_volume"],
            r["turnover_lakhs"],
            r["vol_ratio"],
            r["trend"],
            r["rsi"],
            r["score"],
            r["entry"],
            r["stop_loss"],
            r["target"],
            r["updated_at"],
        ]
        for r in results_sorted
    ]

    ws.clear()
    ws.update([HEADER] + rows, "A1")

    # Reset formatting, then color-code contiguous blocks of the same signal.
    num_cols = len(HEADER)
    requests_batch = [
        {
            "repeatCell": {
                "range": {
                    "sheetId": ws.id,
                    "startRowIndex": 0,
                    "endRowIndex": max(len(rows) + 1, 2),
                    "startColumnIndex": 0,
                    "endColumnIndex": num_cols,
                },
                "cell": {"userEnteredFormat": {"backgroundColor": WHITE}},
                "fields": "userEnteredFormat.backgroundColor",
            }
        }
    ]

    if rows:
        block_start = 0
        for i in range(1, len(results_sorted) + 1):
            changed = (
                i == len(results_sorted)
                or results_sorted[i]["signal"] != results_sorted[block_start]["signal"]
            )
            if changed:
                signal = results_sorted[block_start]["signal"]
                color = SIGNAL_COLOR.get(signal)
                if color:
                    requests_batch.append(
                        {
                            "repeatCell": {
                                "range": {
                                    "sheetId": ws.id,
                                    "startRowIndex": block_start + 1,
                                    "endRowIndex": i + 1,
                                    "startColumnIndex": 0,
                                    "endColumnIndex": num_cols,
                                },
                                "cell": {"userEnteredFormat": {"backgroundColor": color}},
                                "fields": "userEnteredFormat.backgroundColor",
                            }
                        }
                    )
                block_start = i

    sh.batch_update({"requests": requests_batch})


# ============================ DEBUG ONE SYMBOL ===============================
def debug_symbol(symbol: str, tf: dict, min_avg_volume: int, min_turnover_lakhs: float) -> None:
    """Fetch one symbol and print exactly why it did/didn't produce a signal —
    the last 3 candles' OHLC, liquidity numbers, and every pattern condition
    with its true/false result. Use this instead of guessing when a stock
    you can see breaking out on a chart isn't showing up in the sheet."""
    print(
        f"\n=== Debugging {symbol} on timeframe={tf['sheet_name']} "
        f"(interval={tf['interval']}, period={tf['period']}) ===\n"
    )

    try:
        data = fetch_batch([symbol], tf["interval"], tf["period"])
    except Exception as e:
        print(f"Fetch failed: {e}")
        return

    df = extract_symbol_df(data, symbol, 1)
    if df is None:
        print(
            f"No usable data returned for {symbol}.NS — check the symbol is correct "
            f"and actually has {tf['interval']} history on Yahoo Finance."
        )
        return

    print(f"Fetched {len(df)} candles (need >= {tf['min_candles']} for indicators to warm up).")

    if tf.get("drop_live_candle", False):
        print("This timeframe drops the live/still-open candle (drop_live_candle=True).")
        df = df.iloc[:-1]
        print(f"{len(df)} candles remain after dropping it.")

    if len(df) < tf["min_candles"]:
        print(
            f"NOT ENOUGH DATA: {len(df)} < {tf['min_candles']} required candles. "
            f"This symbol will be skipped entirely regardless of pattern/liquidity."
        )
        return

    n = len(df)
    closes = df["Close"]
    ema = closes.ewm(span=tf["ema_trend"], adjust=False, min_periods=tf["ema_trend"]).mean()
    rsi = calc_rsi(closes, tf["rsi_period"])
    vol = df["Volume"]
    _ema_last, _rsi_last = ema.iloc[-1], rsi.iloc[-1]
    avg_vol = vol.iloc[max(0, n - 1 - tf["vol_avg_period"]) : n - 1].mean()

    c1, c2, c3 = df.iloc[-1], df.iloc[-2], df.iloc[-3]
    c1_high, c1_low, c1_close = float(c1["High"]), float(c1["Low"]), float(c1["Close"])
    c2_high, c2_low = float(c2["High"]), float(c2["Low"])
    c3_high, c3_low = float(c3["High"]), float(c3["Low"])

    print("\nLast 3 candles (oldest to newest):")
    print(
        f"  candle_3 (mother bar candidate) : idx={df.index[-3]}  "
        f"High={c3_high:.2f}  Low={c3_low:.2f}"
    )
    print(
        f"  candle_2 (inside bar candidate) : idx={df.index[-2]}  "
        f"High={c2_high:.2f}  Low={c2_low:.2f}"
    )
    print(
        f"  candle_1 (latest closed candle) : idx={df.index[-1]}  "
        f"High={c1_high:.2f}  Low={c1_low:.2f}  Close={c1_close:.2f}"
    )

    avg_vol_safe = float(avg_vol) if avg_vol is not None and not pd.isna(avg_vol) else 0.0
    turnover_lakhs = (c1_close * avg_vol_safe) / 100_000 if avg_vol_safe > 0 else 0.0
    liquidity_ok = avg_vol_safe >= min_avg_volume and turnover_lakhs >= min_turnover_lakhs

    print(
        f"\nLiquidity gate (needs avg_volume >= {min_avg_volume:,} "
        f"AND turnover >= {min_turnover_lakhs:g}L):"
    )
    print(
        f"  avg_volume (20-period) = {avg_vol_safe:,.0f}   -> "
        f"{'PASS' if avg_vol_safe >= min_avg_volume else 'FAIL'}"
    )
    print(
        f"  turnover (lakhs)       = {turnover_lakhs:,.2f}   -> "
        f"{'PASS' if turnover_lakhs >= min_turnover_lakhs else 'FAIL'}"
    )
    if not liquidity_ok:
        print(
            "  => LIQUIDITY GATE FAILS. This symbol is skipped before any pattern "
            "check runs, regardless of what the chart shows."
        )
        return
    print("  => Liquidity gate passes.")

    c2_inside_c3 = (c2_high <= c3_high) and (c2_low >= c3_low)
    c1_inside_c2 = (c1_high <= c2_high) and (c1_low >= c2_low)

    print("\nPattern conditions:")
    print(
        f"  candle_2 fully inside candle_3?  "
        f"(c2_high {c2_high:.2f} <= c3_high {c3_high:.2f}) AND "
        f"(c2_low {c2_low:.2f} >= c3_low {c3_low:.2f})  -> "
        f"{'TRUE' if c2_inside_c3 else 'FALSE'}"
    )

    if c2_inside_c3:
        print(
            f"  candle_1 close vs mother bar:  close={c1_close:.2f}  "
            f"mother_high={c3_high:.2f}  mother_low={c3_low:.2f}"
        )
        if c1_close > c3_high:
            print("  => BULLISH breakout condition MET (close > mother_high).")
        elif c1_close < c3_low:
            print("  => BEARISH breakout condition MET (close < mother_low).")
        else:
            print(
                "  => Inside bar formed, but candle_1 has NOT yet closed beyond the "
                "mother bar's range in either direction. No confirmed breakout signal "
                "(it may still show as WATCH if candle_1 is inside candle_2)."
            )
    else:
        print(
            "  => No confirmed-breakout signal is possible on THIS candle: candle_2 is "
            "not fully contained within candle_3. If your chart shows a strong move that "
            "still doesn't look like a clean 2-candle inside-bar setup by the strict "
            "high<=high / low>=low definition, that's why — not a liquidity or symbol-list "
            "issue."
        )

    print(
        f"\n  candle_1 inside candle_2? "
        f"(c1_high {c1_high:.2f} <= c2_high {c2_high:.2f}) AND "
        f"(c1_low {c1_low:.2f} >= c2_low {c2_low:.2f})  -> "
        f"{'TRUE (WATCH-eligible)' if c1_inside_c2 else 'FALSE'}"
    )

    print(
        "\nNote: only the LAST 3 candles are ever evaluated. If the breakout you're "
        "seeing on a chart happened more than 1-2 candles ago relative to when this "
        "scan runs, it has already scrolled out of this window and will not appear, "
        "even though it's still visible on the chart today.\n"
    )


# ============================== MAIN ========================================
def main():
    parser = argparse.ArgumentParser(description="NSE inside bar scanner")
    parser.add_argument("--timeframe", choices=["daily", "hourly", "weekly"], required=True)
    parser.add_argument(
        "--symbols-file",
        default=None,
        help="Optional text file, one NSE symbol per line. "
        "Default: fetch NSE's full list live (with retries/cache). "
        "Always wins over live fetch if given.",
    )
    parser.add_argument(
        "--allow-fallback-list",
        action="store_true",
        help="If the live NSE symbol fetch AND the local cache both fail, "
        "allow falling back to the 47-stock Nifty-50 starter list "
        "instead of exiting with an error. Off by default so you never "
        "silently under-scan.",
    )
    parser.add_argument(
        "--credentials",
        default="credentials.json",
        help="Path to the Google service account JSON key.",
    )
    parser.add_argument("--spreadsheet-id", default=SPREADSHEET_ID)
    parser.add_argument(
        "--chunk-size", type=int, default=50, help="Symbols per Yahoo Finance batch request."
    )
    parser.add_argument(
        "--min-avg-volume",
        type=int,
        default=CONFIG["min_avg_volume"],
        help="Only report stocks whose average volume meets this threshold. "
        "Default 150000 shares. No price cap is applied.",
    )
    parser.add_argument(
        "--min-turnover-lakhs",
        type=float,
        default=CONFIG["min_turnover_lakhs"],
        help="Only report stocks whose average rupee turnover meets this threshold, "
        "in lakhs. Default 100.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Run an hourly/weekly scan even outside market hours (for testing).",
    )
    parser.add_argument(
        "--debug-symbol",
        default=None,
        help="Diagnose exactly why ONE symbol (e.g. ELGIEQUIP) is or isn't "
        "producing a signal on the given --timeframe: prints the last 3 "
        "candles' OHLC, the liquidity numbers, and each pattern condition "
        "with its true/false result. Skips the full scan and Google Sheets "
        "write entirely — this is a read-only lookup.",
    )
    args = parser.parse_args()

    if args.debug_symbol:
        debug_symbol(
            args.debug_symbol,
            TIMEFRAMES[args.timeframe],
            args.min_avg_volume,
            args.min_turnover_lakhs,
        )
        return

    if args.timeframe == "hourly" and not args.force and not is_market_hours():
        print(
            "Outside NSE market hours (9:15 AM-3:30 PM IST, Mon-Fri) — skipping. "
            "Use --force to run anyway."
        )
        return

    # Weekly scans: only run on Friday after market close (or with --force)
    if args.timeframe == "weekly" and not args.force:
        from datetime import date

        today = date.today()
        now_ist = datetime.now(ZoneInfo("Asia/Kolkata"))
        if today.weekday() != 4:  # 4 = Friday
            print(
                "Weekly scan only runs on Fridays after market close. "
                "Use --force to run on any day (e.g. for testing)."
            )
            return
        if now_ist.strftime("%H%M") < "1530":
            print(
                "Weekly scan runs after 15:30 IST to ensure weekly candle is closed. "
                "Use --force to override."
            )
            return

    tf = TIMEFRAMES[args.timeframe]
    all_symbols = load_symbols(args.symbols_file, args.allow_fallback_list)
    print(
        f"Loaded {len(all_symbols)} symbols. No price cap — filtering to actively "
        f"traded names (avg volume >= {args.min_avg_volume:,}, "
        f"avg turnover >= Rs {args.min_turnover_lakhs:g}L)..."
    )

    symbols = prefilter_by_liquidity(
        all_symbols, args.min_avg_volume, args.min_turnover_lakhs, args.chunk_size
    )
    print(f"{len(symbols)} actively traded symbols. Running {args.timeframe} scan...")

    if not symbols:
        print("No symbols left after the liquidity filter — nothing to scan.")
        return

    gc = get_gspread_client(args.credentials)

    results = []
    chunks = list(chunked(symbols, args.chunk_size))
    for idx, chunk in enumerate(chunks, 1):
        try:
            data = fetch_batch(chunk, tf["interval"], tf["period"])
        except Exception as e:
            print(f"  batch {idx}/{len(chunks)} failed to fetch: {e}", file=sys.stderr)
            continue

        for sym in chunk:
            try:
                df = extract_symbol_df(data, sym, len(chunk))
                r = analyze_symbol(sym, df, tf, args.min_avg_volume, args.min_turnover_lakhs)
                if r:
                    results.append(r)
            except Exception:
                continue

        print(f"  batch {idx}/{len(chunks)} done — {len(results)} signals so far")
        time.sleep(1)  # polite pacing between batches

    if results:
        print(f"Looking up sectors for {len(results)} signals...")
        attach_sectors(results)

    write_results(gc, args.spreadsheet_id, tf["sheet_name"], results)
    print(f"Done. {len(results)} signals written to '{tf['sheet_name']}'.")


if __name__ == "__main__":
    main()
