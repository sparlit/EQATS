"""India insider (PIT) disclosures — v21 raw material.

    python -m ingest.pit          # weekly chunks 2017→now → data/pit/
"""
import time
from datetime import date, timedelta

import pandas as pd

import config
from ingest import nse

URL = ("https://www.nseindia.com/api/corporates-pit"
       "?index=equities&from_date={frm}&to_date={to}")
DIR = config.DATA_DIR / "pit"
KEEP = ["symbol", "date", "intimDt", "acqName", "personCategory",
        "acqMode", "secType", "secVal", "buyValue", "sellValue",
        "secAcq", "befAcqSharesPer", "afterAcqSharesPer"]


def fetch_week(d0: date) -> pd.DataFrame | None:
    d1 = d0 + timedelta(days=6)
    r = nse.get(URL.format(frm=d0.strftime("%d-%m-%Y"),
                           to=d1.strftime("%d-%m-%Y")), timeout=90)
    if r.status_code != 200 or not r.text.strip().startswith(("[", "{")):
        return None
    rows = r.json()
    rows = rows if isinstance(rows, list) else rows.get("data", [])
    if not rows:
        return None
    df = pd.DataFrame(rows)
    cols = [c for c in KEEP if c in df.columns]
    return df[cols]


if __name__ == "__main__":
    DIR.mkdir(parents=True, exist_ok=True)
    d, got = date(2017, 1, 2), 0
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
    print(f"PIT backfill done: {got} weeks")
