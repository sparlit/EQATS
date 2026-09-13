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
"""Bulk BSE fundamentals fetch for stocks missing from docs/sf_fundamentals.json. Reads
_bse_missing.json (built from BSE's active-equity list, >=100cr, sorted by mcap), and for each
stock pulls quarterly net profit from the BSE filing PDF text layer (no OCR) using bse_text's
parser + consensus. Resumable. Run: python bse_bulk.py LO HI
Writes _bse_bulk/<LO>_<HI>.json = {sym: [[qe, std, con, ann], ...]}
"""
import json
import os
import sys
import time

import bse_text as T
import bse_vision as V

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "_bse_bulk")
os.makedirs(OUT, exist_ok=True)
MISS = json.load(open(os.path.join(HERE, "_bse_missing.json")))


def fetch_pdf(o, att):
    for base in ("AttachHis", "AttachLive"):
        try:
            d = V.get(o, f"https://www.bseindia.com/xml-data/corpfiling/{base}/{att}", b=True)
            if d[:4] == b"%PDF":
                return d
        except Exception:
            continue
    return None


def main():
    lo, hi = int(sys.argv[1]), int(sys.argv[2])
    stocks = MISS[lo:hi]
    outf = os.path.join(OUT, "%d_%d.json" % (lo, hi))
    res = json.load(open(outf)) if os.path.exists(outf) else {}
    o = V.session()
    for i, st in enumerate(stocks):
        sym = st["sym"]
        if sym in res:
            continue
        try:
            fl = V.filings(o, st["code"], pages=30, since="20170101")
            obs = {}
            anns = {}
            for ann, att in sorted(fl):
                pdf = fetch_pdf(o, att)
                if not pdf:
                    continue
                try:
                    r = T.parse_pdf(pdf, ann)
                except Exception:
                    r = None
                if not r:
                    continue
                std_c, con_c, _ = r
                qe = T.qe_from_ann(ann)
                anns[qe] = min(ann, anns.get(qe, ann))
                for basis, cols in (("s", std_c), ("c", con_c)):
                    if not cols:
                        continue
                    qmap = [qe, T.prev_q(qe), qe - 10000]
                    for ci, val in enumerate(cols[:3]):
                        if qmap[ci]:
                            obs.setdefault((qmap[ci], basis), []).append(val)
                time.sleep(0.2)
            arr = []
            for qe in sorted({q for q, b in obs}):
                sv, _, _ = T.consensus(obs.get((qe, "s"), []))
                cv, _, _ = T.consensus(obs.get((qe, "c"), []))
                arr.append([qe, sv, cv, anns.get(qe, 0)])
            res[sym] = arr
            print("  [%d/%d] %-12s %d quarters" % (lo + i + 1, lo + len(stocks), sym, len(arr)), flush=True)
        except Exception as e:
            print("  %-12s ERR %s" % (sym, type(e).__name__), flush=True)
            res[sym] = []
        json.dump(res, open(outf, "w"))
    filled = sum(1 for v in res.values() if v)
    print("BATCH %d-%d DONE: %d stocks (%d with data)" % (lo, hi, len(res), filled), flush=True)


if __name__ == "__main__":
    main()
