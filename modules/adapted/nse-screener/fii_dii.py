"""Aggregate FII/DII cash-market flows (₹ crore). Market-regime context only —
there is no public stock-level institutional flow. Use it to answer
'is smart money net buying this market?', nothing more granular."""
from datetime import date

import pandas as pd

import config
from ingest import nse


def store(d: date) -> None:
    r = nse.get(config.FII_DII_URL, timeout=config.TIMEOUT)
    if r.status_code != 200:
        print(f"  fii/dii failed: HTTP {r.status_code}")
        return
    try:
        df = pd.DataFrame(r.json())
    except ValueError:
        print("  fii/dii failed: non-JSON response (cookie issue, rerun)")
        return
    out = config.DATA_DIR / "fii_dii" / f"{d.isoformat()}.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, index=False)
