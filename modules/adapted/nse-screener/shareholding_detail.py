"""FII/DII/institutional detail per (symbol, quarter) from the NSE
shareholding-pattern detail API — the category breakdown the master API
lacks (master gives promoter/public only; this gives Mutual Funds,
Insurance, FPI categories, sub-totals B(1)/B(2)/B(3), row by row).

Endpoint (discovered from the site's corporate-filings.js, 2026-07-14):
    /api/corporate-share-holdings-equities?ndsId=<recordId>
        &index=public-shareholder
Detail exists for 2016+ filings only — the site routes older quarters to
legacy HTML archives (ShareholdingInformation*.html). recordId comes from
the master API, which phase 1 re-stores WITH that column.

    python -m ingest.shareholding_detail masters   # ~40 min, overwrite
    python -m ingest.shareholding_detail detail    # ~12 h, restartable
"""
import sys
import time
from pathlib import Path

import pandas as pd

import config
from ingest import nse
from ingest.shareholding import URL as MASTER_URL, DIR as MASTER_DIR, fetch

DETAIL_DIR = config.DATA_DIR / "shareholding_detail"
DETAIL_URL = ("https://www.nseindia.com/api/corporate-share-holdings-"
              "equities?ndsId={rid}&index=public-shareholder")
KEEP_MASTER = ["date", "broadcastDate", "pr_and_prgrp", "public_val",
               "revisedData", "recordId"]
WARMUP = ("https://www.nseindia.com/companies-listing/"
          "corporate-filings-shareholding-pattern")


def refresh_masters() -> None:
    """Re-store every master file WITH recordId (the original ingester
    dropped it). Overwrites in place; adds a column, loses nothing."""
    import ingest.shareholding as sh
    sh.KEEP = KEEP_MASTER                       # fetch() keeps what exists
    syms = sorted(p.stem for p in MASTER_DIR.glob("*.parquet"))
    s = nse.session()
    s.get(WARMUP, timeout=15)
    done = 0
    for sym in syms:
        f = MASTER_DIR / f"{sym}.parquet"
        if "recordId" in pd.read_parquet(f).columns:
            continue                            # restartable
        try:
            w = fetch(sym)
            if w is not None and len(w) and "recordId" in w.columns:
                w.to_parquet(f, index=False)
                done += 1
            time.sleep(0.6)
        except Exception as e:
            print(f"{sym}: {e} — continuing", flush=True)
        if done and done % 100 == 0:
            print(f"{done} masters refreshed", flush=True)
    print(f"masters refreshed: {done}")


def fetch_detail(rid: str) -> list[dict] | None:
    r = nse.get(DETAIL_URL.format(rid=rid), timeout=60)
    if r.status_code != 200 or not r.text.strip().startswith(("[", "{")):
        return None
    d = r.json()
    return d if isinstance(d, list) else d.get("data", [])


def detail() -> None:
    DETAIL_DIR.mkdir(parents=True, exist_ok=True)
    s = nse.session()
    s.get(WARMUP, timeout=15)
    syms = sorted(p.stem for p in MASTER_DIR.glob("*.parquet"))
    done = 0
    for sym in syms:
        out = DETAIL_DIR / f"{sym}.parquet"
        if out.exists():
            continue                            # restartable per symbol
        m = pd.read_parquet(MASTER_DIR / f"{sym}.parquet")
        if "recordId" not in m.columns:
            continue                            # masters phase incomplete
        m["qdate"] = pd.to_datetime(m["date"], format="%d-%b-%Y",
                                    errors="coerce")
        m = m[(m["qdate"] >= "2016-01-01") & m["recordId"].notna()]
        rows = []
        for _, mr in m.iterrows():
            try:
                d = fetch_detail(str(mr["recordId"]))
            except Exception as e:
                print(f"{sym}/{mr['recordId']}: {e}", flush=True)
                d = None
            time.sleep(0.5)
            if not d:
                continue
            for i, row in enumerate(d):
                rows.append({
                    "symbol": sym, "recordId": str(mr["recordId"]),
                    "date": mr["date"],
                    "broadcastDate": mr["broadcastDate"],
                    "row": i, "category": row.get("COL_I"),
                    "holders": row.get("COL_III"),
                    "shares": row.get("COL_VII"),
                    "pct": row.get("COL_VIII"),
                })
        pd.DataFrame(rows).to_parquet(out, index=False)
        done += 1
        if done % 25 == 0:
            print(f"{done} symbols stored (last: {sym})", flush=True)
    print(f"detail backfill done: {done} symbols this run")


if __name__ == "__main__":
    {"masters": refresh_masters, "detail": detail}[sys.argv[1]]()
