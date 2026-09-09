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


"""Sector/industry map (today's Nifty Total Market classification) and
the monthly pledge-snapshot capture (v20 dataset under construction).
"""
import io
from datetime import date

import pandas as pd
from ingest import nse, renames

import config

IDX_URL = "https://nsearchives.nseindia.com/content/indices/ind_niftytotalmarket_list.csv"
MAP_OUT = config.DATA_DIR / "sector_map.parquet"
PLEDGE_DIR = config.DATA_DIR / "pledge"
PLEDGE_URL = "https://www.nseindia.com/api/corporate-pledgedata?index=equities"


def sector_map() -> pd.Series:
    if not MAP_OUT.exists():
        r = nse.get(IDX_URL, timeout=config.TIMEOUT)
        r.raise_for_status()
        df = pd.read_csv(io.BytesIO(r.content))
        df = df.rename(columns={"Symbol": "symbol", "Industry": "industry"})
        df["symbol"] = renames.canonical(df["symbol"].str.strip())
        df[["symbol", "industry"]].to_parquet(MAP_OUT, index=False)
    m = pd.read_parquet(MAP_OUT)
    return m.set_index("symbol")["industry"]


def capture_pledge_snapshot() -> None:
    """Monthly: store today's promoter-pledge state. In a year this IS
    the point-in-time dataset v20 needs."""
    out = PLEDGE_DIR / f"{date.today().isoformat()}.parquet"
    if out.exists():
        return
    s = nse.session()
    s.get("https://www.nseindia.com/companies-listing/corporate-filings-pledged-data", timeout=15)
    r = s.get(PLEDGE_URL, timeout=90)
    rows = r.json()
    rows = rows if isinstance(rows, list) else rows.get("data", [])
    if not rows:
        return
    PLEDGE_DIR.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_parquet(out, index=False)
    print(f"pledge snapshot: {len(rows)} rows → {out.name}")
