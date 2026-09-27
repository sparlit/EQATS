from __future__ import annotations

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
NSE F&O (derivatives-eligible) universe.

Source: https://www.nseindia.com/api/underlying-information
        -> data.UnderlyingList[].symbol

The NSE API rejects bare requests: it needs a browser-like User-Agent plus
cookies obtained by first hitting the homepage. This module handles that,
caches the list to disk (it only changes when NSE revises F&O eligibility,
roughly twice a year), and falls back to a bundled snapshot if the network
or NSE is unavailable — so the dashboard never dies because NSE is down.

Why restrict to F&O names for this strategy:
  * They are the most liquid stocks on NSE -> minimal slippage, which matters
    because slippage is what kills momentum edges in live trading.
  * They can be hedged or exited via options/futures if a position goes wrong.
  * NSE's F&O eligibility rules themselves screen for market cap, median
    quarter-sigma order size and market-wide position limits, so the list is
    a decent liquidity filter maintained by the exchange for free.
"""


import datetime as dt
import json
import os

import requests

CACHE_PATH = os.path.join("cache", "fno_universe.json")
CACHE_MAX_AGE_DAYS = 7

NSE_HOME = "https://www.nseindia.com"
NSE_API = "https://www.nseindia.com/api/underlying-information"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/market-data/equity-derivatives-watch",
}

# Bundled snapshot (fetched 2026-07-15, 210 symbols). Used only if the live
# API is unreachable. Refresh with: python fno_universe.py --refresh
FALLBACK_FNO = [
    "360ONE",
    "ABB",
    "APLAPOLLO",
    "AUBANK",
    "ADANIENSOL",
    "ADANIENT",
    "ADANIGREEN",
    "ADANIPORTS",
    "ADANIPOWER",
    "ABCAPITAL",
    "ALKEM",
    "AMBER",
    "AMBUJACEM",
    "ANGELONE",
    "APOLLOHOSP",
    "ASHOKLEY",
    "ASIANPAINT",
    "ASTRAL",
    "AUROPHARMA",
    "DMART",
    "AXISBANK",
    "BSE",
    "BAJAJ-AUTO",
    "BAJFINANCE",
    "BAJAJFINSV",
    "BAJAJHLDNG",
    "BANDHANBNK",
    "BANKBARODA",
    "BANKINDIA",
    "BDL",
    "BEL",
    "BHARATFORG",
    "BHEL",
    "BPCL",
    "BHARTIARTL",
    "BIOCON",
    "BLUESTARCO",
    "BOSCHLTD",
    "BRITANNIA",
    "CGPOWER",
    "CANBK",
    "CDSL",
    "CHOLAFIN",
    "CIPLA",
    "COALINDIA",
    "COCHINSHIP",
    "COFORGE",
    "COLPAL",
    "CAMS",
    "CONCOR",
    "CROMPTON",
    "CUMMINSIND",
    "DLF",
    "DABUR",
    "DALBHARAT",
    "DELHIVERY",
    "DIVISLAB",
    "DIXON",
    "DRREDDY",
    "ETERNAL",
    "EICHERMOT",
    "EXIDEIND",
    "FORCEMOT",
    "NYKAA",
    "FORTIS",
    "GAIL",
    "GVT&D",
    "GMRAIRPORT",
    "GLENMARK",
    "GODFRYPHLP",
    "GODREJCP",
    "GODREJPROP",
    "GRASIM",
    "HCLTECH",
    "HDFCAMC",
    "HDFCBANK",
    "HDFCLIFE",
    "HAVELLS",
    "HEROMOTOCO",
    "HINDALCO",
    "HAL",
    "HINDPETRO",
    "HINDUNILVR",
    "HINDZINC",
    "POWERINDIA",
    "HYUNDAI",
    "ICICIBANK",
    "ICICIGI",
    "ICICIPRULI",
    "IDFCFIRSTB",
    "ITC",
    "INDIANB",
    "IEX",
    "IOC",
    "IRFC",
    "IREDA",
    "INDUSTOWER",
    "INDUSINDBK",
    "NAUKRI",
    "INFY",
    "INOXWIND",
    "INDIGO",
    "JINDALSTEL",
    "JSWENERGY",
    "JSWSTEEL",
    "JIOFIN",
    "JUBLFOOD",
    "KEI",
    "KPITTECH",
    "KALYANKJIL",
    "KAYNES",
    "KFINTECH",
    "KOTAKBANK",
    "LTF",
    "LICHSGFIN",
    "LTM",
    "LT",
    "LAURUSLABS",
    "LICI",
    "LODHA",
    "LUPIN",
    "M&M",
    "MANAPPURAM",
    "MANKIND",
    "MARICO",
    "MARUTI",
    "MFSL",
    "MAXHEALTH",
    "MAZDOCK",
    "MOTILALOFS",
    "MPHASIS",
    "MCX",
    "MUTHOOTFIN",
    "NBCC",
    "NHPC",
    "NMDC",
    "NTPC",
    "NATIONALUM",
    "NESTLEIND",
    "NAM-INDIA",
    "NUVAMA",
    "OBEROIRLTY",
    "ONGC",
    "OIL",
    "PAYTM",
    "OFSS",
    "POLICYBZR",
    "PGEL",
    "PIIND",
    "PNBHOUSING",
    "PAGEIND",
    "PATANJALI",
    "PERSISTENT",
    "PETRONET",
    "PIDILITIND",
    "POLYCAB",
    "PFC",
    "POWERGRID",
    "PREMIERENE",
    "PRESTIGE",
    "PNB",
    "RBLBANK",
    "RECLTD",
    "RADICO",
    "RVNL",
    "RELIANCE",
    "SBICARD",
    "SBILIFE",
    "SHREECEM",
    "SRF",
    "MOTHERSON",
    "SHRIRAMFIN",
    "SIEMENS",
    "SOLARINDS",
    "SONACOMS",
    "SBIN",
    "SAIL",
    "SUNPHARMA",
    "SUPREMEIND",
    "SUZLON",
    "SWIGGY",
    "TATACONSUM",
    "TVSMOTOR",
    "TCS",
    "TATAELXSI",
    "TMPV",
    "TATAPOWER",
    "TATASTEEL",
    "TECHM",
    "FEDERALBNK",
    "INDHOTEL",
    "PHOENIXLTD",
    "TITAN",
    "TORNTPHARM",
    "TRENT",
    "TIINDIA",
    "UNOMINDA",
    "UPL",
    "ULTRACEMCO",
    "UNIONBANK",
    "UNITDSPR",
    "VBL",
    "VEDL",
    "VMM",
    "IDEA",
    "VOLTAS",
    "WAAREEENER",
    "WIPRO",
    "YESBANK",
    "ZYDUSLIFE",
]


def fetch_fno_symbols_live(timeout: int = 15) -> list[str]:
    """Hit the NSE API with a warmed-up session. Raises on failure."""
    s = requests.Session()
    s.headers.update(HEADERS)
    s.get(NSE_HOME, timeout=timeout)  # sets cookies
    r = s.get(NSE_API, timeout=timeout)
    r.raise_for_status()
    payload = r.json()
    underlying = payload["data"]["UnderlyingList"]
    return sorted({row["symbol"].strip() for row in underlying if row.get("symbol")})


def _cache_age_days() -> float:
    if not os.path.exists(CACHE_PATH):
        return 1e9
    mtime = dt.datetime.fromtimestamp(os.path.getmtime(CACHE_PATH))
    return (dt.datetime.now() - mtime).total_seconds() / 86400


def get_fno_universe(force_refresh: bool = False, verbose: bool = True) -> list[str]:
    """F&O symbols, preferring cache, then live API, then bundled fallback."""
    if not force_refresh and _cache_age_days() < CACHE_MAX_AGE_DAYS:
        with open(CACHE_PATH) as f:
            data = json.load(f)
        return data["symbols"]

    try:
        symbols = fetch_fno_symbols_live()
        os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
        with open(CACHE_PATH, "w") as f:
            json.dump({"fetched": dt.datetime.now().isoformat(), "symbols": symbols}, f, indent=1)
        if verbose:
            print(f"[fno] fetched {len(symbols)} F&O symbols from NSE")
        return symbols
    except Exception as e:
        if verbose:
            print(f"[fno] live fetch failed ({e})")
        if os.path.exists(CACHE_PATH):
            with open(CACHE_PATH) as f:
                symbols = json.load(f)["symbols"]
            if verbose:
                print(f"[fno] using stale cache ({len(symbols)} symbols, {_cache_age_days():.0f}d old)")
            return symbols
        if verbose:
            print(f"[fno] using bundled fallback ({len(FALLBACK_FNO)} symbols)")
        return list(FALLBACK_FNO)


def tradable_on_kite(symbols: list[str]) -> list[str]:
    """Drop any F&O symbol that has no NSE equity instrument on Kite
    (index underlyings, renamed/merged tickers)."""
    try:
        import kite_client

        valid = kite_client.instrument_map()
        return [s for s in symbols if s in valid]
    except Exception:
        return symbols


if __name__ == "__main__":
    import sys

    syms = get_fno_universe(force_refresh="--refresh" in sys.argv)
    print(f"{len(syms)} F&O underlyings")
    print(", ".join(syms))
