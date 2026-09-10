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
universe.py
Fetches NSE index constituent lists (Nifty 100 / 200 / 500) from NSE's public
archives (free, no auth).

Source verified live: https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv
NOTE: NSE returns 503 without a browser-like User-Agent header. This is not an auth
wall, just basic bot-filtering — the headers below are sufficient and require no login.

The Nifty 100 / 200 / 500 lists are ranked by free-float market cap, so requesting
the top-N-by-market-cap universe is just "fetch Nifty 100" (or 200, or 500).
This avoids the cost of calling yfinance's ticker.info for market caps on all 500
names just to rank them.

Confidence: high (all three endpoints tested). NSE has changed archive paths
before without notice; if these URLs start 404ing, check
https://www.nseindia.com/all-reports for the current path.
"""

import io

import pandas as pd
import requests

NIFTY_INDEX_URLS = {
    100: (
        "https://nsearchives.nseindia.com/content/indices/ind_nifty100list.csv",
        "https://www.niftyindices.com/IndexConstituent/ind_nifty100list.csv",
    ),
    200: (
        "https://nsearchives.nseindia.com/content/indices/ind_nifty200list.csv",
        "https://www.niftyindices.com/IndexConstituent/ind_nifty200list.csv",
    ),
    500: (
        "https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv",
        "https://www.niftyindices.com/IndexConstituent/ind_nifty500list.csv",
    ),
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "text/csv,*/*",
    "Referer": "https://www.nseindia.com/",
}


def _fetch_csv(urls: tuple, timeout: int) -> pd.DataFrame:
    last_err = None
    for url in urls:
        try:
            resp = requests.get(url, headers=HEADERS, timeout=timeout)
            resp.raise_for_status()
            df = pd.read_csv(io.StringIO(resp.text))
            df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]
            df = df.rename(
                columns={
                    "company_name": "company_name",
                    "industry": "industry",
                    "symbol": "symbol",
                    "series": "series",
                    "isin_code": "isin",
                }
            )
            df["yf_ticker"] = df["symbol"].astype(str).str.strip() + ".NS"
            return df[["company_name", "industry", "symbol", "series", "isin", "yf_ticker"]]
        except Exception as e:
            last_err = e
            continue
    msg = f"Failed to fetch NSE index list from {urls}. Last error: {last_err}"
    raise RuntimeError(msg)


def fetch_nifty500(timeout: int = 15) -> pd.DataFrame:
    """Fetch the Nifty 500 constituents (top 500 by free-float market cap)."""
    return _fetch_csv(NIFTY_INDEX_URLS[500], timeout)


def fetch_nifty200(timeout: int = 15) -> pd.DataFrame:
    """Fetch the Nifty 200 constituents (top 200 by free-float market cap)."""
    return _fetch_csv(NIFTY_INDEX_URLS[200], timeout)


def fetch_nifty100(timeout: int = 15) -> pd.DataFrame:
    """Fetch the Nifty 100 constituents (top 100 by free-float market cap)."""
    return _fetch_csv(NIFTY_INDEX_URLS[100], timeout)


def fetch_universe(top_n: int = 500, timeout: int = 15) -> pd.DataFrame:
    """
    Fetch an NSE index constituent list for the requested top-N-by-market-cap tier.

    Valid `top_n` values: 100, 200, 500. Anything else falls back to 500.

    Returns a DataFrame with columns: company_name, industry, symbol, series, isin, yf_ticker
    """
    if top_n not in NIFTY_INDEX_URLS:
        top_n = 500
    return _fetch_csv(NIFTY_INDEX_URLS[top_n], timeout)


if __name__ == "__main__":
    for n in (100, 200, 500):
        u = fetch_universe(top_n=n)
        print(f"Nifty {n}: {len(u)} constituents (first: {u['symbol'].iloc[0]})")
