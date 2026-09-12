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


"""India VIX daily history (information input only — no F&O trading).

    python -m ingest.vix       # → data/india_vix.parquet, 2016→present
"""
import time
from datetime import date, timedelta

import pandas as pd
from ingest import nse

import config

URL = "https://www.nseindia.com/api/historicalOR/vixhistory?from={frm}&to={to}&csv=true"
OUT = config.DATA_DIR / "india_vix.parquet"


def backfill(start: date = date(2016, 1, 1)) -> pd.DataFrame:
    frames, d = [], start
    while d <= date.today():
        q = min(d + timedelta(days=89), date.today())
        r = nse.get(URL.format(frm=d.strftime("%d-%m-%Y"), to=q.strftime("%d-%m-%Y")), timeout=config.TIMEOUT)
        if r.status_code == 200 and r.text.strip().startswith("{"):
            rows = r.json().get("data", [])
            if rows:
                frames.append(pd.DataFrame(rows))
        d = q + timedelta(days=1)
        time.sleep(config.SLEEP_SECS)
    df = pd.concat(frames, ignore_index=True)
    df["date"] = pd.to_datetime(df["EOD_TIMESTAMP"], format="%d-%b-%Y")
    df = df.rename(columns={"EOD_CLOSE_INDEX_VAL": "vix"})[["date", "vix"]].drop_duplicates("date").sort_values("date")
    df.to_parquet(OUT, index=False)
    print(f"{len(df)} VIX days → {OUT}")
    return df


def series() -> pd.Series:
    if not OUT.exists():
        backfill()
    df = pd.read_parquet(OUT)
    return df.set_index("date")["vix"]


if __name__ == "__main__":
    backfill()
