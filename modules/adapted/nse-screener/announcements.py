"""Corporate announcements (buybacks, order wins) — v17 raw material.

    python -m ingest.announcements     # weekly chunks 2016→now, slim store

Full feed is ~1.3M rows/decade; we keep only event-relevant rows plus a
WEEKLY COUNT of all announcements (needed for the all-announcements
baseline null) and a 2% random sample of non-matching rows for the
baseline event pool.
"""
import random
import time
from datetime import date, timedelta

import pandas as pd

import config
from ingest import nse

URL = ("https://www.nseindia.com/api/corporate-announcements"
       "?index=equities&from_date={frm}&to_date={to}")
DIR = config.DATA_DIR / "announcements"

KEEP = ("buyback", "buy back", "buy-back",
        "award of order", "receipt of order", "bagging", "order received")


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
    sym_col = "symbol" if "symbol" in df.columns else "sm_symbol"
    if sym_col not in df.columns:
        return None
    df = df.rename(columns={sym_col: "symbol"})
    blob = (df.get("desc", "").astype(str) + " "
            + df.get("attchmntText", "").astype(str)).str.lower()
    df["kind"] = ""
    df.loc[blob.str.contains("buyback|buy back|buy-back", regex=True),
           "kind"] = "buyback"
    df.loc[blob.str.contains(
        "award of order|receipt of order|bagging|order received",
        regex=True), "kind"] = "order_win"
    rng = random.Random(str(d0))
    baseline = df[df["kind"] == ""].sample(
        frac=0.02, random_state=rng.randint(0, 2**31))
    baseline = baseline.assign(kind="baseline")
    keep = pd.concat([df[df["kind"] != ""], baseline])
    out = keep[["symbol", "an_dt", "desc", "kind"]].copy()
    out["total_that_week"] = len(df)
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
    print(f"announcements backfill done: {got} weeks")
