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
"""The CONSOLIDATED bottom line on NSE's archive pages — components, and which sign is right.

Measured on the cached pages (no fetch). The archive prints, per consolidated page:
    Net Profit / (Loss) for the period                                        P
    Share of profit / (loss) of associates                                    A
    Minority interest                                                         M
    Net Profit / (Loss) after taxes, minority interest and share of ...       B   <- what we read

B is NOT reliably P + A - M. BAJAJHLDNG Mar-2016: P=92.64, A=+471.14, M=0 and the page prints
B = -378.50 = P - A, while the store and MC both hold 563.78 = P + A (Bajaj Holdings' consolidated
profit IS its associate share; a -378 cr quarter never happened). ASHOKA Dec-2015: P=-2.8116,
A=-6.3281, M=+22.3999, page B=-31.5396, store/MC 13.2602 = P + M + A.

So this pass reports, per page, WHICH combination reproduces the store — the sign convention is
established from the arithmetic, not assumed.  OUT: _vintage109_con_comp.json
"""
import json
import os
import re
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import _nse_archive_revop as NA  # noqa: E402

PAGES = os.path.join(HERE, "_vintage108_nse_pages")
R = {
    "period": re.compile(r"net profit\s*/?\s*\(?loss\)?\s+for the period", re.IGNORECASE),
    "ordinary": re.compile(r"net profit\s*/?\s*\(?loss\)?\s+from ordinary activities after tax", re.IGNORECASE),
    "assoc": re.compile(r"share of profit\s*/?\s*\(?loss\)?\s+of associat", re.IGNORECASE),
    "minority": re.compile(
        r"^minority interest$|^less\s*:?\s*minority interest|non-controlling interest", re.IGNORECASE
    ),
    "bottom": re.compile(r"net profit\s*/?\s*\(?loss\)?\s+after taxes,? minority", re.IGNORECASE),
}


def rows_of(seq_file):
    meta, rows = NA.parse_detail(open(seq_file, encoding="utf-8", errors="replace").read())
    got = {}
    for name, p in R.items():
        for lab, v in rows:
            if p.search(lab.strip()):
                got.setdefault(name, v)
                break
    got["_basis"] = meta.get("Consolidated / Non-Consolidated")
    return got


def main():
    idx = {}
    for fn in os.listdir(PAGES):
        m = re.match(r"financial_res_(.+)_(\d+)\.html$", fn)
        if m:
            idx[m.group(2)] = os.path.join(PAGES, fn)
    b = json.load(open(os.path.join(HERE, "_vintage109_byprod.json")))["cells"]
    con = {k: r for k, r in b.items() if r["basis"] == "con"}
    print("con by-product cells: %d" % len(con))
    out, cnt = {}, Counter()
    for k, r in sorted(con.items()):
        f = idx.get(str(r["nse_seq"]))
        if not f:
            cnt["page-not-cached"] += 1
            continue
        g = rows_of(f)
        P = g.get("period", g.get("ordinary"))
        A, M, B = g.get("assoc"), g.get("minority"), g.get("bottom")
        st = r["stored"]
        mc = r.get("mc") or {}
        cand = {"P": P, "B": B}
        if P is not None:
            if A is not None:
                cand["P+A"] = P + A
                cand["P-A"] = P - A
            if M is not None:
                cand["P-M"] = P - M
                cand["P+M"] = P + M
            if A is not None and M is not None:
                cand["P+A-M"] = P + A - M
                cand["P+A+M"] = P + A + M
                cand["P-A-M"] = P - A - M
        hit = [nm for nm, v in cand.items() if v is not None and abs(v - st) <= max(0.35, abs(st) * 0.005)]
        out[k] = {
            "P": P,
            "A": A,
            "M": M,
            "B": B,
            "stored": st,
            "mc_own": mc.get("pat_own"),
            "mc_total": mc.get("pat_total"),
            "reproduces_store": hit,
        }
        cnt["store == " + (hit[0] if hit else "NONE of the combinations")] += 1
    print("\nWhich combination of the page's own rows reproduces the STORED value?")
    for kk, n in cnt.most_common():
        print("   %-46s %d" % (kk, n))
    json.dump({"cells": out}, open(os.path.join(HERE, "_vintage109_con_comp.json"), "w"), indent=1)
    print("\nwrote _vintage109_con_comp.json")


if __name__ == "__main__":
    main()
