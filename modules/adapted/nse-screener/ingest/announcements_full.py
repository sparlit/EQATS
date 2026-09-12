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


"""Full announcements taxonomy (v22 raw material): category label for
EVERY announcement + a text snippet for the risk-relevant categories.

    python -m ingest.announcements_full   # weekly 2016→now → data/ann_full/
"""
import time
from datetime import date, timedelta

import pandas as pd
from ingest import nse

import config

URL = "https://www.nseindia.com/api/corporate-announcements?index=equities&from_date={frm}&to_date={to}"
DIR = config.DATA_DIR / "ann_full"
RISKY = ("rating", "director", "auditor", "resign", "key managerial")


def fetch_week(d0: date) -> pd.DataFrame | None:
    d1 = d0 + timedelta(days=6)
    r = nse.get(URL.format(frm=d0.strftime("%d-%m-%Y"), to=d1.strftime("%d-%m-%Y")), timeout=90)
    if r.status_code != 200 or not r.text.strip().startswith(("[", "{")):
        return None
    rows = r.json()
    rows = rows if isinstance(rows, list) else rows.get("data", [])
    if not rows:
        return None
    df = pd.DataFrame(rows)
    sym = "symbol" if "symbol" in df.columns else "sm_symbol"
    if sym not in df.columns:
        return None
    out = pd.DataFrame(
        {
            "symbol": df[sym].astype(str).str.strip(),
            "an_dt": df["an_dt"],
            "desc": df.get("desc", "").astype(str),
        }
    )
    blob = (out["desc"] + " " + df.get("attchmntText", "").astype(str)).str.lower()
    risky = blob.str.contains("|".join(RISKY), regex=True)
    out["snippet"] = ""
    out.loc[risky, "snippet"] = df.get("attchmntText", "").astype(str).str[:220][risky]
    return out


if __name__ == "__main__":
    DIR.mkdir(parents=True, exist_ok=True)
    d, got = date(2016, 1, 4), 0
    while d <= date.today():
        f = DIR / f"{d.isoformat()}.parquet"
        if not f.exists():
            try:
                w = fetch_week(d)
                if w is not None and len(w):
                    w.to_parquet(f, index=False)
                    got += 1
                time.sleep(1.0)
            except Exception as e:
                print(f"{d}: {e} — continuing")
        d += timedelta(days=7)
        if got and got % 50 == 0:
            print(f"{got} weeks stored, at {d}")
    print(f"announcements_full backfill done: {got} weeks")
