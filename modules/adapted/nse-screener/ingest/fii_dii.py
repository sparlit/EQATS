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


"""Aggregate FII/DII cash-market flows (₹ crore). Market-regime context only —
there is no public stock-level institutional flow. Use it to answer
'is smart money net buying this market?', nothing more granular."""
from datetime import date

import pandas as pd
from ingest import nse

import config


def store(d: date) -> None:
    r = nse.get(config.FII_DII_URL, timeout=config.TIMEOUT)
    if r.status_code != 200:
        print(f"  fii/dii failed: HTTP {r.status_code}")
        return
    try:
        df = pd.DataFrame(r.json())
    except ValueError:
        print("  fii/dii failed: non-JSON response (cookie issue, rerun)")
        return
    out = config.DATA_DIR / "fii_dii" / f"{d.isoformat()}.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, index=False)
