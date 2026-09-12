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
Refresh the bundled NSE main-board equity universe.

Run this from a machine that can reach NSE (an India IP works best); NSE blocks
most cloud IPs, which is exactly why the app ships a bundled snapshot instead of
fetching live. Commit the regenerated data/nse_equity_list.csv.

    python update_universe.py
"""

import contextlib
import io
import sys

import pandas as pd
import requests

EQUITY_L_URL = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"
OUT_PATH = "data/nse_equity_list.csv"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "text/csv,application/csv,*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
}


def fetch() -> pd.DataFrame:
    s = requests.Session()
    s.headers.update(HEADERS)
    # prime cookies from the main site first (NSE often requires this)
    with contextlib.suppress(Exception):
        s.get("https://www.nseindia.com/", timeout=15)
    r = s.get(EQUITY_L_URL, timeout=30)
    r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.text))
    df.columns = [c.strip() for c in df.columns]
    df["SERIES"] = df["SERIES"].astype(str).str.strip()
    # main-board tradable equity series
    df = df[df["SERIES"].isin(["EQ", "BE"])].copy()
    df["SYMBOL"] = df["SYMBOL"].astype(str).str.strip()
    cols = ["SYMBOL", "NAME OF COMPANY", "SERIES"]
    # DATE OF LISTING powers the listing-window filter (format like 08-JUL-1999)
    if "DATE OF LISTING" in df.columns:
        df["DATE OF LISTING"] = df["DATE OF LISTING"].astype(str).str.strip()
        cols.append("DATE OF LISTING")
    out = df[cols].drop_duplicates("SYMBOL")
    return out.reset_index(drop=True)


def main():
    try:
        df = fetch()
    except Exception as e:
        print(f"ERROR: could not fetch EQUITY_L.csv from NSE: {e}", file=sys.stderr)
        print("Tip: run this from an India IP; the app still works with the existing bundled list.", file=sys.stderr)
        sys.exit(1)
    df.to_csv(OUT_PATH, index=False)
    print(f"Wrote {len(df)} symbols to {OUT_PATH}")


if __name__ == "__main__":
    main()
