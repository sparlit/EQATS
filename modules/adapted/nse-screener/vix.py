"""India VIX daily history (information input only — no F&O trading).

    python -m ingest.vix       # → data/india_vix.parquet, 2016→present
"""
import time
from datetime import date, timedelta

import pandas as pd

import config
from ingest import nse

URL = ("https://www.nseindia.com/api/historicalOR/vixhistory"
       "?from={frm}&to={to}&csv=true")
OUT = config.DATA_DIR / "india_vix.parquet"


def backfill(start: date = date(2016, 1, 1)) -> pd.DataFrame:
    frames, d = [], start
    while d <= date.today():
        q = min(d + timedelta(days=89), date.today())
        r = nse.get(URL.format(frm=d.strftime("%d-%m-%Y"),
                               to=q.strftime("%d-%m-%Y")),
                    timeout=config.TIMEOUT)
        if r.status_code == 200 and r.text.strip().startswith("{"):
            rows = r.json().get("data", [])
            if rows:
                frames.append(pd.DataFrame(rows))
        d = q + timedelta(days=1)
        time.sleep(config.SLEEP_SECS)
    df = pd.concat(frames, ignore_index=True)
    df["date"] = pd.to_datetime(df["EOD_TIMESTAMP"], format="%d-%b-%Y")
    df = (df.rename(columns={"EOD_CLOSE_INDEX_VAL": "vix"})
            [["date", "vix"]].drop_duplicates("date").sort_values("date"))
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
