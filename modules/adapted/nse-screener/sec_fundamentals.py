"""SEC Financial Statement Data Sets → point-in-time US EPS.
Quarterly ZIPs (2009q2→) with every XBRL filing's numbers + FILED date.
Keeps only EPS tags; one parquet per quarter, restartable.

    python -m ingest.sec_fundamentals
"""
import io
import time
import zipfile
from datetime import date
from pathlib import Path

import pandas as pd
import requests

import config

DIR = config.DATA_DIR / "sec_fund"
URL = ("https://www.sec.gov/files/dera/data/"
       "financial-statement-data-sets/{tag}.zip")
H = {"User-Agent": "research contact@deshpanda.dev"}
TAGS = {"EarningsPerShareBasic", "EarningsPerShareDiluted"}


def quarters():
    y, q = 2009, 2
    while (y, q) <= (date.today().year, (date.today().month - 1) // 3 + 1):
        yield f"{y}q{q}"
        q += 1
        if q == 5:
            y, q = y + 1, 1


def fetch_one(tag: str) -> pd.DataFrame | None:
    r = requests.get(URL.format(tag=tag), headers=H, timeout=300)
    if r.status_code != 200:
        print(f"{tag}: HTTP {r.status_code} — skipped", flush=True)
        return None
    z = zipfile.ZipFile(io.BytesIO(r.content))
    sub = pd.read_csv(z.open("sub.txt"), sep="\t", dtype=str,
                      usecols=["adsh", "cik", "form", "period", "filed"])
    sub = sub[sub["form"].isin(["10-Q", "10-K"])]
    keep = []
    for chunk in pd.read_csv(z.open("num.txt"), sep="\t", dtype=str,
                             usecols=["adsh", "tag", "ddate", "qtrs",
                                      "value"], chunksize=1_000_000):
        c = chunk[chunk["tag"].isin(TAGS) & chunk["qtrs"].isin(["1", "4"])]
        if len(c):
            keep.append(c)
    if not keep:
        return pd.DataFrame()
    num = pd.concat(keep, ignore_index=True)
    return num.merge(sub, on="adsh")


def main():
    DIR.mkdir(parents=True, exist_ok=True)
    for tag in quarters():
        out = DIR / f"{tag}.parquet"
        if out.exists():
            continue
        try:
            df = fetch_one(tag)
        except Exception as e:
            print(f"{tag}: {e} — continuing", flush=True)
            continue
        if df is None:
            continue
        df.to_parquet(out, index=False)
        print(f"{tag}: {len(df):,} EPS rows", flush=True)
        time.sleep(2)
    print("sec fundamentals done:", len(list(DIR.glob("*.parquet"))),
          "quarters")


if __name__ == "__main__":
    main()
