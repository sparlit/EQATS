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
"""Validate BSE candidate values (_bse_text/<SYM>.json) against the bracketing quarters in
docs/sf_fundamentals.json and fill ONLY the high-confidence ones. A value is auto-accepted for
a gap quarter only if (a) it was read from >=2 filings (consensus support) AND (b) it is
plausible vs the nearest present quarter on each side (same sign as a neighbor + magnitude in
a generous band) — this rejects the EPS-row misreads (~0 vs large neighbors) and the
single-filing fliers (e.g. CYIENT 54.6) that would corrupt the screen worse than a gap.

std and con are gated INDEPENDENTLY (the parser sometimes nails con but misreads std). Fill is
fill-only (never overwrites an existing value). Everything that fails the gate is written to
_bse_vision_queue.json for the vision step.

  python -X utf8 merge_bse_gaps.py            # report only (dry)
  python -X utf8 merge_bse_gaps.py --apply    # fill accepted into docs/sf_fundamentals.json
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DOCS = os.path.join(os.path.dirname(HERE), "docs", "sf_fundamentals.json")
OUTF = os.path.join(HERE, "fundamentals.json")
work = json.load(open(os.path.join(HERE, "_gap_work.json")))
data = json.load(open(DOCS))


def neighbors(arr, qe, idx):
    """nearest present value (col idx: 1=std,3=con) strictly before and after qe."""
    prev = nxt = None
    for r in arr:
        if r[idx] is None:
            continue
        if r[0] < qe and (prev is None or r[0] > prev[0]):
            prev = (r[0], r[idx])
        if r[0] > qe and (nxt is None or r[0] < nxt[0]):
            nxt = (r[0], r[idx])
    return (prev[1] if prev else None), (nxt[1] if nxt else None)


def plausible(v, prev, nxt):
    if v is None:
        return False
    ns = [x for x in (prev, nxt) if x is not None]
    if not ns:
        return False
    mag = [abs(x) for x in ns]
    lo, hi = min(mag), max(mag)
    if abs(v) < max(lo * 0.25, 0.5):  # ~0 vs large neighbor -> EPS misread
        return False
    if abs(v) > hi * 4 + 5:  # wild over-read
        return False
    # sign: v must share sign with at least one neighbor (allow tiny neighbors)
    if not any((v >= 0) == (x >= 0) or abs(x) < 1 for x in ns):
        return False
    return True


def main():
    apply = "--apply" in sys.argv
    fill = []
    vision = []
    nodata = []
    for sym in sorted(work):
        bf = os.path.join(HERE, "_bse_text", f"{sym}.json")
        cand = {r[0]: r for r in json.load(open(bf))} if os.path.exists(bf) else {}
        arr = data[sym]
        for qe in work[sym]:
            r = cand.get(qe)
            sp, sn = neighbors(arr, qe, 1)
            cp, cn = neighbors(arr, qe, 3)
            if not r:
                nodata.append((sym, qe, "no BSE filing", cp, cn))
                continue
            std, con = r[1], r[2]
            ssup = r[4][0] if len(r) > 4 else 0
            csup = r[5][0] if len(r) > 5 else 0
            con_ok = con is not None and csup >= 2 and plausible(con, cp, cn)
            std_ok = std is not None and ssup >= 2 and plausible(std, sp, sn)
            # cross-check: a company's standalone & consolidated profit share sign in the same
            # quarter; opposite signs => one is a wrong-row read (e.g. IOC std=-1992 vs con=+883)
            if con_ok and std_ok and min(abs(std), abs(con)) > 5 and (std >= 0) != (con >= 0):
                con_ok = std_ok = False

            # high-magnitude guard: >3x the larger neighbor => likely a half-year/YTD or wrong row
            def hot(v, p, q):
                ns = [abs(x) for x in (p, q) if x is not None]
                return bool(ns) and abs(v) > 3 * max(ns)

            if con_ok and hot(con, cp, cn):
                con_ok = False
            if std_ok and hot(std, sp, sn):
                std_ok = False
            if con_ok or std_ok:
                fill.append((sym, qe, std if std_ok else None, con if con_ok else None, r[3], std, con, csup, cp, cn))
            else:
                vision.append((sym, qe, std, con, csup, cp, cn))
    print("AUTO-FILL (passed gate): %d   VISION-NEEDED: %d   NO-BSE-DATA: %d" % (len(fill), len(vision), len(nodata)))
    print("\n-- AUTO-FILL sample --")
    for f in fill[:30]:
        print("  %-12s %d  std=%s con=%s  (csup=%s, conNbrs %s/%s)" % (f[0], f[1], f[2], f[3], f[7], f[8], f[9]))
    print("\n-- VISION-NEEDED sample --")
    for v in vision[:30]:
        print("  %-12s %d  bse std=%s con=%s csup=%s  conNbrs %s/%s" % (v[0], v[1], v[2], v[3], v[4], v[5], v[6]))
    json.dump([(s, q, std, con) for s, q, std, con, *_ in fill], open(os.path.join(HERE, "_bse_fill.json"), "w"))
    json.dump([(s, q) for s, q, *_ in vision], open(os.path.join(HERE, "_bse_vision_queue.json"), "w"))
    json.dump([(s, q) for s, q, *_ in nodata], open(os.path.join(HERE, "_bse_nodata.json"), "w"))

    if apply:
        n = 0
        for sym, qe, std, con, ann, *_ in fill:
            by = {r[0]: r for r in data[sym]}
            row = by.get(qe) or [qe, None, None, None, None]
            if std is not None and row[1] is None:
                row[1], row[2] = std, ann or None
            if con is not None and row[3] is None:
                row[3], row[4] = con, ann or None
            by[qe] = row
            data[sym] = [by[k] for k in sorted(by)]
            n += 1
        json.dump(data, open(DOCS, "w"), separators=(",", ":"))
        json.dump(data, open(OUTF, "w"), separators=(",", ":"))
        print("\nAPPLIED %d quarter-fills to docs/sf_fundamentals.json" % n)


if __name__ == "__main__":
    main()
