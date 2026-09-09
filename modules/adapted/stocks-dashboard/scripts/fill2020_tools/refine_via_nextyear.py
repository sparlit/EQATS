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
"""Recover a Mar-YYYY figure at filing precision from the Mar-(YYYY+1) filing's comparative column.

Route ladder rung 6 (§57), made reliable by rung 3b: every quarter is printed in ~3 filings (its
own, the next quarter's, and the same quarter NEXT YEAR as the comparative). When the own-quarter
PDF is image-only or labelled unexpectedly, the next-YEAR filing still prints the number in plain
text -- and because screener has already told us the value to +-1 crore, we can identify the right
cell without ever guessing a column index.

  python -X utf8 scripts/fill2020_tools/refine_via_nextyear.py
"""
import datetime
import importlib.util
import json
import os
import sys
import time

WT = os.path.expanduser("~/stocks-wt/fill2020")
sys.path.insert(0, os.path.join(WT, "scripts"))
sys.path.insert(0, os.path.join(WT, "scripts", "fill2020_tools"))
os.chdir(WT)
import fetch_insurers as FI  # noqa: E402
import fitz  # noqa: E402
from refine_from_filing import hunt  # noqa: E402

_s = importlib.util.spec_from_file_location("brg", os.path.join(WT, "scripts", "backfill_revop_gaps.py"))
BRG = importlib.util.module_from_spec(_s)
_s.loader.exec_module(BRG)

# sym -> (bse scrip, screener crore-rounded target for 2025-03-31 consolidated revenue)
TARGETS = {
    "CGPOWER": (500093, 2753.0),
    "CYIENT": (532175, 1909.0),
    "NMDC": (526371, 7005.0),
    "WAAREEENER": (544277, 4004.0),
    "MCX": (534091, 291.0),
}
WIN = ("20260410", "20260630")  # Mar-2026 results season


def main():
    out = {}
    for sym, (scrip, target) in sorted(TARGETS.items()):
        sess = FI.bse_session()
        fils = FI.datebound(sess, str(scrip), *WIN) or []
        hit = None
        for _annd, att, _sub in fils[:8]:
            raw, _ = BRG.cached_pdf(sess, att)
            if not raw:
                continue
            try:
                doc = fitz.open(stream=raw, filetype="pdf")
            except Exception:
                continue
            hit = hunt(doc, target)
            doc.close()
            if hit:
                break
        if hit:
            out[sym] = {"value": hit[1], "where": hit[2], "target": target}
            print("  %-11s = %-9s EXACT  %s" % (sym, hit[1], hit[2]))
        else:
            print("  %-11s not located in %d Mar-2026 filings" % (sym, len(fils)))
        time.sleep(0.5)
    json.dump(out, open("/tmp/nextyear.json", "w"), indent=1)
    print("\nexact from next-year comparative: %d of %d" % (len(out), len(TARGETS)))


if __name__ == "__main__":
    main()
