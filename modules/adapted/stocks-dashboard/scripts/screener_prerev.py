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
"""Fetch pre/post-IPO quarterly REVENUE (Sales row) from Screener for symbols whose PAT already
came from Screener (screener_prefund.py stored np only and threw the Sales row away — this is
the companion pass the 2026-07-22 Dec-24/Sep-24/Jun-24 audit called for).

ANCHOR (never assumes): a quarter's Sales is accepted ONLY when Screener's Net Profit for that
same (quarter, basis) matches our stored sf_fundamentals PAT within max(3%, Rs 2cr) — the same
tolerance the original merge used. No anchor -> no write, logged to the skip report.

Insurers are EXCLUDED (Screener's insurer 'Revenue' row != our NPI+investment-income convention).

Writes STAGING ONLY: scripts/screener_rev.json  {sym: {qe: {basis: {"rev": x, "np_page": y,
"np_stored": z}}}}. A separate reviewed apply-step merges into sf_revop.json.

Run: python -X utf8 scripts/screener_prerev.py @targets.json   (targets: {sym: {qe: {basis: pat}}})
"""
import json
import os
import sys
import time
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import screener_prefund as SP

HERE = os.path.dirname(os.path.abspath(__file__))
OUTF = os.path.join(HERE, "screener_rev.json")


def fetch_rows(sym, basis):
    """(heads, sales, nps) from the quarters table; 'Revenue' fallback for financial-format pages.
    Returns '429' on rate-limit, None when the page/table is missing."""
    import re

    slug = urllib.parse.quote(sym, safe="")
    t = SP.get("https://www.screener.in/company/{}/{}".format(slug, "consolidated/" if basis == "con" else ""))
    if t == "429":
        return "429"
    m = re.search(r'id="quarters".*?</section>', t, re.DOTALL)
    if not m:
        return None
    sec = m.group(0)
    heads = [SP.qe_of(h) for h in re.findall(r"<th[^>]*>\s*([A-Za-z]{3} \d{4})\s*</th>", sec)]
    sales = SP._row(sec, "Sales") or SP._row(sec, "Revenue")
    nps = SP._row(sec, "Net Profit")
    return heads, sales, nps


def main():
    a = sys.argv[1:]
    targets = json.load(open(a[0][1:])) if (a and a[0].startswith("@")) else {}
    store = json.load(open(OUTF)) if os.path.exists(OUTF) else {}
    skips = []
    consec = 0
    for sym, qmap in targets.items():
        if sym in store:
            continue  # resumable
        got = {}
        for basis in ("std", "con"):
            wanted = {qe: pats[basis] for qe, pats in qmap.items() if pats.get(basis) is not None}
            if not wanted:
                continue
            r = fetch_rows(sym, basis)
            if r == "429":
                print("%-12s 429 — backoff 90s" % sym, flush=True)
                time.sleep(90)
                r = fetch_rows(sym, basis)
                if r == "429":
                    consec += 1
                    if consec >= 4:
                        print("repeated 429 — stopping; rerun to resume", flush=True)
                        json.dump(store, open(OUTF, "w"), indent=0)
                        return
                    r = None
            else:
                consec = 0
            time.sleep(4)
            if not r or r == "429":
                skips.append(f"{sym} {basis}: no page/table")
                continue
            heads, sales, nps = r
            for i, qe in enumerate(heads):
                q = str(qe)
                if q not in wanted or qe is None:
                    continue
                np_page = SP._num(nps[i]) if i < len(nps) else None
                sv = SP._num(sales[i]) if i < len(sales) else None
                stored = wanted[q]
                if np_page is None or sv is None:
                    skips.append(f"{sym} {basis} {q}: missing cell (np={np_page} sales={sv})")
                    continue
                if abs(np_page - stored) > max(0.03 * abs(stored), 2.0):
                    skips.append(f"{sym} {basis} {q}: ANCHOR FAIL page-np={np_page} stored={stored}")
                    continue
                got.setdefault(q, {})[basis] = {"rev": sv, "np_page": np_page, "np_stored": stored}
        if got:
            store[sym] = got
            json.dump(store, open(OUTF, "w"), indent=0)
        print("%-12s staged %d quarter-cells" % (sym, sum(len(v) for v in got.values())), flush=True)
    json.dump(store, open(OUTF, "w"), indent=0)
    print("\n== SKIPS (%d) ==" % len(skips))
    for s in skips:
        print("  " + s)


if __name__ == "__main__":
    main()
