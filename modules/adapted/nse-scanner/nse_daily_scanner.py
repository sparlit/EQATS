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
# Uses Yahoo Finance NATIVE 5-minute candles. No Parquet, no nselib.
# Universe: Nifty 500 CSV -> NSE equity list -> built-in fallback.
# Output: index.html (a plain dashboard)
#
# =============================================================================
# STRATEGY  (5-minute timeframe, read on the previous day only)
# =============================================================================
#
# "Previous day" = the most recent COMPLETED trading session (today is never
# used - today is the entry day).
#
# NSE 5-minute candles are labelled by their start time: 09:15 ... 15:25.
# 15:25 is the LAST candle, 15:20 the last second candle, 09:15 the morning
# candle.
#
# 1) The 15:20 candle's volume is greater than the 15:25 candle's volume.
# 2) The 09:15 candle's trend is the same as the 15:20 candle's trend.
#
# DIRECTION: the shared trend (up = LONG, down = SHORT).
# TRADE:     Entry = today's 09:15 OPEN, Exit = EXIT_TIME_LABEL.
#
# A candle with no trades is simply absent from Yahoo's data and is treated
# as "no trend", so it can never satisfy the trend condition. The one case
# that could create a false signal is a missing 15:25 candle (its volume would
# read as zero), so that case is flagged "verify".
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

# Native 5-minute candles. Yahoo keeps about 60 days of 5-minute history,
# so a month-long fallback is safely inside the limit.
INTERVAL = "5m"

INITIAL_PERIOD = "5d"

FALLBACK_PERIOD = "1mo"

REQUEST_TIMEOUT = 20

# If fewer than this share of scanned symbols have all 3 required 5-minute
# candles, the report shows a "data looks incomplete" warning. Kept low
# because illiquid stocks often have a no-trade candle; when Yahoo's data
# is genuinely broken the share is close to 0%.
SESSION_COMPLETE_SHARE = 0.20

# Exit time shown in the report (unchanged from before).
EXIT_TIME_LABEL = "15:27"


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
# REQUIRED 5-MINUTE CANDLES
# =============================================================================

# The three native 5-minute candles the strategy reads, all on the previous
# day (P). Slot keys are "<day><hhmm>", e.g. "P1520" = previous day's 15:20.
SLOTS = [("P", 915), ("P", 1520), ("P", 1525)]

SLOT_KEYS = [f"{day}{hm:04d}" for day, hm in SLOTS]


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
                raise ValueError("Symbol column not found")

            symbols = normalize_symbols(df[symbol_column].dropna().tolist())

            if len(symbols) < minimum:
                raise ValueError(f"Only {len(symbols)} symbols returned")

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
            raise ValueError("NSE Symbol column not found")

        if series_column is not None:
            df = df[df[series_column].astype(str).str.strip().str.upper() == "EQ"]

        symbols = normalize_symbols(df[symbol_column].dropna().tolist())

        if len(symbols) < 300:
            raise ValueError(f"Only {len(symbols)} EQ symbols returned")

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
    if ts.dt.tz is not None:
        ts = ts.dt.tz_convert("Asia/Kolkata")
    else:
        ts = ts.dt.tz_localize("Asia/Kolkata")

    if not all(c in df.columns for c in ("Open", "Close", "Volume")):
        return None

    open_ = pd.to_numeric(df["Open"], errors="coerce")
    close_ = pd.to_numeric(df["Close"], errors="coerce")
    # High/Low power the candlestick visuals; fall back to open/close for
    # any feed that happens to omit them so nothing downstream breaks.
    high_ = pd.to_numeric(df["High"], errors="coerce") if "High" in df.columns else None
    low_ = pd.to_numeric(df["Low"], errors="coerce") if "Low" in df.columns else None

    out = pd.DataFrame(
        {
            "date": ts.dt.strftime("%Y-%m-%d").values,
            "hm": (ts.dt.hour * 100 + ts.dt.minute).values,
            "open": open_.values,
            "high": (
                high_ if high_ is not None else pd.concat([open_, close_], axis=1).max(axis=1)
            ).values,
            "low": (
                low_ if low_ is not None else pd.concat([open_, close_], axis=1).min(axis=1)
            ).values,
            "close": close_.values,
            "volume": pd.to_numeric(df["Volume"], errors="coerce").values,
        }
    )

    # Regular NSE session only.
    out = out[out["hm"].between(915, 1529)]

    out = out.dropna(subset=["open", "high", "low", "close", "volume"])

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
                interval=INTERVAL,
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


def completed_day_count(rows):
    """Number of distinct trading sessions strictly before today."""

    today = pd.Timestamp.now(tz="Asia/Kolkata").strftime("%Y-%m-%d")

    return len({d for d in rows["date"].unique() if d != today})


def fetch_symbol_rows(symbol):
    """Returns (rows, info). If rows is None, info is "NO_DATA" or an
    error message. Otherwise info is "OK" or "FALLBACK"."""

    # Small random delay so the workers do not hit Yahoo in one burst.
    time.sleep(random.uniform(0.05, 0.25))

    rows, error = yahoo_download(symbol, INITIAL_PERIOD)

    # The strategy reads one completed session, so a short window (long
    # weekend / holidays) gets one longer retry. A rate-limit error does
    # not: a longer request would only be throttled again.
    if rows is not None and completed_day_count(rows) >= 1:
        return rows, "OK"

    if rows is not None or error == "NO_DATA":
        rows2, error2 = yahoo_download(symbol, FALLBACK_PERIOD)

        if rows2 is not None:
            return rows2, "FALLBACK"

        if rows is not None:
            return rows, "OK"  # evaluate_rows will report INCOMPLETE

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


def entry_session_day(today_str):
    """Entry happens at the next session's open. Today is the entry day on
    a weekday; on a weekend it rolls forward to Monday. (Exchange holidays
    are not modelled - there is no holiday calendar to check them against.)"""

    day = pd.Timestamp(today_str)

    while day.weekday() >= 5:
        day += pd.Timedelta(days=1)

    return day.strftime("%Y-%m-%d")


def slot_label(key):
    """'P1520' -> 'P 15:20' (used in missing/verify notes)."""

    return f"{key[0]} {hm_text(int(key[1:]))}"


def evaluate_rows(rows):
    """Native 5-minute strategy, read on the previous day (P) only.

    P = the latest completed session. Entry day = today. NSE 5-minute
    candles are labelled by start time: 09:15 is the morning candle, 15:25
    the last candle and 15:20 the last second candle.

    1) P's 15:20 candle has more volume than P's 15:25 candle.
    2) P's 09:15 candle trends the same way as P's 15:20 candle.

    Direction = that shared trend (up is LONG, down is SHORT).
    """

    if rows is None or rows.empty:
        return {"status": "NO_DATA"}

    by_date = {}

    for date, hm, o, c, v in zip(
        rows["date"], rows["hm"], rows["open"], rows["close"], rows["volume"], strict=False
    ):
        by_date.setdefault(date, {})[int(hm)] = (float(o), float(c), float(v))

    # Today is the entry day, so it is never read, whether the scan runs
    # before the open or mid-session.
    today = pd.Timestamp.now(tz="Asia/Kolkata").strftime("%Y-%m-%d")
    entry = entry_session_day(today)
    dates = sorted(d for d in by_date if d != today)

    if not dates:
        return {
            "status": "INCOMPLETE",
            "date": None,
            "previous_day": None,
            "entry_day": entry,
            "missing": [slot_label(k) for k in SLOT_KEYS],
            "note": "no completed trading day of data before today",
        }

    previous_day = dates[-1]
    day = by_date[previous_day]

    candles, missing = {}, []

    for _, hm in SLOTS:
        key = f"P{hm:04d}"
        bar = day.get(hm)

        if bar is None:
            candles[key] = None
            missing.append(slot_label(key))
        else:
            o, c, v = bar
            candles[key] = {"open": o, "close": c, "volume": int(round(v))}

    if len(missing) == len(SLOTS):
        return {
            "status": "INCOMPLETE",
            "date": previous_day,
            "previous_day": previous_day,
            "entry_day": entry,
            "missing": missing,
        }

    def trend(key):
        c = candles.get(key)
        return candle_direction(c["open"], c["close"]) if c else 0

    def volume(key):
        c = candles.get(key)
        return c["volume"] if c else 0

    d0915, d1520 = trend("P0915"), trend("P1520")
    v1520, v1525 = volume("P1520"), volume("P1525")

    # CONDITION 1: 15:20 volume is greater than 15:25 volume.
    cond1 = candles["P1520"] is not None and v1520 > v1525

    # CONDITION 2: 09:15 trend is the same as the 15:20 trend. A candle with
    # no trades has no trend, so it can never match.
    cond2 = d0915 != 0 and d0915 == d1520

    passed = cond1 and cond2

    direction = "LONG" if d1520 == 1 else "SHORT" if d1520 == -1 else None

    # A missing 15:25 candle reads as zero volume, which can turn condition 1
    # into a false pass. It is the only missing-data case that can create a
    # signal (any other missing candle has no trend and can only block one).
    verify_notes = []
    if candles["P1525"] is None:
        verify_notes.append("P 15:25 has no data, so its volume was read as zero")

    return {
        "status": "PASS" if passed else "FAIL",
        "date": previous_day,
        "previous_day": previous_day,
        "entry_day": entry,
        "direction": direction if passed else None,
        "cond1": cond1,
        "cond2": cond2,
        "missing": missing,
        "verify_notes": verify_notes,
        "needs_verify": bool(verify_notes),
        "details": {
            "dP0915": d0915,
            "dP1520": d1520,
            "P1520_vol": v1520,
            "P1525_vol": v1525,
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
    """A symbol whose previous day differs from the one most symbols used (a
    suspended stock, a missing day) cannot be compared fairly, so it is
    marked STALE instead of producing a signal. Returns the reference day."""

    evaluated = [r for r in results if r.get("status") in ("PASS", "FAIL")]
    days = [r["previous_day"] for r in evaluated if r.get("previous_day")]

    if not days:
        return None

    reference = Counter(days).most_common(1)[0][0]

    for r in evaluated:
        if r.get("previous_day") != reference:
            r["status"] = "STALE"
            r["direction"] = None

    return reference


def session_warning(results):
    """Warn when a large share of symbols are missing some of the 3 required
    5-minute candles - a sign of a broad Yahoo data-quality issue, not just
    isolated thin trading."""

    evaluated = [r for r in results if r.get("status") in ("PASS", "FAIL")]

    if not evaluated:
        return None

    complete = sum(1 for r in evaluated if not r.get("missing"))
    share = complete / len(evaluated)

    if share < SESSION_COMPLETE_SHARE:
        return (
            f"Only {share:.0%} of scanned symbols have all 3 required "
            f"5-minute candles on the previous day. "
            f"Yahoo's data may be unusually incomplete - treat matches with "
            f"extra caution and verify on TradingView."
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


def trend_name(d):
    return {1: "Up", -1: "Down"}.get(d, "Flat")


def hm_text(hm):
    return f"{hm // 100:02d}:{hm % 100:02d}"


def fmt_day(value):
    """'2026-09-28' -> 'Mon 28 Sep 2026'."""

    if not value:
        return "\u2013"

    try:
        ts = pd.Timestamp(value)
    except Exception:
        return str(value)

    return f"{ts.strftime('%a')} {ts.day} {ts.strftime('%b %Y')}"


def badge(value):

    if value is None:
        return DASH

    if value:
        return '<span class="badge pass">PASS</span>'

    return '<span class="badge fail">FAIL</span>'


STATUS_LABEL = {
    "PASS": "PASS",
    "FAIL": "FAIL",
    "INCOMPLETE": "INCOMPLETE",
    "STALE": "STALE",
    "NO_DATA": "NO DATA",
    "ERROR": "ERROR",
}

STATUS_RANK = {"PASS": 0, "FAIL": 1, "INCOMPLETE": 2, "STALE": 3, "ERROR": 4, "NO_DATA": 5}

CSS = """
body {
    font-family: Arial, sans-serif;
    background: #f5f5f5;
    color: #222;
    margin: 0;
    padding: 25px;
}
.container { max-width: 1500px; margin: auto; }
h1 { margin-bottom: 5px; }
.subtitle { color: #777; line-height: 1.6; }
.warn {
    background: #fff3cd; border: 1px solid #e0c36a; color: #6b5200;
    border-radius: 8px; padding: 12px 16px; margin: 18px 0;
}
.stats { display: flex; flex-wrap: wrap; gap: 10px; margin: 20px 0; }
.stat {
    background: white; padding: 15px 20px; border-radius: 8px;
    border: 1px solid #ddd;
}
.stat b { font-size: 22px; display: block; }
.match-box {
    background: white; border: 1px solid #ddd; border-radius: 8px;
    padding: 20px; margin-bottom: 20px;
}
.matches { column-width: 300px; column-gap: 28px; }
.match {
    padding: 9px 0; border-bottom: 1px solid #eee;
    break-inside: avoid;
}
.direction {
    display: inline-block; padding: 3px 7px; border-radius: 4px;
    font-size: 11px; font-weight: bold; margin-right: 8px;
}
.long { background: #dff5e5; color: #08752f; }
.short { background: #f8dddd; color: #a52222; }
.date { color: #777; margin-left: 8px; font-size: 12px; }
.verify {
    display: inline-block; margin-left: 8px; padding: 1px 6px;
    border-radius: 4px; background: #fff3cd; color: #6b5200;
    font-size: 10px; font-weight: bold;
}
.table-wrap { overflow-x: auto; }
table {
    width: 100%; border-collapse: collapse; background: white; font-size: 13px;
}
th {
    background: #ededed; padding: 10px; text-align: left;
    position: sticky; top: 0;
}
td { padding: 9px 10px; border-top: 1px solid #eee; vertical-align: top; }
.symbol { font-weight: bold; }
small { color: #777; font-size: 10px; }
.badge {
    display: inline-block; padding: 2px 6px; border-radius: 4px;
    font-size: 10px; font-weight: bold;
}
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
        t1 = f"P 15:20 vol {details['P1520_vol']:,.0f} &gt; P 15:25 vol {details['P1525_vol']:,.0f}"
        t2 = f"P 09:15 {trend_name(details['dP0915'])} / P 15:20 {trend_name(details['dP1520'])}"
    else:
        t1 = t2 = ""

    verify_html = ""
    if r.get("needs_verify"):
        verify_html = '<br><span class="verify">verify: P 15:25 missing</span>'

    data_label = {
        "OK": "OK",
        "FALLBACK": "Fallback (1mo)",
        "NO_DATA": "No data",
        "ERROR": "Error",
    }.get(r.get("data_status"), r.get("data_status"))

    data_text = cell(data_label)

    if r.get("missing"):
        data_text += "<br><small>missing: " + ", ".join(esc(m) for m in r["missing"]) + "</small>"

    if r.get("error"):
        data_text += f"<br><small>{esc(r['error'][:120])}</small>"

    return f"""
<tr>
<td class="symbol">{esc(r.get("symbol", ""))}</td>
<td>{esc(r["previous_day"]) if r.get("previous_day") else DASH}</td>
<td>{cell(r.get("direction"))}</td>
<td>{badge(r.get("cond1"))}<br><small>{t1}</small></td>
<td>{badge(r.get("cond2"))}<br><small>{t2}</small></td>
<td class="{status_class}">{esc(STATUS_LABEL.get(status, status))}{verify_html}</td>
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
    matches.sort(key=lambda r: (r.get("direction") != "LONG", r.get("symbol", "")))

    longs = sum(1 for r in matches if r.get("direction") == "LONG")
    shorts = len(matches) - longs

    def most_common(field):
        c = Counter(r[field] for r in results if r.get(field)).most_common(1)
        return c[0][0] if c else None

    previous_day = most_common("previous_day")
    entry_day = most_common("entry_day") or entry_session_day(
        pd.Timestamp.now(tz="Asia/Kolkata").strftime("%Y-%m-%d")
    )

    scan_time = pd.Timestamp.now(tz="Asia/Kolkata").strftime("%Y-%m-%d %H:%M:%S IST")

    warning = session_warning(results)
    warning_html = f'<div class="warn">{esc(warning)}</div>' if warning else ""

    # ---- matches ----

    if matches:
        match_html = "".join(
            '<div class="match">'
            f'<span class="direction {"long" if r["direction"] == "LONG" else "short"}">'
            f"{esc(r['direction'])}</span>"
            f"<b>{esc(r['symbol'])}</b>"
            f'<span class="date">Previous day: {esc(r.get("previous_day", ""))}</span>'
            + (
                '<span class="verify">verify: P 15:25 missing</span>'
                if r.get("needs_verify")
                else ""
            )
            + "</div>"
            for r in matches
        )
    else:
        match_html = '<div class="none">No stocks matched.</div>'

    # ---- table ----

    sorted_results = sorted(
        results,
        key=lambda x: (STATUS_RANK.get(x.get("status"), 9), x.get("symbol", "")),
    )

    table_rows = "".join(build_table_row(r) for r in sorted_results)

    stats = [
        (len(results), "Stocks scanned"),
        (len(matches), "Matches"),
        (longs, "Long"),
        (shorts, "Short"),
        (count("FAIL"), "No match"),
        (count("INCOMPLETE"), "Incomplete"),
        (count("STALE"), "Stale"),
        (count("NO_DATA"), "No data"),
        (count("ERROR"), "Errors"),
        (f"{elapsed:.1f}s", "Scan time"),
    ]

    stats_html = "".join(f'<div class="stat"><b>{value}</b>{label}</div>' for value, label in stats)

    document = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>NSE Momentum Scanner</title>
<style>{CSS}</style>
</head>
<body>
<div class="container">

<h1>NSE Momentum Scanner</h1>

<div class="subtitle">
Generated: {esc(scan_time)}<br>
Universe: {esc(universe_source)}<br>
Yahoo Finance 5-minute data<br>
Previous day: {esc(fmt_day(previous_day))}<br>
Entry: {esc(fmt_day(entry_day))} at the 09:15 open &nbsp;|&nbsp; Exit: {esc(EXIT_TIME_LABEL)}
</div>

{warning_html}

<div class="stats">{stats_html}</div>

<div class="match-box">
<h2>Matches</h2>
<div class="matches">{match_html}</div>
</div>

<div class="table-wrap">
<table>
<thead>
<tr>
<th>Symbol</th>
<th>Previous day</th>
<th>Direction</th>
<th>Cond 1<br><small>15:20 volume &gt; 15:25 volume</small></th>
<th>Cond 2<br><small>09:15 trend = 15:20 trend</small></th>
<th>Result</th>
<th>Data</th>
</tr>
</thead>
<tbody>
{table_rows}
</tbody>
</table>
</div>

<div class="footer">
<b>STRATEGY (5-minute candles)</b><br>
Everything is read on the previous day, the latest completed session. The last
candle of a session is 15:25, the last second candle is 15:20 and the morning
candle is 09:15.<br>
1. The 15:20 candle's volume is greater than the 15:25 candle's volume.<br>
2. The 09:15 candle's trend is the same as the 15:20 candle's trend.<br>
Direction follows that trend: up is LONG, down is SHORT.<br>
<b>Entry:</b> the 09:15 open on entry day. <b>Exit:</b> {esc(EXIT_TIME_LABEL)}.<br><br>
<b>Data notes:</b> Candles come straight from Yahoo's 5-minute feed. A candle with
no trades is missing from Yahoo's data and is read as having no trend, so it can
never satisfy the trend condition. The one case that could create a false signal is
a missing 15:25 candle, because its volume then reads as zero; those matches are
tagged "verify" and are worth checking on TradingView. INCOMPLETE means no completed
session came back. STALE means the previous day differs from most other symbols.
</div>

</div>
</body>
</html>
"""

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
    print(f"Previous day: {reference_date}")
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
    error_messages = list(
        dict.fromkeys(r.get("error", "") for r in results if r.get("status") == "ERROR")
    )[:5]

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
