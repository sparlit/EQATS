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
# NSE DAILY SCANNER — FAST + RELIABLE
# =============================================================================
#
# FINAL STRATEGY CONDITIONS
#
# 1) 3-MIN:
#       15:24 and 15:27 must be OPPOSITE trends
#       15:24 volume > 15:27 volume
#
# 2) 3-MIN MORNING:
#       09:15 and 09:18 must BOTH be OPPOSITE
#       to 15:24 direction
#
# 3) 1-MIN:
#       15:28 and 15:29 must be OPPOSITE trends
#       15:28 volume > 15:29 volume
#
# 4) 1-MIN / 3-MIN CONFIRMATION:
#       1-min 15:28 must MATCH 3-min 15:24 direction
#
# FINAL DIRECTION:
#       3-min 15:24
#
# ENTRY:
#       Next trading day at 09:15 open
#
# EXIT:
#       15:27
#
# =============================================================================
#
# INSTALL:
#
# pip install yfinance pandas requests nselib
#
# =============================================================================


import random
import sys
import time
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import pandas as pd

warnings.filterwarnings("ignore")


# =============================================================================
# IMPORT YFINANCE
# =============================================================================

try:
    import yfinance as yf

except ImportError:
    print()
    print("yfinance is missing.")
    print()
    print("Install with:")
    print("pip install yfinance pandas requests nselib")
    print()

    sys.exit(1)


# =============================================================================
# CONFIGURATION
# =============================================================================

# -----------------------------------------------------------------------------
# SPEED
# -----------------------------------------------------------------------------

MAX_WORKERS = 12

# Yahoo request retries
MAX_RETRIES = 4

# First request
INITIAL_PERIOD = "3d"

# Fallback request
FIVE_DAY_FALLBACK = "7d"

# Yahoo timeout
REQUEST_TIMEOUT = 20

# Retry delay
MIN_RETRY_SLEEP = 1.0
MAX_RETRY_SLEEP = 3.0


# =============================================================================
# NSE UNIVERSE
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


STOCK_UNIVERSE = list(dict.fromkeys(NIFTY_50 + NIFTY_NEXT_150))


# =============================================================================
# TRY LIVE NIFTY 500
# =============================================================================

try:
    from nselib import indices

    print("Attempting to load live Nifty 500 universe...")

    df = indices.constituent_stock_list(index_category="BroadMarketIndices", index_name="Nifty 500")

    if df is not None and not df.empty and "Symbol" in df.columns:
        fetched = df["Symbol"].dropna().astype(str).str.strip().str.upper().tolist()

        fetched = list(dict.fromkeys(fetched))

        if len(fetched) > len(STOCK_UNIVERSE):
            STOCK_UNIVERSE = fetched

            print(f"Loaded {len(STOCK_UNIVERSE)} symbols from Nifty 500.")


except Exception as e:
    print(f"Nifty 500 loading failed: {e}")

    print(f"Using existing universe: {len(STOCK_UNIVERSE)} stocks.")


# =============================================================================
# TRY NSE OFFICIAL EQUITY LIST
# =============================================================================

try:
    from io import StringIO

    import requests

    print("Attempting to load NSE official equity list...")

    headers = {
        "User-Agent": "Mozilla/5.0 "
        "(Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/131.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    session = requests.Session()

    session.headers.update(headers)

    session.get("https://www.nseindia.com", timeout=15)

    response = session.get("https://nsearchives.nseindia.com/content/equities/sec_list.csv", timeout=20)

    response.raise_for_status()

    full_df = pd.read_csv(StringIO(response.text))

    symbol_col = next((c for c in full_df.columns if "symbol" in c.lower()), None)

    series_col = next((c for c in full_df.columns if "series" in c.lower()), None)

    if symbol_col is not None:
        if series_col is not None:
            full_df = full_df[full_df[series_col].astype(str).str.strip().str.upper() == "EQ"]

        symbols = full_df[symbol_col].dropna().astype(str).str.strip().str.upper().tolist()

        banned = (
            "ETF",
            "IETF",
            "BEES",
            "LIQUID",
            "GILT",
            "MUTUAL",
            "FUND",
            "INDEX",
        )

        symbols = [s for s in symbols if not any(word in s for word in banned)]

        symbols = list(dict.fromkeys(symbols))

        if len(symbols) > len(STOCK_UNIVERSE):
            STOCK_UNIVERSE = symbols

            print(f"Loaded {len(STOCK_UNIVERSE)} stocks from NSE official list.")


except Exception as e:
    print(f"NSE official list unavailable: {e}")


print()
print("=" * 70)
print(f"FINAL STOCK UNIVERSE: {len(STOCK_UNIVERSE)}")
print("=" * 70)
print()


# =============================================================================
# REQUIRED 1-MINUTE CANDLES
# =============================================================================
#
# 09:15, 09:16, 09:17
# 09:18, 09:19, 09:20
#
# 15:24, 15:25, 15:26
# 15:27, 15:28, 15:29
#
# 1-minute 15:28 and 15:29 are required.
#
# =============================================================================

NEEDED_HM = {
    915,
    916,
    917,
    918,
    919,
    920,
    1524,
    1525,
    1526,
    1527,
    1528,
    1529,
}


# =============================================================================
# DIRECTION
# =============================================================================


def candle_direction(open_price, close_price):

    if close_price > open_price:
        return 1

    if close_price < open_price:
        return -1

    return 0


# =============================================================================
# CLEAN YAHOO DATA
# =============================================================================


def clean_yahoo_data(df):

    if df is None or df.empty:
        return None

    # ---------------------------------------------------------
    # Flatten MultiIndex
    # ---------------------------------------------------------

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]

    df = df.reset_index()

    # ---------------------------------------------------------
    # Find timestamp
    # ---------------------------------------------------------

    timestamp_col = None

    for candidate in (
        "Datetime",
        "Date",
        "datetime",
        "date",
    ):
        if candidate in df.columns:
            timestamp_col = candidate
            break

    if timestamp_col is None:
        timestamp_col = df.columns[0]

    ts = pd.to_datetime(df[timestamp_col], errors="coerce")

    valid_ts = ts.notna()

    if not valid_ts.any():
        return None

    df = df.loc[valid_ts].copy()

    ts = ts.loc[valid_ts]

    # ---------------------------------------------------------
    # India timezone
    # ---------------------------------------------------------

    ts = ts.dt.tz_convert("Asia/Kolkata") if ts.dt.tz is not None else ts.dt.tz_localize("Asia/Kolkata")

    # ---------------------------------------------------------
    # Required columns
    # ---------------------------------------------------------

    required = [
        "Open",
        "Close",
        "Volume",
    ]

    if not all(c in df.columns for c in required):
        return None

    # ---------------------------------------------------------
    # Compact dataframe
    # ---------------------------------------------------------

    out = pd.DataFrame(
        {
            "date": ts.dt.strftime("%Y-%m-%d"),
            "hm": (ts.dt.hour * 100 + ts.dt.minute),
            "open": pd.to_numeric(df["Open"], errors="coerce").values,
            "close": pd.to_numeric(df["Close"], errors="coerce").values,
            "volume": pd.to_numeric(df["Volume"], errors="coerce").values,
        }
    )

    # ---------------------------------------------------------
    # NSE regular session
    # ---------------------------------------------------------

    out = out[out["hm"].between(915, 1529)]

    # ---------------------------------------------------------
    # Remove invalid
    # ---------------------------------------------------------

    out = out.dropna(
        subset=[
            "open",
            "close",
            "volume",
        ]
    )

    # ---------------------------------------------------------
    # Duplicate protection
    # ---------------------------------------------------------

    return out.drop_duplicates(
        subset=[
            "date",
            "hm",
        ],
        keep="last",
    )


# =============================================================================
# CHECK COMPLETE DAYS
# =============================================================================


def find_complete_days(rows):

    if rows is None or rows.empty:
        return []

    by_date = rows.groupby("date")

    complete_days = []

    for date, group in by_date:
        available = set(group["hm"].astype(int))

        if NEEDED_HM.issubset(available):
            complete_days.append(date)

    return sorted(complete_days)


# =============================================================================
# DOWNLOAD SYMBOL
# =============================================================================


def download_symbol(symbol, period):

    ticker = f"{symbol}.NS"

    for attempt in range(MAX_RETRIES):
        try:
            df = yf.download(
                ticker,
                period=period,
                interval="1m",
                progress=False,
                auto_adjust=False,
                actions=False,
                threads=False,
                timeout=REQUEST_TIMEOUT,
            )

            if df is not None and not df.empty:
                cleaned = clean_yahoo_data(df)

                if cleaned is not None and not cleaned.empty:
                    return cleaned

        except Exception:
            pass

        # -----------------------------------------------------
        # Retry backoff
        # -----------------------------------------------------

        if attempt < MAX_RETRIES - 1:
            sleep_time = min(
                MAX_RETRY_SLEEP,
                MIN_RETRY_SLEEP * (2**attempt),
            )

            sleep_time += random.uniform(0, 0.75)

            time.sleep(sleep_time)

    return None


# =============================================================================
# FETCH WITH FALLBACK
# =============================================================================


def fetch_symbol_rows(symbol):

    # ---------------------------------------------------------
    # First request
    # ---------------------------------------------------------

    rows = download_symbol(symbol, INITIAL_PERIOD)

    if rows is not None:
        complete_days = find_complete_days(rows)

        if complete_days:
            return (rows, "OK")

    # ---------------------------------------------------------
    # Fallback
    # ---------------------------------------------------------

    rows = download_symbol(symbol, FIVE_DAY_FALLBACK)

    if rows is not None:
        complete_days = find_complete_days(rows)

        if complete_days:
            return (rows, "FALLBACK")

        return (rows, "INCOMPLETE")

    return (None, "NO_DATA")


# =============================================================================
# EVALUATE STRATEGY
# =============================================================================


def evaluate_rows(rows):

    if rows is None or rows.empty:
        return {"status": "NO_DATA"}

    # =========================================================
    # GROUP BY DATE
    # =========================================================

    by_date = {}

    for row in rows.itertuples(index=False):
        date = row.date
        hm = int(row.hm)

        if date not in by_date:
            by_date[date] = {}

        by_date[date][hm] = {
            "open": row.open,
            "close": row.close,
            "volume": row.volume,
        }

    # =========================================================
    # FIND COMPLETE DAYS
    # =========================================================

    complete_dates = []

    for date, minute_map in by_date.items():
        if NEEDED_HM.issubset(minute_map.keys()):
            complete_dates.append(date)

    if not complete_dates:
        return {"status": "INCOMPLETE"}

    # =========================================================
    # LATEST COMPLETE DAY
    # =========================================================

    signal_date = max(complete_dates)

    m = by_date[signal_date]

    # =========================================================
    # 3-MINUTE AGGREGATION
    # =========================================================

    def aggregate_3m(minute_times):

        candles = [m[x] for x in minute_times]

        return {
            "open": float(candles[0]["open"]),
            "close": float(candles[-1]["close"]),
            "volume": sum(float(x["volume"]) for x in candles),
        }

    # =========================================================
    # 3-MIN 15:24
    # =========================================================

    candle_1524 = aggregate_3m(
        [
            1524,
            1525,
            1526,
        ]
    )

    # =========================================================
    # 3-MIN 15:27
    # =========================================================

    candle_1527 = aggregate_3m(
        [
            1527,
            1528,
            1529,
        ]
    )

    # =========================================================
    # 3-MIN 09:15
    # =========================================================

    candle_915 = aggregate_3m(
        [
            915,
            916,
            917,
        ]
    )

    # =========================================================
    # 3-MIN 09:18
    # =========================================================

    candle_918 = aggregate_3m(
        [
            918,
            919,
            920,
        ]
    )

    # =========================================================
    # DIRECTIONS
    # =========================================================

    dir_1524 = candle_direction(candle_1524["open"], candle_1524["close"])

    dir_1527 = candle_direction(candle_1527["open"], candle_1527["close"])

    dir_915_3m = candle_direction(candle_915["open"], candle_915["close"])

    dir_918_3m = candle_direction(candle_918["open"], candle_918["close"])

    # =========================================================
    # 1-MIN DIRECTIONS
    # =========================================================

    dir_1528_1m = candle_direction(m[1528]["open"], m[1528]["close"])

    dir_1529_1m = candle_direction(m[1529]["open"], m[1529]["close"])

    # =========================================================
    # VOLUMES
    # =========================================================

    vol_1524 = float(candle_1524["volume"])

    vol_1527 = float(candle_1527["volume"])

    vol_1528 = float(m[1528]["volume"])

    vol_1529 = float(m[1529]["volume"])

    # =========================================================
    # CONDITION 1
    #
    # 3-MIN 15:24 AND 15:27
    # OPPOSITE
    #
    # 15:24 VOLUME > 15:27
    # =========================================================

    cond1 = dir_1524 != 0 and dir_1527 not in (0, dir_1524) and vol_1524 > vol_1527

    # =========================================================
    # CONDITION 2
    #
    # 3-MIN 09:15 AND 09:18
    #
    # BOTH MUST BE OPPOSITE
    # TO 15:24
    # =========================================================

    cond2 = (
        dir_1524 != 0 and dir_915_3m != 0 and dir_918_3m != 0 and dir_915_3m == -dir_1524 and dir_918_3m == -dir_1524
    )

    # =========================================================
    # CONDITION 3
    #
    # 1-MIN 15:28 AND 15:29
    # OPPOSITE
    #
    # 15:28 VOLUME > 15:29
    # =========================================================

    cond3 = dir_1528_1m != 0 and dir_1529_1m not in (0, dir_1528_1m) and vol_1528 > vol_1529

    # =========================================================
    # CONDITION 4
    #
    # 1-MIN 15:28
    #
    # MUST MATCH 3-MIN 15:24
    # =========================================================

    cond4 = dir_1528_1m != 0 and dir_1524 != 0 and dir_1528_1m == dir_1524

    # =========================================================
    # FINAL
    # =========================================================

    passed = cond1 and cond2 and cond3 and cond4

    # =========================================================
    # FINAL DIRECTION
    #
    # Direction = 3-MIN 15:24
    # =========================================================

    if dir_1524 == 1:
        direction = "LONG"

    elif dir_1524 == -1:
        direction = "SHORT"

    else:
        direction = None

    # =========================================================
    # RETURN
    # =========================================================

    return {
        "status": "PASS" if passed else "FAIL",
        "date": signal_date,
        "direction": direction if passed else None,
        "cond1": cond1,
        "cond2": cond2,
        "cond3": cond3,
        "cond4": cond4,
        "details": {
            "15:24_vol": f"{vol_1524:,.0f}",
            "15:27_vol": f"{vol_1527:,.0f}",
            "15:28_vol": f"{vol_1528:,.0f}",
            "15:29_vol": f"{vol_1529:,.0f}",
            "15:24_trend": trend_text(dir_1524),
            "15:27_trend": trend_text(dir_1527),
            "09:15_trend": trend_text(dir_915_3m),
            "09:18_trend": trend_text(dir_918_3m),
            "15:28_trend": trend_text(dir_1528_1m),
            "15:29_trend": trend_text(dir_1529_1m),
        },
    }


# =============================================================================
# TREND TEXT
# =============================================================================


def trend_text(direction):

    if direction == 1:
        return "GREEN"

    if direction == -1:
        return "RED"

    return "DOJI"


# =============================================================================
# SCAN ONE STOCK
# =============================================================================


def scan_one_symbol(symbol):

    try:
        rows, data_status = fetch_symbol_rows(symbol)

        if rows is None:
            return {
                "symbol": symbol,
                "status": "NO_DATA",
                "data_status": data_status,
            }

        result = evaluate_rows(rows)

        result["symbol"] = symbol

        result["data_status"] = data_status

        return result

    except Exception as e:
        return {
            "symbol": symbol,
            "status": "ERROR",
            "error": str(e),
        }


# =============================================================================
# FAST PARALLEL SCAN
# =============================================================================


def scan_all_symbols(symbols):

    total = len(symbols)

    results = []

    completed = 0

    print()

    print(f"Scanning {total} stocks with {MAX_WORKERS} workers...")

    print()

    start = time.time()

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
                    "error": str(e),
                }

            results.append(result)

            completed += 1

            status = result.get("status")

            if status == "PASS":
                print(
                    f"[{completed}/{total}] {symbol:<15} *** MATCH *** {result.get('direction')} ({result.get('date')})"
                )

            elif status == "ERROR":
                print(f"[{completed}/{total}] {symbol:<15} ERROR")

            elif status == "NO_DATA":
                print(f"[{completed}/{total}] {symbol:<15} NO DATA")

            elif status == "INCOMPLETE":
                print(f"[{completed}/{total}] {symbol:<15} INCOMPLETE DATA")

            else:
                print(f"[{completed}/{total}] {symbol:<15} NO MATCH")

    elapsed = time.time() - start

    results.sort(key=lambda x: x.get("symbol", ""))

    return (results, elapsed)


# =============================================================================
# BADGE
# =============================================================================


def badge(value):

    if value is True:
        return '<span class="badge pass">PASS</span>'

    if value is False:
        return '<span class="badge fail">FAIL</span>'

    return "—"


# =============================================================================
# HTML REPORT
# =============================================================================


def generate_html_report(results, elapsed):

    matches = [r for r in results if r.get("status") == "PASS"]

    fails = [r for r in results if r.get("status") == "FAIL"]

    incomplete = [r for r in results if r.get("status") == "INCOMPLETE"]

    no_data = [r for r in results if r.get("status") == "NO_DATA"]

    errors = [r for r in results if r.get("status") == "ERROR"]

    # =========================================================
    # MATCHES
    # =========================================================

    if matches:
        match_html = "".join(
            f"""
            <div class="match">

                <span class="direction
                {"long" if r["direction"] == "LONG" else "short"}">

                    {r["direction"]}

                </span>

                <b>
                    {r["symbol"]}
                </b>

                <span class="date">

                    Signal day:
                    {r["date"]}

                </span>

            </div>
            """
            for r in matches
        )

    else:
        match_html = """

        <div class="none">
            No stocks matched today.
        </div>

        """

    # =========================================================
    # TABLE
    # =========================================================

    table_rows = ""

    for r in sorted(
        results,
        key=lambda x: (
            x.get("status") != "PASS",
            x.get("symbol", ""),
        ),
    ):
        status = r.get("status", "UNKNOWN")

        if status == "PASS":
            status_class = "pass"

        elif status == "FAIL":
            status_class = "fail"

        else:
            status_class = "skip"

        details = r.get("details", {})

        table_rows += f"""

        <tr>

            <td class="symbol">
                {r.get("symbol", "")}
            </td>

            <td>
                {r.get("date", "—")}
            </td>

            <td>
                {r.get("direction", "—") or "—"}
            </td>

            <td>

                {badge(r.get("cond1"))}

                <br>

                <small>

                    15:24:
                    {details.get("15:24_vol", "—")}

                    &gt;

                    15:27:
                    {details.get("15:27_vol", "—")}

                </small>

            </td>

            <td>

                {badge(r.get("cond2"))}

                <br>

                <small>

                    09:15:
                    {details.get("09:15_trend", "—")}

                    /

                    09:18:
                    {details.get("09:18_trend", "—")}

                </small>

            </td>

            <td>

                {badge(r.get("cond3"))}

                <br>

                <small>

                    15:28:
                    {details.get("15:28_vol", "—")}

                    &gt;

                    15:29:
                    {details.get("15:29_vol", "—")}

                </small>

            </td>

            <td>

                {badge(r.get("cond4"))}

                <br>

                <small>

                    1M 15:28:
                    {details.get("15:28_trend", "—")}

                    /

                    3M 15:24:
                    {details.get("15:24_trend", "—")}

                </small>

            </td>

            <td class="{status_class}">

                {status}

            </td>

            <td>

                {r.get("data_status", "—")}

            </td>

        </tr>

        """

    # =========================================================
    # SCAN TIME
    # =========================================================

    scan_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # =========================================================
    # HTML
    # =========================================================

    html = f"""

<!DOCTYPE html>

<html>

<head>

<meta charset="UTF-8">

<title>
NSE Scanner
</title>

<style>

body {{

    font-family:
        Arial,
        sans-serif;

    background:
        #f5f5f5;

    color:
        #222;

    margin:
        0;

    padding:
        25px;

}}

.container {{

    max-width:
        1400px;

    margin:
        auto;

}}

h1 {{

    margin-bottom:
        5px;

}}

.subtitle {{

    color:
        #777;

}}

.stats {{

    display:
        flex;

    flex-wrap:
        wrap;

    gap:
        10px;

    margin:
        20px 0;

}}

.stat {{

    background:
        white;

    padding:
        15px 20px;

    border-radius:
        8px;

    border:
        1px solid #ddd;

}}

.stat b {{

    font-size:
        22px;

    display:
        block;

}}

.match-box {{

    background:
        white;

    border:
        1px solid #ddd;

    border-radius:
        8px;

    padding:
        20px;

    margin-bottom:
        20px;

}}

.match {{

    padding:
        8px 0;

    border-bottom:
        1px solid #eee;

}}

.direction {{

    display:
        inline-block;

    padding:
        3px 7px;

    border-radius:
        4px;

    font-size:
        11px;

    font-weight:
        bold;

    margin-right:
        8px;

}}

.long {{

    background:
        #dff5e5;

    color:
        #08752f;

}}

.short {{

    background:
        #f8dddd;

    color:
        #a52222;

}}

.date {{

    color:
        #777;

    margin-left:
        8px;

}}

table {{

    width:
        100%;

    border-collapse:
        collapse;

    background:
        white;

    font-size:
        13px;

}}

th {{

    background:
        #ededed;

    padding:
        10px;

    text-align:
        left;

}}

td {{

    padding:
        9px 10px;

    border-top:
        1px solid #eee;

}}

.symbol {{

    font-weight:
        bold;

}}

small {{

    color:
        #777;

    font-size:
        10px;

}}

.badge {{

    display:
        inline-block;

    padding:
        2px 6px;

    border-radius:
        4px;

    font-size:
        10px;

    font-weight:
        bold;

}}

.badge.pass {{

    background:
        #dff5e5;

    color:
        #08752f;

}}

.badge.fail {{

    background:
        #f8dddd;

    color:
        #a52222;

}}

.pass {{

    color:
        #08752f;

    font-weight:
        bold;

}}

.fail {{

    color:
        #999;

}}

.skip {{

    color:
        #b07000;

}}

.none {{

    color:
        #777;

}}

.footer {{

    margin-top:
        25px;

    color:
        #777;

    font-size:
        12px;

}}

</style>

</head>


<body>

<div class="container">


<h1>
NSE Daily Scanner
</h1>


<div class="subtitle">

Generated:
{scan_time}

<br>

Yahoo Finance 1-minute data

</div>


<div class="stats">


<div class="stat">

<b>
{len(results)}
</b>

Stocks scanned

</div>


<div class="stat">

<b>
{len(matches)}
</b>

Matches

</div>


<div class="stat">

<b>
{len(fails)}
</b>

No match

</div>


<div class="stat">

<b>
{len(incomplete)}
</b>

Incomplete

</div>


<div class="stat">

<b>
{len(no_data)}
</b>

No data

</div>


<div class="stat">

<b>
{len(errors)}
</b>

Errors

</div>


<div class="stat">

<b>
{elapsed:.1f}s
</b>

Scan time

</div>


</div>


<div class="match-box">


<h2>
Matches
</h2>


{match_html}


</div>


<table>


<thead>

<tr>

<th>
Symbol
</th>

<th>
Signal Day
</th>

<th>
Direction
</th>

<th>
3M 15:24 / 15:27
</th>

<th>
3M Morning
</th>

<th>
1M 15:28 / 15:29
</th>

<th>
1M 15:28 = 3M 15:24
</th>

<th>
Result
</th>

<th>
Data
</th>

</tr>

</thead>


<tbody>

{table_rows}

</tbody>


</table>


<div class="footer">

<b>
Strategy:
</b>

3-min 15:24 and 15:27 opposite,
with 15:24 volume greater than 15:27.

<br>

3-min 09:15 and 09:18 are both
opposite to 15:24 direction.

<br>

1-min 15:28 and 15:29 opposite,
with 15:28 volume greater than 15:29.

<br>

1-min 15:28 matches
3-min 15:24 direction.

<br>

<b>
Entry:
</b>

Next trading day 09:15 open.

<br>

<b>
Exit:
</b>

15:27.

</div>


</div>

</body>

</html>

"""

    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html)


# =============================================================================
# MAIN
# =============================================================================


def main():

    print()

    print("=" * 70)

    print("NSE DAILY SCANNER")

    print("=" * 70)

    print()

    time.time()

    results, elapsed = scan_all_symbols(STOCK_UNIVERSE)

    matches = [r for r in results if r.get("status") == "PASS"]

    print()

    print("=" * 70)

    print("FINAL RESULTS")

    print("=" * 70)

    print()

    if matches:
        print(f"MATCHES FOUND: {len(matches)}")

        print()

        for r in matches:
            print(f"{r['symbol']:<15}{r['direction']:<8}Signal day: {r['date']}")

    else:
        print("NO MATCHES TODAY.")

    print()

    pass_count = sum(r.get("status") == "PASS" for r in results)

    fail_count = sum(r.get("status") == "FAIL" for r in results)

    incomplete_count = sum(r.get("status") == "INCOMPLETE" for r in results)

    no_data_count = sum(r.get("status") == "NO_DATA" for r in results)

    error_count = sum(r.get("status") == "ERROR" for r in results)

    print(f"PASS:       {pass_count}")

    print(f"FAIL:       {fail_count}")

    print(f"INCOMPLETE: {incomplete_count}")

    print(f"NO DATA:    {no_data_count}")

    print(f"ERROR:      {error_count}")

    print()

    print(f"Scan time:  {elapsed:.1f} seconds")

    print()

    print("=" * 70)

    generate_html_report(results, elapsed)

    print()

    print("HTML report written to:")

    print("index.html")


# =============================================================================
# RUN
# =============================================================================

if __name__ == "__main__":
    main()
