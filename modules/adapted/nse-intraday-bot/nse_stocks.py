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
Fetches the live NSE stock list dynamically.
No hardcoding — pulls Nifty 500 F&O list from NSE every day.
Falls back to Nifty 50 if NSE is unreachable.
"""
import contextlib
import json
import os
from datetime import date

import requests

CACHE_FILE = "nse_stock_cache.json"

NIFTY50_FALLBACK = [
    "RELIANCE",
    "TCS",
    "INFY",
    "HDFCBANK",
    "ICICIBANK",
    "SBIN",
    "BHARTIARTL",
    "LT",
    "KOTAKBANK",
    "AXISBANK",
    "BAJFINANCE",
    "WIPRO",
    "HCLTECH",
    "ASIANPAINT",
    "MARUTI",
    "TITAN",
    "ULTRACEMCO",
    "TECHM",
    "SUNPHARMA",
    "DRREDDY",
    "CIPLA",
    "DIVISLAB",
    "NESTLEIND",
    "HINDUNILVR",
    "ITC",
    "ONGC",
    "COALINDIA",
    "NTPC",
    "POWERGRID",
    "BPCL",
    "IOC",
    "BAJAJFINSV",
    "M&M",
    "EICHERMOT",
    "HEROMOTOCO",
    "JSWSTEEL",
    "TATASTEEL",
    "HINDALCO",
    "GRASIM",
    "ADANIENT",
    "APOLLOHOSP",
    "DMART",
    "TATACONSUM",
    "HDFCLIFE",
    "SBILIFE",
    "INDUSINDBK",
    "VEDL",
    "WIPRO",
    "PIDILITIND",
    "BRITANNIA",
]


def _fetch_nse_fo_list() -> list:
    """Fetch all F&O stocks from NSE (most liquid = best intraday)."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Referer": "https://www.nseindia.com/",
        "Connection": "keep-alive",
    }
    session = requests.Session()
    session.headers.update(headers)

    # Warm up the session with a page visit first
    with contextlib.suppress(Exception):
        session.get("https://www.nseindia.com/", timeout=8)

    # Fetch F&O stocks list
    url = "https://www.nseindia.com/api/equity-stockIndices?index=NIFTY%20500"
    try:
        r = session.get(url, timeout=10)
        data = r.json()
        stocks = [item["symbol"] for item in data.get("data", [])[1:]]
        if len(stocks) > 50:
            print(f"[NSE] Fetched {len(stocks)} stocks from Nifty 500")
            return stocks
    except Exception as e:
        print(f"[NSE] Nifty 500 fetch failed: {e}")

    # Fallback: Nifty 200
    url2 = "https://www.nseindia.com/api/equity-stockIndices?index=NIFTY%20200"
    try:
        r = session.get(url2, timeout=10)
        data = r.json()
        stocks = [item["symbol"] for item in data.get("data", [])[1:]]
        if len(stocks) > 50:
            print(f"[NSE] Fetched {len(stocks)} stocks from Nifty 200")
            return stocks
    except Exception as e:
        print(f"[NSE] Nifty 200 fetch failed: {e}")

    return []


def _fetch_nse_csv() -> list:
    """Fallback: NSE F&O lot size CSV (publicly available)."""
    url = "https://archives.nseindia.com/content/fo/fo_mktlots.csv"
    try:
        r = requests.get(url, timeout=10)
        lines = r.text.strip().split("\n")
        stocks = []
        for line in lines[1:]:
            parts = line.split(",")
            if len(parts) >= 2:
                sym = parts[1].strip().upper()
                if sym and sym != "SYMBOL" and not sym.startswith("NIFTY"):
                    stocks.append(sym)
        if len(stocks) > 50:
            print(f"[NSE] Fetched {len(stocks)} F&O stocks from CSV")
            return stocks
    except Exception as e:
        print(f"[NSE] CSV fetch failed: {e}")
    return []


def get_nse_stocks(force_refresh=False) -> list:
    """
    Returns live NSE stock list.
    Caches for the trading day. Auto-refreshes next day.
    """
    today_str = str(date.today())

    # Return from cache if same day
    if not force_refresh and os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, encoding="utf-8") as f:
                cache = json.load(f)
            if cache.get("date") == today_str and len(cache.get("stocks", [])) > 50:
                print(f"[NSE] Using cached list: {len(cache['stocks'])} stocks")
                return cache["stocks"]
        except Exception as e:
            print(f"[NSE] Cache read failed: {e}")

    print("[NSE] Fetching fresh stock list from NSE...")

    stocks = _fetch_nse_fo_list()
    if len(stocks) < 50:
        stocks = _fetch_nse_csv()
    if len(stocks) < 50:
        print("[NSE] All fetches failed, using Nifty 50 fallback")
        stocks = NIFTY50_FALLBACK

    # Save cache
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump({"date": today_str, "stocks": stocks}, f)
    except Exception as e:
        print(f"[NSE] Cache write failed: {e}")

    return stocks


if __name__ == "__main__":
    stocks = get_nse_stocks(force_refresh=True)
    print(f"\nTotal stocks fetched: {len(stocks)}")
    print("Sample:", stocks[:10])
