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


# =============================================================================
# NSE DAILY MOMENTUM SCANNER - FIXED VERSION
# =============================================================================
#
# Uses Yahoo Finance 1-minute data. No Parquet, no nselib.
# Universe: Nifty 500 CSV -> NSE equity list -> built-in fallback.
# Output: index.html
#
# =============================================================================
# STRATEGY (UNCHANGED)
# =============================================================================
#
# 1) 3-MIN:   15:24 volume > 15:27 volume
#             (15:24 / 15:27 trend relationship does NOT matter)
#
# 2) 1-MIN:   15:28 and 15:29 must be OPPOSITE trends
#             15:28 volume > 15:29 volume
#
# 3) 1-MIN / 3-MIN: 1-min 15:28 trend must equal 3-min 15:24 trend
#
# 4) FINAL DIRECTION: 1-min 15:28 trend
#
# 5) TRADE: Entry = next trading day 09:15 OPEN, Exit = 15:27
#
# =============================================================================
# WHAT WAS FIXED (strategy logic untouched)
# =============================================================================
#
# - NameError: `unused_old_condition` was returned but never defined, so every
#   symbol that reached the end of evaluate_rows() became an ERROR.
# - yf.download() is not thread-safe (shared global state), so running it in a
#   ThreadPoolExecutor returned empty / mixed-up data. Now uses
#   yf.Ticker(...).history(), which is safe per thread.
# - INCOMPLETE: Yahoo does not return a row for a minute with no trades, so
#   any stock missing even one of the six candles was rejected. A missing
#   minute is now treated as "no trade": volume 0, no trend. The missing
#   minutes are listed in the Data column.
# - The old code silently fell back to an OLDER "complete" day. Now the latest
#   session is used, and symbols on a different date than the rest of the
#   market are marked STALE instead of producing a stale signal.
# - Banner warns when Yahoo's data for the day looks unfinished (few symbols
#   have the 15:29 candle).
# - Rate-limit (429) errors are retried with a longer back-off, and real
#   errors are reported as ERROR instead of being hidden as NO_DATA.
# - HTML table had 9 headers for 8 columns; fixed. Mojibake characters fixed.
#
# INSTALL:
#   python -m pip install yfinance pandas requests curl_cffi
#
# =============================================================================

import contextlib
import html
import logging
import random
import sys
import time
import warnings
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from io import StringIO

import pandas as pd
import requests

warnings.filterwarnings("ignore")

try:
    import yfinance as yf
except ImportError:
    print()
    print("ERROR: yfinance is not installed.")
    print("Install with: pip install yfinance pandas requests curl_cffi")
    print()
    sys.exit(1)

# yfinance logs every failed ticker; we report those ourselves.
logging.getLogger("yfinance").setLevel(logging.CRITICAL)


# =============================================================================
# CONFIGURATION
# =============================================================================

# Yahoo throttles heavy parallel use. If you see many rate-limit ERRORs,
# lower this to 4-6.
MAX_WORKERS = 8

# Attempts per request (only rate limits / network errors are retried).
MAX_RETRIES = 3

INITIAL_PERIOD = "3d"
FALLBACK_PERIOD = "7d"

REQUEST_TIMEOUT = 20

# If fewer than this share of symbols have the 15:29 candle on the signal
# day, the report shows a "data looks incomplete" warning. Kept low because
# illiquid stocks often have no trade in the last minute; when Yahoo's data
# is genuinely unfinished the share is close to 0%.
SESSION_COMPLETE_SHARE = 0.20


# =============================================================================
# UNIVERSE SIZE  <-- change this to scan more / fewer stocks
# =============================================================================
#
#   "NIFTY500"      ~500 stocks   (large + mid + small caps)
#   "TOTAL_MARKET"  ~750 stocks   (Nifty 500 + Nifty Microcap 250)  [default]
#   "ALL_NSE"       ~1800+ stocks (every EQ-series stock on NSE)
#
# If the chosen list cannot be downloaded, the scanner falls back to the next
# smaller list automatically (see get_stock_universe).
#
UNIVERSE_MODE = "TOTAL_MARKET"


# =============================================================================
# OFFICIAL UNIVERSE SOURCES
# =============================================================================

# Each index is tried on niftyindices.com first, then on NSE's archive server
# (niftyindices.com is sometimes blocked from cloud runners such as GitHub
# Actions).
INDEX_CSV_URLS = {
    "Nifty 500": [
        "https://www.niftyindices.com/IndexConstituent/ind_nifty500list.csv",
        "https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv",
    ],
    "Nifty Microcap 250": [
        "https://www.niftyindices.com/IndexConstituent/ind_niftymicrocap250_list.csv",
        "https://nsearchives.nseindia.com/content/indices/ind_niftymicrocap250_list.csv",
    ],
    "Nifty Total Market": [
        "https://www.niftyindices.com/IndexConstituent/ind_niftytotalmarket_list.csv",
        "https://nsearchives.nseindia.com/content/indices/ind_niftytotalmarket_list.csv",
    ],
}

# Reject obviously bad / partial downloads.
INDEX_MIN_SYMBOLS = {
    "Nifty 500": 450,
    "Nifty Microcap 250": 200,
    "Nifty Total Market": 650,
}

# NSE official equity security list (all EQ-series stocks).
NSE_EQUITY_URL = "https://nsearchives.nseindia.com/content/equities/sec_list.csv"


# =============================================================================
# REQUIRED 1-MINUTE CANDLES
# =============================================================================

# 3m 15:24 = 15:24,25,26      3m 15:27 = 15:27,28,29
NEEDED_HM = {1524, 1525, 1526, 1527, 1528, 1529}


# =============================================================================
# BUILT-IN FALLBACK UNIVERSE
# =============================================================================

NIFTY_50 = [
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
    "HCLTECH",
    "SUNPHARMA",
    "TITAN",
    "ULTRACEMCO",
    "NESTLEIND",
    "WIPRO",
    "ADANIENT",
    "ONGC",
    "NTPC",
    "POWERGRID",
    "M&M",
    "JSWSTEEL",
    "TATASTEEL",
    "TATAMOTORS",
    "COALINDIA",
    "BAJAJFINSV",
    "TECHM",
    "INDUSINDBK",
    "HDFCLIFE",
    "SBILIFE",
    "GRASIM",
    "DRREDDY",
    "DIVISLAB",
    "EICHERMOT",
    "BRITANNIA",
    "CIPLA",
    "APOLLOHOSP",
    "HEROMOTOCO",
    "BPCL",
    "TATACONSUM",
    "ADANIPORTS",
    "HINDALCO",
    "BAJAJ-AUTO",
    "SHRIRAMFIN",
    "LTIM",
    "UPL",
]

NIFTY_NEXT_150 = [
    "ABB",
    "ADANIENSOL",
    "ADANIGREEN",
    "ADANIPOWER",
    "AMBUJACEM",
    "DMART",
    "BANKBARODA",
    "BERGEPAINT",
    "BEL",
    "BOSCHLTD",
    "CANBK",
    "CHOLAFIN",
    "COLPAL",
    "DABUR",
    "DLF",
    "GAIL",
    "GODREJCP",
    "HAVELLS",
    "HAL",
    "ICICIGI",
    "ICICIPRULI",
    "IOC",
    "IRCTC",
    "IRFC",
    "JINDALSTEL",
    "JIOFIN",
    "LICI",
    "LODHA",
    "LUPIN",
    "MARICO",
    "MOTHERSON",
    "MRF",
    "NAUKRI",
    "NHPC",
    "PIDILITIND",
    "PFC",
    "PNB",
    "RECLTD",
    "SIEMENS",
    "SRF",
    "TATAPOWER",
    "TORNTPHARM",
    "TVSMOTOR",
    "UNIONBANK",
    "VBL",
    "VEDL",
    "ZOMATO",
    "ZYDUSLIFE",
    "PAYTM",
    "POLICYBZR",
    "PERSISTENT",
    "COFORGE",
    "MPHASIS",
    "OBEROIRLTY",
    "PIIND",
    "ASHOKLEY",
    "AUROPHARMA",
    "BANDHANBNK",
    "BATAINDIA",
    "BHARATFORG",
    "BHEL",
    "CGPOWER",
    "CONCOR",
    "CUMMINSIND",
    "DEEPAKNTR",
    "DIXON",
    "ESCORTS",
    "EXIDEIND",
    "FEDERALBNK",
    "GLAND",
    "GMRAIRPORT",
    "GODREJPROP",
    "GUJGASLTD",
    "HDFCAMC",
    "HINDPETRO",
    "IDEA",
    "IDFCFIRSTB",
    "IGL",
    "INDHOTEL",
    "INDIGO",
    "INDUSTOWER",
    "IPCALAB",
    "JSWENERGY",
    "JUBLFOOD",
    "KALYANKJIL",
    "L&TFH",
    "LALPATHLAB",
    "LAURUSLABS",
    "LTTS",
    "M&MFIN",
    "MANKIND",
    "MAXHEALTH",
    "METROPOLIS",
    "MFSL",
    "MUTHOOTFIN",
    "NATIONALUM",
    "NAVINFLUOR",
    "NMDC",
    "OFSS",
    "PAGEIND",
    "PATANJALI",
    "PETRONET",
    "PHOENIXLTD",
    "POLYCAB",
    "PRESTIGE",
    "RAMCOCEM",
    "RVNL",
    "SAIL",
    "SBICARD",
    "SCHAEFFLER",
    "SHREECEM",
    "SJVN",
    "SOLARINDS",
    "SONACOMS",
    "STARHEALTH",
    "SUNDARMFIN",
    "SUPREMEIND",
    "SUZLON",
    "SYNGENE",
    "TATACHEM",
    "TATACOMM",
    "TATAELXSI",
    "THERMAX",
    "TIINDIA",
    "TORNTPOWER",
    "TRENT",
    "TRIDENT",
    "UBL",
    "UCOBANK",
    "VOLTAS",
    "WHIRLPOOL",
    "YESBANK",
    "ZEEL",
    "ABCAPITAL",
    "ABFRL",
    "ALKEM",
    "APLAPOLLO",
    "APOLLOTYRE",
    "ASTRAL",
    "AUBANK",
    "BALKRISIND",
    "BANKINDIA",
    "BSOFT",
    "CANFINHOME",
    "CENTRALBK",
    "CROMPTON",
    "CYIENT",
    "DALBHARAT",
    "DELHIVERY",
    "DEVYANI",
    "EMAMILTD",
    "GICRE",
    "GLENMARK",
    "GNFC",
    "GODIGIT",
    "GRANULES",
    "GRSE",
    "HFCL",
    "HONAUT",
]

FALLBACK_UNIVERSE = list(dict.fromkeys(NIFTY_50 + NIFTY_NEXT_150))

# Old NSE symbols that are now listed under a different Yahoo ticker.
# Only matters for the built-in fallback list; the official CSVs already use
# current symbols. Edit if Yahoo lists any of these differently.
SYMBOL_ALIASES = {
    "ZOMATO": "ETERNAL",
    "L&TFH": "LTF",
    "TATAMOTORS": "TMPV",
}


def yahoo_ticker(symbol):
    return SYMBOL_ALIASES.get(symbol, symbol) + ".NS"


# =============================================================================
# HTTP HEADERS
# =============================================================================

NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0 Safari/537.36",
    "Accept": "text/csv,text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.niftyindices.com/",
}


# =============================================================================
# UNIVERSE LOADING
# =============================================================================


def normalize_symbols(values):

    symbols = []

    for value in values:
        symbol = str(value).strip().upper()
        if not symbol or symbol == "NAN":
            continue
        symbols.append(symbol)

    return list(dict.fromkeys(symbols))


def load_index_csv(name):
    """Download one NSE index constituent list. Returns symbols or None."""

    minimum = INDEX_MIN_SYMBOLS[name]

    print()
    print(f"Attempting to load {name} universe...")

    for url in INDEX_CSV_URLS[name]:
        try:
            host = url.split("/")[2]

            session = requests.Session()
            session.headers.update(
                {
                    **NSE_HEADERS,
                    "Referer": f"https://{host}/",
                }
            )

            with contextlib.suppress(Exception):
                session.get(f"https://{host}/", timeout=15)

            response = session.get(url, timeout=20)
            response.raise_for_status()

            df = pd.read_csv(StringIO(response.text))

            symbol_column = None
            for column in df.columns:
                if str(column).strip().lower() == "symbol":
                    symbol_column = column
                    break

            if symbol_column is None:
                msg = "Symbol column not found"
                raise ValueError(msg)

            symbols = normalize_symbols(df[symbol_column].dropna().tolist())

            if len(symbols) < minimum:
                msg = f"Only {len(symbols)} symbols returned"
                raise ValueError(msg)

            print(f"{name} loaded successfully: {len(symbols)} symbols")
            return symbols

        except Exception as e:
            print(f"{name} loading failed ({url.split('/')[2]}): {e}")

    return None


def load_nifty500():
    return load_index_csv("Nifty 500")


def load_total_market():
    """~750 stocks = Nifty 500 + Nifty Microcap 250."""

    # 1) The official Total Market list, if available.
    symbols = load_index_csv("Nifty Total Market")
    if symbols:
        return symbols

    # 2) Build it ourselves (Total Market is defined as exactly this union).
    base = load_index_csv("Nifty 500")
    micro = load_index_csv("Nifty Microcap 250")

    if base and micro:
        combined = list(dict.fromkeys(base + micro))
        print(f"Total Market built from Nifty 500 + Microcap 250: {len(combined)} symbols")
        return combined

    print("Could not build the Total Market universe.")
    return None


def load_nse_equity_list():

    try:
        print()
        print("Attempting to load NSE official equity list...")

        session = requests.Session()
        session.headers.update(
            {
                **NSE_HEADERS,
                "Referer": "https://www.nseindia.com/",
            }
        )

        with contextlib.suppress(Exception):
            session.get("https://www.nseindia.com/", timeout=15)

        response = session.get(NSE_EQUITY_URL, timeout=20)
        response.raise_for_status()

        df = pd.read_csv(StringIO(response.text))

        symbol_column = next((c for c in df.columns if "symbol" in str(c).lower()), None)
        series_column = next((c for c in df.columns if "series" in str(c).lower()), None)

        if symbol_column is None:
            msg = "NSE Symbol column not found"
            raise ValueError(msg)

        if series_column is not None:
            df = df[df[series_column].astype(str).str.strip().str.upper() == "EQ"]

        symbols = normalize_symbols(df[symbol_column].dropna().tolist())

        if len(symbols) < 300:
            msg = f"Only {len(symbols)} EQ symbols returned"
            raise ValueError(msg)

        print(f"NSE official equity list loaded: {len(symbols)} symbols")
        return symbols

    except Exception as e:
        print(f"NSE official list unavailable: {e}")
        return None


def get_stock_universe():

    print()
    print("=" * 70)
    print("LOADING NSE STOCK UNIVERSE")
    print(f"Requested mode: {UNIVERSE_MODE}")
    print("=" * 70)

    # Tried in order; the first list that loads is used.
    attempts = []

    if UNIVERSE_MODE == "ALL_NSE":
        attempts.append(("NSE official equity list (all EQ)", load_nse_equity_list))

    if UNIVERSE_MODE in ("ALL_NSE", "TOTAL_MARKET"):
        attempts.append(("Nifty Total Market (Nifty 500 + Microcap 250)", load_total_market))

    attempts.append(("Nifty 500 official CSV", load_nifty500))
    attempts.append(("NSE official equity list", load_nse_equity_list))

    for label, loader in attempts:
        symbols = loader()

        if symbols:
            return symbols, label

    print()
    print(f"Using built-in fallback universe: {len(FALLBACK_UNIVERSE)} symbols")

    return FALLBACK_UNIVERSE, "Built-in fallback"


# =============================================================================
# CLEAN YAHOO DATA
# =============================================================================


def clean_yahoo_data(df):

    if df is None or df.empty:
        return None

    df = df.copy()

    # Flatten MultiIndex columns if present.
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [column[0] for column in df.columns]

    df = df.reset_index()

    timestamp_column = None
    for candidate in ("Datetime", "Date", "datetime", "date", "index"):
        if candidate in df.columns:
            timestamp_column = candidate
            break

    if timestamp_column is None:
        return None

    ts = pd.to_datetime(df[timestamp_column], errors="coerce", utc=False)

    valid = ts.notna()
    if not valid.any():
        return None

    df = df.loc[valid].copy()
    ts = ts.loc[valid]

    # Convert to India time.
    ts = ts.dt.tz_convert("Asia/Kolkata") if ts.dt.tz is not None else ts.dt.tz_localize("Asia/Kolkata")

    if not all(c in df.columns for c in ("Open", "Close", "Volume")):
        return None

    out = pd.DataFrame(
        {
            "date": ts.dt.strftime("%Y-%m-%d").values,
            "hm": (ts.dt.hour * 100 + ts.dt.minute).values,
            "open": pd.to_numeric(df["Open"], errors="coerce").values,
            "close": pd.to_numeric(df["Close"], errors="coerce").values,
            "volume": pd.to_numeric(df["Volume"], errors="coerce").values,
        }
    )

    # Regular NSE session only.
    out = out[out["hm"].between(915, 1529)]

    out = out.dropna(subset=["open", "close", "volume"])

    out = out.drop_duplicates(subset=["date", "hm"], keep="last")

    if out.empty:
        return None

    return out


# =============================================================================
# YAHOO DOWNLOAD
# =============================================================================
#
# yf.Ticker(...).history() is used instead of yf.download(): download() keeps
# results in module-level globals and is NOT safe to call from several threads
# at once.
#

RATE_LIMIT_WORDS = ("rate limit", "rate-limit", "too many requests", "429")

DEAD_TICKER_WORDS = (
    "delisted",
    "no data found",
    "no price data",
    "not found",
    "404",
)


def yahoo_download(symbol, period):
    """Returns (dataframe, None) on success, or (None, reason).
    reason == "NO_DATA" means Yahoo has nothing for this ticker;
    any other string is a real error message."""

    ticker = yahoo_ticker(symbol)
    last_error = "NO_DATA"

    for attempt in range(MAX_RETRIES):
        try:
            df = yf.Ticker(ticker).history(
                period=period,
                interval="1m",
                auto_adjust=False,
                actions=False,
                prepost=False,
                timeout=REQUEST_TIMEOUT,
                raise_errors=True,
            )

            cleaned = clean_yahoo_data(df)

            if cleaned is not None and not cleaned.empty:
                return cleaned, None

            return None, "NO_DATA"

        except Exception as e:
            message = str(e).replace("\n", " ")
            lowered = message.lower()

            rate_limited = any(w in lowered for w in RATE_LIMIT_WORDS)
            dead = any(w in lowered for w in DEAD_TICKER_WORDS)

            # Invalid / delisted ticker: do not retry.
            if dead and not rate_limited:
                return None, "NO_DATA"

            last_error = message[:240]

            if attempt < MAX_RETRIES - 1:
                base = 4.0 if rate_limited else 1.0
                time.sleep(base * (2**attempt) + random.uniform(0.2, 1.0))

    return None, last_error


def fetch_symbol_rows(symbol):
    """Returns (rows, info). If rows is None, info is "NO_DATA" or an
    error message. Otherwise info is "OK" or "FALLBACK"."""

    # Small random delay so the workers do not hit Yahoo in one burst.
    time.sleep(random.uniform(0.05, 0.25))

    rows, error = yahoo_download(symbol, INITIAL_PERIOD)

    if rows is not None:
        return rows, "OK"

    # Only one extra request, and only if Yahoo simply returned nothing.
    # (No point retrying with a longer period after a rate-limit error.)
    if error == "NO_DATA":
        rows2, error2 = yahoo_download(symbol, FALLBACK_PERIOD)
        if rows2 is not None:
            return rows2, "FALLBACK"
        return None, error2

    return None, error


# =============================================================================
# STRATEGY HELPERS
# =============================================================================


def candle_direction(open_price, close_price):

    if open_price is None or close_price is None:
        return 0

    if close_price > open_price:
        return 1

    if close_price < open_price:
        return -1

    return 0


def aggregate_3m(m, minutes):
    """3-minute candle built from whichever of the 3 one-minute candles
    exist. A minute with no trades is simply absent from Yahoo's data."""

    candles = [m[minute] for minute in minutes if minute in m]

    if not candles:
        return {"open": None, "close": None, "volume": 0.0}

    return {
        "open": candles[0][0],
        "close": candles[-1][1],
        "volume": sum(c[2] for c in candles),
    }


# =============================================================================
# EVALUATE STRATEGY
# =============================================================================


def evaluate_rows(rows):

    if rows is None or rows.empty:
        return {"status": "NO_DATA"}

    # ---------------------------------------------------------------------
    # DATE -> {minute: (open, close, volume)}
    # ---------------------------------------------------------------------

    by_date = {}

    for date, hm, o, c, v in zip(rows["date"], rows["hm"], rows["open"], rows["close"], rows["volume"], strict=False):
        by_date.setdefault(date, {})[int(hm)] = (float(o), float(c), float(v))

    # ---------------------------------------------------------------------
    # SIGNAL DAY = latest day that has any candle in the 15:24-15:29 window.
    # (If the scan runs before the close / next morning, this skips a day
    # that has no closing-window data at all.)
    # ---------------------------------------------------------------------

    dates_with_window = sorted(d for d, minute_map in by_date.items() if any(hm in minute_map for hm in NEEDED_HM))

    signal_date = dates_with_window[-1] if dates_with_window else max(by_date)

    m = by_date[signal_date]

    missing = [hm for hm in sorted(NEEDED_HM) if hm not in m]
    last_hm = max(m)

    # No candle at all in the closing window: nothing to evaluate.
    if len(missing) == len(NEEDED_HM):
        return {
            "status": "INCOMPLETE",
            "date": signal_date,
            "missing": missing,
            "last_hm": last_hm,
        }

    # ---------------------------------------------------------------------
    # 3-MIN CANDLES
    # ---------------------------------------------------------------------

    candle_1524 = aggregate_3m(m, [1524, 1525, 1526])
    candle_1527 = aggregate_3m(m, [1527, 1528, 1529])

    # ---------------------------------------------------------------------
    # DIRECTIONS
    # ---------------------------------------------------------------------

    d1524 = candle_direction(candle_1524["open"], candle_1524["close"])
    d1527 = candle_direction(candle_1527["open"], candle_1527["close"])

    d1528 = candle_direction(*m[1528][:2]) if 1528 in m else 0
    d1529 = candle_direction(*m[1529][:2]) if 1529 in m else 0

    # ---------------------------------------------------------------------
    # VOLUMES
    # ---------------------------------------------------------------------

    v1524 = candle_1524["volume"]
    v1527 = candle_1527["volume"]
    v1528 = m[1528][2] if 1528 in m else 0.0
    v1529 = m[1529][2] if 1529 in m else 0.0

    # CONDITION 1: 3m 15:24 volume > 3m 15:27 volume
    cond1 = d1524 != 0 and v1524 > v1527

    # CONDITION 2: 1m 15:28 / 15:29 opposite trends, 15:28 volume larger
    cond2 = d1528 != 0 and d1529 not in (0, d1528) and v1528 > v1529

    # CONDITION 3: 1m 15:28 trend == 3m 15:24 trend
    cond3 = d1528 != 0 and d1524 != 0 and d1528 == d1524

    passed = cond1 and cond2 and cond3

    # FINAL DIRECTION = 1-min 15:28
    if d1528 == 1:
        direction = "LONG"
    elif d1528 == -1:
        direction = "SHORT"
    else:
        direction = None

    return {
        "status": "PASS" if passed else "FAIL",
        "date": signal_date,
        "direction": direction if passed else None,
        "raw_direction": direction,
        "cond1": cond1,
        "cond2": cond2,
        "cond3": cond3,
        "missing": missing,
        "last_hm": last_hm,
        "details": {
            "d1524": d1524,
            "d1527": d1527,
            "d1528": d1528,
            "d1529": d1529,
            "15:24_vol": v1524,
            "15:27_vol": v1527,
            "15:28_vol": v1528,
            "15:29_vol": v1529,
        },
    }


# =============================================================================
# SCAN ONE SYMBOL
# =============================================================================


def scan_one_symbol(symbol):

    try:
        rows, info = fetch_symbol_rows(symbol)

        if rows is None:
            if info == "NO_DATA":
                return {
                    "symbol": symbol,
                    "status": "NO_DATA",
                    "data_status": "NO_DATA",
                }

            return {
                "symbol": symbol,
                "status": "ERROR",
                "data_status": "ERROR",
                "error": info,
            }

        result = evaluate_rows(rows)
        result["symbol"] = symbol
        result["data_status"] = info

        return result

    except Exception as e:
        return {
            "symbol": symbol,
            "status": "ERROR",
            "data_status": "ERROR",
            "error": f"{type(e).__name__}: {e}"[:240],
        }


# =============================================================================
# PARALLEL SCAN
# =============================================================================


def scan_all_symbols(symbols):

    total = len(symbols)
    results = []
    completed = 0
    start = time.time()

    print()
    print("=" * 70)
    print(f"Scanning {total} symbols with {MAX_WORKERS} workers")
    print("=" * 70)
    print()

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(scan_one_symbol, symbol): symbol for symbol in symbols}

        for future in as_completed(futures):
            symbol = futures[future]

            try:
                result = future.result()
            except Exception as e:
                result = {
                    "symbol": symbol,
                    "status": "ERROR",
                    "error": str(e)[:240],
                }

            results.append(result)
            completed += 1

            if result.get("status") == "PASS":
                print(f"[{completed}/{total}] {symbol:<15} MATCH {result.get('direction')}")
            elif completed % 10 == 0 or completed == total:
                print(f"Progress: {completed}/{total}")

    results.sort(key=lambda x: x.get("symbol", ""))

    return results, time.time() - start


# =============================================================================
# POST-SCAN CHECKS
# =============================================================================


def mark_stale(results):
    """Symbols whose latest usable day differs from the day most symbols
    used cannot be traded off today's close, so they are marked STALE."""

    dates = [r["date"] for r in results if r.get("date")]

    if not dates:
        return None

    reference = Counter(dates).most_common(1)[0][0]

    for r in results:
        if r.get("date") and r["date"] != reference:
            r["status"] = "STALE"
            r["direction"] = None

    return reference


def session_warning(results):
    """Warn when Yahoo's data for the signal day looks unfinished."""

    with_data = [r for r in results if r.get("last_hm") is not None]

    if not with_data:
        return None

    done = sum(1 for r in with_data if r["last_hm"] >= 1529)
    share = done / len(with_data)

    if share < SESSION_COMPLETE_SHARE:
        return (
            f"Only {share:.0%} of symbols have the 15:29 candle on the "
            f"signal day. Yahoo's data for that day is probably not "
            f"complete yet (or the market has not closed). "
            f"Re-run later - these results are unreliable."
        )

    return None


# =============================================================================
# HTML HELPERS
# =============================================================================

DASH = "&mdash;"


def esc(value):
    return html.escape(str(value))


def cell(value):
    if value is None or value == "":
        return DASH
    return esc(value)


def badge(value):

    if value is None:
        return DASH

    if value:
        return '<span class="badge pass">PASS</span>'

    return '<span class="badge fail">FAIL</span>'


def trend_name(d):
    return {1: "UP", -1: "DOWN"}.get(d, "FLAT")


def hm_text(hm):
    return f"{hm // 100:02d}:{hm % 100:02d}"


CSS = """
body { font-family: Arial, sans-serif; background: #f5f5f5; color: #222;
       margin: 0; padding: 25px; }
.container { max-width: 1500px; margin: auto; }
h1 { margin-bottom: 5px; }
.subtitle { color: #777; line-height: 1.6; }
.warn { background: #fff3cd; border: 1px solid #e0c36a; color: #6b5200;
        border-radius: 8px; padding: 12px 16px; margin: 18px 0; }
.stats { display: flex; flex-wrap: wrap; gap: 10px; margin: 20px 0; }
.stat { background: white; padding: 15px 20px; border-radius: 8px;
        border: 1px solid #ddd; }
.stat b { font-size: 22px; display: block; }
.match-box { background: white; border: 1px solid #ddd; border-radius: 8px;
             padding: 20px; margin-bottom: 20px; }
.match { padding: 9px 0; border-bottom: 1px solid #eee; }
.direction { display: inline-block; padding: 3px 7px; border-radius: 4px;
             font-size: 11px; font-weight: bold; margin-right: 8px; }
.long { background: #dff5e5; color: #08752f; }
.short { background: #f8dddd; color: #a52222; }
.date { color: #777; margin-left: 8px; }
table { width: 100%; border-collapse: collapse; background: white;
        font-size: 13px; }
th { background: #ededed; padding: 10px; text-align: left;
     position: sticky; top: 0; }
td { padding: 9px 10px; border-top: 1px solid #eee; vertical-align: top; }
.symbol { font-weight: bold; }
small { color: #777; font-size: 10px; }
.badge { display: inline-block; padding: 2px 6px; border-radius: 4px;
         font-size: 10px; font-weight: bold; }
.badge.pass { background: #dff5e5; color: #08752f; }
.badge.fail { background: #f8dddd; color: #a52222; }
.pass { color: #08752f; font-weight: bold; }
.fail { color: #999; }
.skip { color: #b07000; }
.none { color: #777; }
.footer { margin-top: 25px; color: #777; font-size: 12px; line-height: 1.7; }
"""


def build_table_row(r):

    details = r.get("details")
    status = r.get("status", "UNKNOWN")

    status_class = {"PASS": "pass", "FAIL": "fail"}.get(status, "skip")

    if details:
        t1 = (
            f"15:24 {trend_name(details['d1524'])} "
            f"vol {details['15:24_vol']:,.0f} &gt; "
            f"15:27 vol {details['15:27_vol']:,.0f}"
        )
        t2 = (
            f"15:28 {trend_name(details['d1528'])} "
            f"vol {details['15:28_vol']:,.0f} &gt; "
            f"15:29 {trend_name(details['d1529'])} "
            f"vol {details['15:29_vol']:,.0f}"
        )
        t3 = f"1M 15:28 {trend_name(details['d1528'])} = 3M 15:24 {trend_name(details['d1524'])}"
    else:
        t1 = t2 = t3 = ""

    data_text = cell(r.get("data_status"))

    if r.get("missing"):
        data_text += "<br><small>missing: " + ", ".join(hm_text(h) for h in r["missing"]) + "</small>"

    if r.get("error"):
        data_text += f"<br><small>{esc(r['error'][:120])}</small>"

    return f"""
<tr>
<td class="symbol">{esc(r.get("symbol", ""))}</td>
<td>{cell(r.get("date"))}</td>
<td>{cell(r.get("direction"))}</td>
<td>{badge(r.get("cond1"))}<br><small>{t1}</small></td>
<td>{badge(r.get("cond2"))}<br><small>{t2}</small></td>
<td>{badge(r.get("cond3"))}<br><small>{t3}</small></td>
<td class="{status_class}">{esc(status)}</td>
<td>{data_text}</td>
</tr>
"""


# =============================================================================
# GENERATE HTML
# =============================================================================


def generate_html_report(results, elapsed, universe_source):

    def count(name):
        return sum(1 for r in results if r.get("status") == name)

    matches = [r for r in results if r.get("status") == "PASS"]

    if matches:
        match_html = "".join(
            '<div class="match">'
            f'<span class="direction '
            f'{"long" if r["direction"] == "LONG" else "short"}">'
            f"{esc(r['direction'])}</span>"
            f"<b>{esc(r['symbol'])}</b>"
            f'<span class="date">Signal day: {cell(r.get("date"))}</span>'
            "</div>"
            for r in matches
        )
    else:
        match_html = '<div class="none">No stocks matched today.</div>'

    sorted_results = sorted(
        results,
        key=lambda x: (x.get("status") != "PASS", x.get("symbol", "")),
    )

    table_rows = "".join(build_table_row(r) for r in sorted_results)

    warning = session_warning(results)
    warning_html = f'<div class="warn">{esc(warning)}</div>' if warning else ""

    scan_time = pd.Timestamp.now(tz="Asia/Kolkata").strftime("%Y-%m-%d %H:%M:%S IST")

    stats = [
        (len(results), "Stocks scanned"),
        (len(matches), "Matches"),
        (count("FAIL"), "No match"),
        (count("INCOMPLETE"), "Incomplete"),
        (count("STALE"), "Stale"),
        (count("NO_DATA"), "No data"),
        (count("ERROR"), "Errors"),
        (f"{elapsed:.1f}s", "Scan time"),
    ]

    stats_html = "".join(f'<div class="stat"><b>{value}</b>{label}</div>' for value, label in stats)

    document = (
        '<!DOCTYPE html>\n<html>\n<head>\n<meta charset="UTF-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "<title>NSE Daily Momentum Scanner</title>\n"
        f'<style>{CSS}</style>\n</head>\n<body>\n<div class="container">\n'
        "<h1>NSE Daily Momentum Scanner</h1>\n"
        f'<div class="subtitle">Generated: {esc(scan_time)}<br>'
        f"Universe: {esc(universe_source)}<br>"
        "Yahoo Finance 1-minute data</div>\n"
        f"{warning_html}\n"
        f'<div class="stats">{stats_html}</div>\n'
        f'<div class="match-box"><h2>Matches</h2>{match_html}</div>\n'
        "<table>\n<thead>\n<tr>"
        "<th>Symbol</th>"
        "<th>Signal Day</th>"
        "<th>Direction</th>"
        "<th>Cond 1<br><small>3M 15:24 vol &gt; 15:27 vol</small></th>"
        "<th>Cond 2<br><small>1M 15:28 / 15:29 opposite, "
        "15:28 vol &gt; 15:29 vol</small></th>"
        "<th>Cond 3<br><small>1M 15:28 trend = 3M 15:24 trend</small></th>"
        "<th>Result</th>"
        "<th>Data</th>"
        "</tr>\n</thead>\n<tbody>\n"
        f"{table_rows}\n"
        "</tbody>\n</table>\n"
        '<div class="footer">\n<b>CURRENT STRATEGY</b><br>\n'
        "1. 3-min 15:24 volume must be greater than 15:27 volume.<br>\n"
        "2. 3-min 15:24 and 15:27 trend relationship is ignored. "
        "They can be the same or opposite.<br>\n"
        "3. 1-min 15:28 and 15:29 must be opposite trends.<br>\n"
        "4. 1-min 15:28 volume must be greater than 15:29 volume.<br>\n"
        "5. 1-min 15:28 trend must match 3-min 15:24 trend.<br>\n"
        "6. Final direction = 1-min 15:28.<br>\n"
        "<b>Entry:</b> Next trading day 09:15 open.<br>\n"
        "<b>Exit:</b> 15:27.<br><br>\n"
        "<b>Data notes:</b> Yahoo returns no row for a minute with no trades. "
        "Such a minute is treated as volume 0 with no trend and is listed "
        'under "missing" in the Data column. INCOMPLETE = no candle at all in '
        "the 15:24-15:29 window. STALE = latest data is from a different day "
        "than most symbols.\n</div>\n"
        "</div>\n</body>\n</html>\n"
    )

    with open("index.html", "w", encoding="utf-8") as file:
        file.write(document)


# =============================================================================
# MAIN
# =============================================================================


def main():

    print()
    print("=" * 70)
    print("NSE EOD MOMENTUM SCANNER")
    print("=" * 70)
    print()
    print("yfinance version:", getattr(yf, "__version__", "unknown"))

    universe, source = get_stock_universe()

    print()
    print("=" * 70)
    print(f"FINAL STOCK UNIVERSE: {len(universe)}")
    print(f"SOURCE: {source}")
    print("=" * 70)

    results, elapsed = scan_all_symbols(universe)

    reference_date = mark_stale(results)

    matches = [r for r in results if r.get("status") == "PASS"]

    print()
    print("=" * 70)
    print("SCAN COMPLETE")
    print("=" * 70)
    print(f"Universe    : {len(universe)}")
    print(f"Signal day  : {reference_date}")
    print(f"Matches     : {len(matches)}")
    print(f"Time        : {elapsed:.1f} seconds")
    print()

    if matches:
        print("MATCHES:")
        for result in matches:
            print(f"  {result['symbol']:<15}{result['direction']:<7}{result['date']}")
    else:
        print("NO MATCHES.")

    print()

    for name in ("PASS", "FAIL", "INCOMPLETE", "STALE", "NO_DATA", "ERROR"):
        n = sum(1 for r in results if r.get("status") == name)
        print(f"{name:<11}: {n}")

    # Show a few distinct error messages so problems are easy to diagnose.
    error_messages = list(dict.fromkeys(r.get("error", "") for r in results if r.get("status") == "ERROR"))[:5]

    if error_messages:
        print()
        print("SAMPLE ERRORS:")
        for message in error_messages:
            print(f"  - {message}")

    warning = session_warning(results)
    if warning:
        print()
        print("WARNING:", warning)

    generate_html_report(results, elapsed, source)

    print()
    print("HTML report: index.html")
    print()
    print("=" * 70)


if __name__ == "__main__":
    main()
