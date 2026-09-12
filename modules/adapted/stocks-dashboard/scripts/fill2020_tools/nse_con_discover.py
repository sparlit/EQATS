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
"""FILL-2020 pre-2020 con-PAT: DISCOVERY sweep of the NSE results archive.

Before reading anything, enumerate which of the 2,979 gap cells (311 companies, quarters
20150331..20191231, consolidated PAT empty) actually have a CONSOLIDATED filing available.
Runbook §51a says most pre-FY2020 con quarters were never filed -- this sweep measures the
honest fillable ceiling instead of assuming it, using the NSE archive list API (proven to serve
delisted symbols and to declare basis per row -- ADVANTA/SATYAMCOMP precedents, §52c):

    /api/corporates-financial-results?index=equities&symbol=<SYM>&period=Quarterly   (and Annual)
    row fields: toDate, consolidated ("Consolidated"/"Non-Consolidated"), resultDetailedDataLink

Output scripts/fill2020_tools/_con_nse_inventory.json:
    sym -> {"qtr": {qe: detail_link}, "ann": {fy_end_qe: link}, "rows": N, "err": reason?}
Annual con rows are captured too -- they power the §45 FY-sum gate at read time.

Resumable: symbols already in the output file are skipped. Rate-discipline: sequential,
~0.8s between calls, session refresh on 401/403, hard abort after 10 consecutive failures
(NSE all-transport-403 lockdown = wait it out, memory project-stocks-nse-api-lockdown).

Run:  python -X utf8 scripts/fill2020_tools/nse_con_discover.py [--limit N]
"""
import contextlib
import json
import os
import sys
import time
import urllib.parse

from curl_cffi import requests as cr

HERE = os.path.dirname(os.path.abspath(__file__))
TARGETS = os.path.join(HERE, "_con_targets_pre2020.json")
OUT = os.path.join(HERE, "_con_nse_inventory.json")

MON = {
    "Jan": 1,
    "Feb": 2,
    "Mar": 3,
    "Apr": 4,
    "May": 5,
    "Jun": 6,
    "Jul": 7,
    "Aug": 8,
    "Sep": 9,
    "Oct": 10,
    "Nov": 11,
    "Dec": 12,
}


def to_qe(s):
    """'30-Sep-2015' -> 20150930."""
    try:
        d, mo, y = s.split("-")
        return int(y) * 10000 + MON[mo] * 100 + int(d)
    except Exception:
        return None


def fresh_session():
    s = cr.Session(impersonate="chrome")
    s.get("https://www.nseindia.com/", timeout=45)
    time.sleep(1)
    return s


def fetch_list(sess, sym, period):
    u = (
        "https://www.nseindia.com/api/corporates-financial-results?index=equities"
        f"&symbol={urllib.parse.quote(sym)}&period={period}"
    )
    r = sess.get(
        u,
        headers={"Referer": "https://www.nseindia.com/companies-listing/corporate-filings-financial-results"},
        timeout=45,
    )
    if r.status_code != 200:
        raise RuntimeError("http%d" % r.status_code)
    d = r.json()
    return d if isinstance(d, list) else d.get("data", [])


def main():
    limit = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else None
    targets = json.load(open(TARGETS))
    inv = json.load(open(OUT)) if os.path.exists(OUT) else {}
    todo = [s for s in sorted(targets) if s not in inv]
    if limit:
        todo = todo[:limit]
    print("discovery: %d symbols to sweep (%d already done)" % (len(todo), len(inv)), flush=True)
    sess = fresh_session()
    consec_err = 0
    for i, sym in enumerate(todo):
        gaps = set(targets[sym]["qes"])
        rec = {"qtr": {}, "ann": {}, "rows": 0}
        try:
            rows = fetch_list(sess, sym, "Quarterly")
            time.sleep(0.8)
            rec["rows"] = len(rows)
            for row in rows:
                if (row.get("consolidated") or "").startswith("Consolidated"):
                    qe = to_qe(row.get("toDate") or "")
                    if qe in gaps and row.get("resultDetailedDataLink"):
                        rec["qtr"][str(qe)] = row["resultDetailedDataLink"]
            arows = fetch_list(sess, sym, "Annual")
            time.sleep(0.8)
            for row in arows:
                if (row.get("consolidated") or "").startswith("Consolidated"):
                    qe = to_qe(row.get("toDate") or "")
                    if qe and 20140601 <= qe <= 20200401 and row.get("resultDetailedDataLink"):
                        rec["ann"][str(qe)] = row["resultDetailedDataLink"]
            consec_err = 0
        except Exception as ex:
            rec["err"] = f"{type(ex).__name__}:{str(ex)[:60]}"
            consec_err += 1
            with contextlib.suppress(Exception):
                sess = fresh_session()
            if consec_err >= 10:
                print("!! 10 consecutive failures -- NSE lockdown? aborting sweep (resumable).", flush=True)
                break
        inv[sym] = rec
        if (i + 1) % 20 == 0 or i + 1 == len(todo):
            json.dump(inv, open(OUT, "w"), indent=0, sort_keys=True)
            hits = sum(len(v["qtr"]) for v in inv.values())
            print("  [%d/%d] %s -- con-qtr hits so far: %d" % (i + 1, len(todo), sym, hits), flush=True)
    json.dump(inv, open(OUT, "w"), indent=0, sort_keys=True)
    hits = sum(len(v["qtr"]) for v in inv.values())
    anns = sum(len(v["ann"]) for v in inv.values())
    errs = sum(1 for v in inv.values() if v.get("err"))
    print(
        "DONE: %d symbols, %d gap-cells have a con quarterly filing, %d con annuals, %d errors"
        % (len(inv), hits, anns, errs),
        flush=True,
    )


if __name__ == "__main__":
    main()
