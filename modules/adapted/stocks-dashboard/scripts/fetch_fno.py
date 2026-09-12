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
"""Fetch the current NSE F&O underlyings list from fo_mktlots.csv.

Produces scripts/fno_list.json with shape:
  { "asOf": "YYYY-MM-DD", "stocks": ["RELIANCE", "TCS", ...] }

NOTE: This is TODAY's list. Historical F&O membership (which stocks were in F&O
on a past date) is not yet tracked — see fetch_fno_history.py for that.
The dashboard falls back to today's list when no historical snapshot exists.
"""
import csv
import io
import json
import subprocess
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "scripts" / "fno_list.json"
URL = "https://nsearchives.nseindia.com/content/fo/fo_mktlots.csv"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

# Index underlyings are filtered out — we only want stock F&O
INDEX_UNDERLYINGS = {
    "NIFTY",
    "BANKNIFTY",
    "FINNIFTY",
    "MIDCPNIFTY",
    "NIFTYNXT50",
    "NIFTYIT",
    "NIFTYBANK",
    "BANKEX",
    "SENSEX",
    "SENSEX50",
}

print(f"Fetching {URL}...")
r = subprocess.run(["curl", "-s", "-A", UA, "--max-time", "20", URL], capture_output=True, timeout=30)
text = r.stdout.decode("utf-8", errors="ignore")
if len(text) < 1000:
    print(f"  WARN: response too short ({len(text)} bytes), keeping existing fno_list.json")
    raise SystemExit(0)

# NSE's CSV actually has TWO header rows:
#   1) "UNDERLYING, SYMBOL, MAY-26, JUN-26, ..."
#   2) "Derivatives on Individual Securities, Symbol, ..." (sub-section header)
# The case differs ("SYMBOL" vs "Symbol") so we need both forms in the skip list.
BOGUS_HEADERS = {"SYMBOL", "Symbol", "symbol", "TckrSymb", "TCKR"}
rows = list(csv.reader(io.StringIO(text)))
stocks = []
for r in rows[1:]:
    if len(r) < 2:
        continue
    sym = r[1].strip().strip('"')
    if not sym or sym in BOGUS_HEADERS:
        continue
    if sym in INDEX_UNDERLYINGS:
        continue
    stocks.append(sym)

stocks = sorted(set(stocks))
print(f"  Parsed {len(stocks)} stock F&O underlyings")
OUT.write_text(
    json.dumps(
        {
            "asOf": date.today().strftime("%Y-%m-%d"),
            "stocks": stocks,
        },
        indent=2,
    )
)
print(f"Saved → {OUT}")
