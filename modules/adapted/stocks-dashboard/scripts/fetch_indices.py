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
"""Download Nifty index constituent CSVs from NSE archives and tag each stock
   in scripts/stock_data.json with the indices it belongs to."""
import csv
import io
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "scripts" / "stock_data.json"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

# Display name → NSE CSV slug (under https://archives.nseindia.com/content/indices/ind_{slug}list.csv)
INDEX_URLS = {
    "Nifty 50": "nifty50",
    "Nifty Next 50": "niftynext50",
    "Nifty 100": "nifty100",
    "Nifty 200": "nifty200",
    "Nifty 500": "nifty500",
    "Nifty Midcap 50": "niftymidcap50",
    "Nifty Midcap 100": "niftymidcap100",
    "Nifty Midcap 150": "niftymidcap150",
    "Nifty Smallcap 50": "niftysmallcap50",
    "Nifty Smallcap 100": "niftysmallcap100",
    "Nifty Smallcap 250": "niftysmallcap250",
    "Nifty LargeMidcap 250": "niftylargemidcap250",
    "Nifty MidSmallcap 400": "niftymidsmallcap400",
    # Sectoral
    "Nifty Bank": "niftybank",
    "Nifty IT": "niftyit",
    "Nifty Pharma": "niftypharma",
    "Nifty Auto": "niftyauto",
    "Nifty FMCG": "niftyfmcg",
    "Nifty Metal": "niftymetal",
    "Nifty Energy": "niftyenergy",
    "Nifty Realty": "niftyrealty",
    "Nifty Media": "niftymedia",
    "Nifty Healthcare": "niftyhealthcare",
    "Nifty Consumer Durables": "niftyconsumerdurables",
    "Nifty Oil & Gas": "niftyoilgas",
    "Nifty PSU Bank": "niftypsubank",
    "Nifty MNC": "niftymnc",
}


def fetch_csv(slug):
    url = f"https://archives.nseindia.com/content/indices/ind_{slug}list.csv"
    r = subprocess.run(["curl", "-s", "--max-time", "12", "-A", UA, url], capture_output=True, timeout=15)
    if not r.stdout:
        return []
    if r.stdout[:3] == b"<!D" or r.stdout[:5] == b"<html":
        return []  # error page
    try:
        text = r.stdout.decode("utf-8", errors="ignore")
        rows = list(csv.DictReader(io.StringIO(text)))
        return [(row.get("Symbol") or "").strip() for row in rows if row.get("Symbol")]
    except Exception:
        return []


# Pull every index — ticker -> set(indices)
print("Fetching index constituents from NSE archives...")
ticker_to_indices = {}
for display, slug in INDEX_URLS.items():
    symbols = fetch_csv(slug)
    if not symbols:
        print(f"  WARN  {display:30s}  (slug={slug})  0 symbols")
        continue
    print(f"  OK    {display:30s}  {len(symbols):4d} symbols")
    for sym in symbols:
        ticker_to_indices.setdefault(sym, set()).add(display)

# Convert sets to sorted lists for stable JSON
ticker_to_indices = {sym: sorted(idxs) for sym, idxs in ticker_to_indices.items()}
print(f"\nTotal unique NSE symbols across all indices: {len(ticker_to_indices)}")

# Merge into stock_data.json. Our tickers are like RELIANCE.NS or 543620.BO.
# Match by the symbol part (before the suffix), and only for .NS tickers (the
# NSE indices only list NSE symbols).
data = json.loads(DATA.read_text())
tagged = 0
for ticker, meta in data["meta"].items():
    if not ticker.endswith(".NS"):
        meta["indices"] = []
        continue
    sym = ticker.rsplit(".", 1)[0]
    idxs = ticker_to_indices.get(sym, [])
    meta["indices"] = idxs
    if idxs:
        tagged += 1
print(f"\nTagged {tagged} / {len(data['meta'])} stocks with index membership")
DATA.write_text(json.dumps(data, separators=(",", ":")))
print(f"Updated {DATA}")
