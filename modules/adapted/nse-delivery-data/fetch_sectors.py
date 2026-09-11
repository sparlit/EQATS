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
fetch_sectors.py
================
Downloads the official Nifty 500 constituents list from the NSE
and formats it into the 'nifty500_sectors.csv' mapping file required
by the Dual-Engine Backtester.
"""
import io

import pandas as pd
import requests


def fetch_nse_sector_mapping():
    # Official NSE URL for Nifty 500 constituents
    url = "https://nsearchives.nseindia.com/content/indices/ind_niftytotalmarket_list.csv"

    # Headers to fake a standard web browser
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }

    session = requests.Session()
    session.headers.update(headers)

    print("Establishing connection to NSE India...")
    try:
        # Hit the homepage first to establish session cookies
        session.get("https://www.nseindia.com", timeout=10)

        print("Downloading Nifty 500 industry mapping...")
        response = session.get(url, timeout=15)

        if response.status_code == 200:
            # Read the raw CSV text directly into Pandas
            csv_content = io.StringIO(response.text)
            df = pd.read_csv(csv_content)

            # The NSE CSV provides columns: 'Company Name', 'Industry', 'Symbol', 'Series', 'ISIN Code'
            # We isolate what we need and rename them for the backtester
            df = df[["Symbol", "Industry"]].copy()
            df.columns = ["SYMBOL", "SECTOR"]

            # Save it to the root directory where the backtester expects it
            df.to_csv("nifty500_sectors.csv", index=False)

            print(f"✅ Success! Saved mapping for {len(df)} stocks to nifty500_sectors.csv")

            # Display a quick preview to confirm successful parsing
            print("\nPreview of downloaded data:")
            print(df.head().to_markdown(index=False))

        else:
            print(f"❌ Failed to download. NSE returned HTTP Status: {response.status_code}")

    except Exception as e:
        print(f"❌ Execution failed: {e}")


if __name__ == "__main__":
    fetch_nse_sector_mapping()
