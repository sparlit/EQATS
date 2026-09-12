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


"""Quarterly shareholding patterns per symbol (promoter/public %, with
broadcast timestamps = point-in-time). One API call per symbol.

    python -m ingest.shareholding    # liquid universe → data/shareholding/
"""
import time

import pandas as pd
from ingest import nse
from ingest.financials import _liquid_universe

import config

URL = "https://www.nseindia.com/api/corporate-share-holdings-master?index=equities&symbol={sym}"
DIR = config.DATA_DIR / "shareholding"
KEEP = ["date", "broadcastDate", "pr_and_prgrp", "public_val", "revisedData"]


def fetch(sym: str) -> pd.DataFrame | None:
    r = nse.get(URL.format(sym=sym.replace("&", "%26")), timeout=60)
    if r.status_code != 200 or not r.text.strip().startswith(("[", "{")):
        return None
    rows = r.json()
    rows = rows if isinstance(rows, list) else rows.get("data", [])
    if not rows:
        return None
    df = pd.DataFrame(rows)
    cols = [c for c in KEEP if c in df.columns]
    out = df[cols].copy()
    out["symbol"] = sym
    return out


if __name__ == "__main__":
    DIR.mkdir(parents=True, exist_ok=True)
    syms = sorted(_liquid_universe())
    got = 0
    s = nse.session()
    s.get("https://www.nseindia.com/companies-listing/corporate-filings-shareholding-pattern", timeout=15)
    for sym in syms:
        f = DIR / f"{sym}.parquet"
        if f.exists():
            continue
        try:
            w = fetch(sym)
            if w is not None and len(w):
                w.to_parquet(f, index=False)
                got += 1
            time.sleep(0.8)
        except Exception as e:
            print(f"{sym}: {e} — continuing")
        if got and got % 200 == 0:
            print(f"{got} symbols stored")
    print(f"shareholding backfill done: {got} symbols")
