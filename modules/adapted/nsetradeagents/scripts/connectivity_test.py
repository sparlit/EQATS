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


"""Can this machine reach the two data sources the bot depends on?

Run before provisioning anything permanent. NSE archives and Yahoo Finance both
throttle datacenter IPs, and `safe_yf_download` has no retry — a single refusal
on the 400-ticker batch ends a day's scan silently.

Standalone on purpose: no app imports, no database, no config.

    python3 -m venv /tmp/t
    /tmp/t/bin/pip install -q yfinance requests pandas
    /tmp/t/bin/python connectivity_test.py

Home-IP baseline for comparison: NSE 200 / 250 tickers, yfinance 250/250.
"""

import io

import pandas as pd
import requests
import yfinance as yf

NSE_URL = "https://archives.nseindia.com/content/indices/ind_niftysmallcap250list.csv"
NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://www.nseindia.com",
}

# Used only if NSE blocks us, so the yfinance check still runs.
FALLBACK = [
    "TITAN.NS",
    "TATAMOTORS.NS",
    "SUNPHARMA.NS",
    "AXISBANK.NS",
    "WIPRO.NS",
    "HINDALCO.NS",
    "GRASIM.NS",
    "CIPLA.NS",
    "BEL.NS",
    "TRENT.NS",
]

print("=" * 55)
print("1. NSE archives")
print("=" * 55)

tickers = []
try:
    r = requests.get(NSE_URL, headers=NSE_HEADERS, timeout=15)
    print(f"   status: {r.status_code}   bytes: {len(r.content)}")
    if r.status_code == 200:
        df = pd.read_csv(io.StringIO(r.text))
        col = next(c for c in df.columns if "symbol" in c.lower())
        tickers = [f"{s.strip().upper()}.NS" for s in df[col].dropna().astype(str)]
        print(f"   PASS - {len(tickers)} tickers")
    else:
        print(f"   FAIL - blocked\n   body: {r.text[:200]}")
except Exception as e:
    print(f"   FAIL - {type(e).__name__}: {e}")

print()
print("=" * 55)
print("2. yfinance batch download")
print("=" * 55)

# The real scan pulls the whole universe in one call; that batch size is what
# gets rate-limited, so test at full size rather than with a token few.
batch = tickers or FALLBACK
print(f"   requesting {len(batch)} tickers, 6mo daily")

try:
    raw = yf.download(
        batch,
        period="6mo",
        interval="1d",
        auto_adjust=True,
        progress=False,
        threads=True,
    )
    if raw.empty:
        print("   FAIL - empty frame (rate limited or blocked)")
    else:
        got = len(set(raw.columns.get_level_values(1))) if isinstance(raw.columns, pd.MultiIndex) else 1
        pct = got / len(batch) * 100
        print(f"   rows: {len(raw)}   tickers with data: {got}/{len(batch)} ({pct:.0f}%)")
        print("   PASS" if pct > 90 else "   PARTIAL - some tickers returned nothing")
except Exception as e:
    print(f"   FAIL - {type(e).__name__}: {e}")

print()
print("Both must PASS before provisioning anything permanent.")
