"""Quarterly shareholding patterns per symbol (promoter/public %, with
broadcast timestamps = point-in-time). One API call per symbol.

    python -m ingest.shareholding    # liquid universe → data/shareholding/
"""
import time

import pandas as pd

import config
from ingest import nse
from ingest.financials import _liquid_universe

URL = ("https://www.nseindia.com/api/corporate-share-holdings-master"
       "?index=equities&symbol={sym}")
DIR = config.DATA_DIR / "shareholding"
KEEP = ["date", "broadcastDate", "pr_and_prgrp", "public_val", "revisedData"]


def fetch(sym: str) -> pd.DataFrame | None:
    r = nse.get(URL.format(sym=sym.replace("&", "%26")), timeout=60)
    if r.status_code != 200 or not r.text.strip().startswith(("[", "{")):
        return None
    rows = r.json()
    rows = rows if isinstance(rows, list) else rows.get("data", [])
    if not rows:
        return None
    df = pd.DataFrame(rows)
    cols = [c for c in KEEP if c in df.columns]
    out = df[cols].copy()
    out["symbol"] = sym
    return out


if __name__ == "__main__":
    DIR.mkdir(parents=True, exist_ok=True)
    syms = sorted(_liquid_universe())
    got = 0
    s = nse.session()
    s.get("https://www.nseindia.com/companies-listing/"
          "corporate-filings-shareholding-pattern", timeout=15)
    for sym in syms:
        f = DIR / f"{sym}.parquet"
        if f.exists():
            continue
        try:
            w = fetch(sym)
            if w is not None and len(w):
                w.to_parquet(f, index=False)
                got += 1
            time.sleep(0.8)
        except Exception as e:
            print(f"{sym}: {e} — continuing")
        if got and got % 200 == 0:
            print(f"{got} symbols stored")
    print(f"shareholding backfill done: {got} symbols")
