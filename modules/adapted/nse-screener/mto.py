"""Security-wise delivery (MTO) archives — fills the delivery columns for
2016-2019, where the legacy bhavcopy has none. Record-type-20 lines carry
symbol, series, traded qty, delivered qty, delivered %.

    python -m ingest.mto            # backfill 2016-2019 into data/mto/
"""
import io
from datetime import date, timedelta

import pandas as pd

import config
from ingest import nse

MTO_URL = "https://nsearchives.nseindia.com/archives/equities/mto/MTO_{ddmmyyyy}.DAT"


def fetch(d: date) -> pd.DataFrame | None:
    r = nse.get(MTO_URL.format(ddmmyyyy=d.strftime("%d%m%Y")),
                timeout=config.TIMEOUT)
    if r.status_code == 404:
        return None  # holiday
    r.raise_for_status()
    rows = []
    for line in io.StringIO(r.text):
        p = line.strip().split(",")
        if p[0] == "20" and len(p) >= 7 and p[3] in config.SERIES:
            rows.append((p[2].strip(), float(p[5]), float(p[6])))
    if not rows:
        return None
    df = pd.DataFrame(rows, columns=["symbol", "deliv_qty", "deliv_pct"])
    df["date"] = pd.to_datetime(d)
    return df


def store(d: date) -> bool:
    out = config.DATA_DIR / "mto" / f"{d.isoformat()}.parquet"
    if out.exists():
        return True
    df = fetch(d)
    if df is None or df.empty:
        return False
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, index=False)
    return True


def merge_into_bhav() -> int:
    """One-time: fill deliv columns of 2016-2019 bhav parquets in place."""
    fixed = 0
    for f in sorted((config.DATA_DIR / "mto").glob("*.parquet")):
        bf = config.DATA_DIR / "bhav" / f.name
        if not bf.exists():
            continue
        bhav = pd.read_parquet(bf)
        if bhav["deliv_qty"].notna().any():
            continue  # already has delivery data
        mto = pd.read_parquet(f)[["symbol", "deliv_qty", "deliv_pct"]]
        merged = bhav.drop(columns=["deliv_qty", "deliv_pct"]).merge(
            mto, on="symbol", how="left")
        merged.to_parquet(bf, index=False)
        fixed += 1
    return fixed


if __name__ == "__main__":
    import time
    d, got = date(2016, 1, 1), 0
    while d <= date(2019, 12, 31):
        if d.weekday() < 5:
            out = config.DATA_DIR / "mto" / f"{d.isoformat()}.parquet"
            if not out.exists():
                try:
                    if store(d):
                        got += 1
                        if got % 50 == 0:
                            print(f"{got} days, at {d}")
                    time.sleep(config.SLEEP_SECS)
                except Exception as e:
                    print(f"{d}: {e} — continuing")
        d += timedelta(days=1)
    print(f"MTO backfill done: {got} days. Merging into bhav parquets…")
    print(f"merged into {merge_into_bhav()} files")
