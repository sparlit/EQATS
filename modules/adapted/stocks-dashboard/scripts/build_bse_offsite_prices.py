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


# -*- coding: utf-8 -*-
"""BSE equity scrips that traded since 2020 but sit in NEITHER price store → scripts/bse_offsite_prices.json.gz (§172).

WHY. docs/bse_prices.bin keeps only scrips on BSE's ListofScripData "Active" list that are not on NSE; the NSE tape keeps
NSE symbols (+ §149/§171 BSE-era prepends). A BSE equity that delisted/was suspended after 2020, or that trades but is
missing from the Active list (surveillance names trading once a week), exists nowhere. User (2026-09-26): every stock
from 2020 must be fetched; names no longer trading are stored as DATA ONLY (no page, no search, no screens).

WHAT. Every scrip in the §149 bhavcopy cache with an equity-share ISIN (INE…01…, or IN9 partly paid) whose scripcode is
not in docs/bse_prices.bin and whose ISIN (exact, or issuer isin[:7] of an equity ISIN) is not on NSE (tape meta,
EQUITY_L.csv, or the given NSE bhavcopies). Per scrip: RAW daily bars [d, o, h, l, c, v, turnover ₹] exactly as
BSE printed them, plus the §149 adjustment facts — `splits` (ISIN-confirmed) and `unexpl` (>30 % one-day falls, bonus
or crash, undecided). Nothing is adjusted here; a consumer adjusts. `last` = last BSE trade in the cache.

Run: BSE_BHAV_CACHE=~/stocks-cache/bse_bhav python3 -X utf8 scripts/build_bse_offsite_prices.py \
        --tape <sf bin with meta> --equity-l EQUITY_L.csv [--nse-bhav cmDDMMMYYYYbhav.csv,…] [--out PATH]
"""
import csv
import datetime
import gzip
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import build_bse_sme_backfill as BB
import build_bse_sme_prepend as BP

OUT = os.path.join(HERE, "bse_offsite_prices.json.gz")


def is_equity(i):
    return (i.startswith("INE") and i[7:9] == "01") or i.startswith("IN9")


def main():
    a = sys.argv[1:]

    def arg(k):
        return a[a.index(k) + 1] if k in a else None

    T = json.loads(gzip.open(arg("--tape")).read())
    nse = {m["isin"] for m in T["meta"].values() if m.get("isin")}
    for r in csv.DictReader(open(arg("--equity-l"), encoding="utf-8", errors="replace")):
        r = {k.strip(): (v or "").strip() for k, v in r.items() if k}
        if r.get("ISIN NUMBER"):
            nse.add(r["ISIN NUMBER"])
    for f in (arg("--nse-bhav") or "").split(","):
        if f:
            for r in csv.DictReader(open(f, encoding="utf-8", errors="replace")):
                if r.get("ISIN"):
                    nse.add(r["ISIN"].strip())
    nse_iss = {i[:7] for i in nse if is_equity(i)}
    store = json.loads(
        gzip.decompress(open(os.path.join(HERE, "..", "docs", "bse_prices.bin"), "rb").read())
    )["px"]
    ser, days, _ = BB.build_series("ALL")
    pick = {
        c: s
        for c, s in ser.items()
        if is_equity(s.get("isin") or "")
        and c not in store
        and s["isin"] not in nse
        and s["isin"][:7] not in nse_iss
    }
    rows = BP.ohlc_rows(set(pick))
    out = {}
    for c, s in sorted(pick.items()):
        R = rows[c]
        bars = [
            [d] + [round(x, 2) for x in R[d][:4]] + [int(R[d][4]), round(R[d][5], 2)]
            for d in sorted(R)
            if R[d][3] > 0
        ]
        if not bars:
            continue
        out[c] = {
            "tk": s.get("tk"),
            "isin": s["isin"],
            "first": bars[0][0],
            "last": bars[-1][0],
            "splits": s.get("splits", []),
            "unexpl": s.get("unexpl", []),
            "bars": bars,
        }
    cache_end = max(max(s["d"]) for s in ser.values())
    blob = {
        "built": datetime.date.today().isoformat(),
        "cache_end": cache_end,
        "days": days,
        "keys": ["d", "o", "h", "l", "c", "v", "turnover_rs"],
        "scrips": out,
    }
    p = arg("--out") or OUT
    with gzip.open(p, "wt", encoding="utf-8") as fh:
        json.dump(blob, fh, separators=(",", ":"))
    recent = sum(
        1 for v in out.values() if v["last"] >= cache_end - 300
    )  # traded within ~3 months of cache end
    print(
        "offsite: %d scrips, %d bars, %d traded in the last ~3 months of the cache (to %d) -> %s"
        % (len(out), sum(len(v["bars"]) for v in out.values()), recent, cache_end, p)
    )


if __name__ == "__main__":
    main()
