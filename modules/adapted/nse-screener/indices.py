"""Sector/thematic index daily OHLC (proper sector benchmarks).

    python -m ingest.indices      # 2016→now → data/indices/
"""
import time
from datetime import date, timedelta

import pandas as pd

import config
from ingest import nse

URL = ("https://www.nseindia.com/api/historicalOR/indicesHistory"
       "?indexType={idx}&from={frm}&to={to}")
DIR = config.DATA_DIR / "indices"
INDICES = ["NIFTY 50", "NIFTY BANK", "NIFTY IT", "NIFTY PHARMA",
           "NIFTY AUTO", "NIFTY FMCG", "NIFTY METAL", "NIFTY REALTY",
           "NIFTY ENERGY", "NIFTY FINANCIAL SERVICES", "NIFTY MEDIA",
           "NIFTY PSU BANK", "NIFTY INFRASTRUCTURE", "NIFTY MIDCAP 100",
           "NIFTY SMALLCAP 100"]


def backfill():
    DIR.mkdir(parents=True, exist_ok=True)
    for idx in INDICES:
        f = DIR / f"{idx.replace(' ', '_')}.parquet"
        if f.exists():
            continue
        frames, d = [], date(2016, 1, 1)
        while d <= date.today():
            q = min(d + timedelta(days=89), date.today())
            try:
                r = nse.get(URL.format(idx=idx.replace(" ", "%20"),
                                       frm=d.strftime("%d-%m-%Y"),
                                       to=q.strftime("%d-%m-%Y")), timeout=60)
                if r.status_code == 200 and r.text.strip().startswith(("[", "{")):
                    rows = r.json().get("data", [])
                    if rows:
                        frames.append(pd.DataFrame(rows))
            except Exception as e:
                print(f"{idx} {d}: {e}")
            d = q + timedelta(days=1)
            time.sleep(0.8)
        if frames:
            df = pd.concat(frames, ignore_index=True)
            df["date"] = pd.to_datetime(df["EOD_TIMESTAMP"], format="%d-%b-%Y")
            df = (df.rename(columns={"EOD_CLOSE_INDEX_VAL": "close"})
                    [["date", "close"]].drop_duplicates("date")
                    .sort_values("date"))
            df.to_parquet(f, index=False)
            print(f"{idx}: {len(df)} days")
    print("indices backfill done")


if __name__ == "__main__":
    backfill()
