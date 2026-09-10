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
"""OFFLINE re-extraction of every cached NSE detail page, with the PAT-row defect fixed.

THE DEFECT (found 2026-08-24, GRINDWELL Dec-2016). `vintage108_nse_vintages.PAT_ROWS` is an
ORDERED tuple and takes the FIRST pattern that matches any row:

    1. "net profit /(loss) after taxes, minority interest and share of profit..."
    2. "net profit /(loss) for the period"
    3. "net profit /(loss) from ordinary activities after tax"

On a STANDALONE filing there is no minority interest, so the exchange's template prints row 1 as a
bare `0` while rows 2 and 3 carry the real figure. GRINDWELL Dec-2016 prints
`... after tax 2659.00 / for the period 2659.00 / after taxes, minority ... 0` and the reader
returned **0.0** — the §59d rule "owners and NCI both tagged 0.00 does not mean zero profit", and
the falsy-sentinel rule, in one row.

CORRECTED RULE: read EVERY candidate row, then pick the minority-adjusted bottom line ONLY when it
is populated (non-zero, or the only row there is); otherwise fall to "for the period" / "ordinary
activities after tax". A 0 in the minority row while another PAT row is materially non-zero is a
blank template, not a result.

Nothing is fetched: the ~10k pages under _vintage108_nse_pages are read from disk.
OUT: _vintage109_pat_rows.json  {seq: {rows: {...}, pat_old, pat_new, unit, div, basis, period}}
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
OUT = os.path.join(HERE, "_vintage109_pat_rows.json")
P_MINORITY = re.compile(r"net profit\s*/?\s*\(?loss\)?\s+after taxes,? minority", re.IGNORECASE)
P_PERIOD = re.compile(r"net profit\s*/?\s*\(?loss\)?\s+for the period", re.IGNORECASE)
P_ORD = re.compile(r"net profit\s*/?\s*\(?loss\)?\s+from ordinary activities after tax", re.IGNORECASE)
OLD_ORDER = (P_MINORITY, P_PERIOD, P_ORD)


def pat_old(rows):
    for p in OLD_ORDER:
        for lab, v in rows:
            if p.search(lab.strip()):
                return v, lab.strip()[:70]
    return None, None


def pat_new(rows):
    """-> (value, label, note). Minority-adjusted line wins only when POPULATED."""
    got = {}
    for name, p in (("minority", P_MINORITY), ("period", P_PERIOD), ("ordinary", P_ORD)):
        for lab, v in rows:
            if p.search(lab.strip()):
                got.setdefault(name, (v, lab.strip()[:70]))
                break
    others = [v for k, (v, _) in got.items() if k != "minority"]
    if "minority" in got:
        mv = got["minority"][0]
        if abs(mv) > 0.0049 or not others or all(abs(o) <= 0.0049 for o in others):
            return got["minority"][0], got["minority"][1], "minority"
        # a 0 minority row beside a populated PAT row = blank template
        for k in ("period", "ordinary"):
            if k in got and abs(got[k][0]) > 0.0049:
                return got[k][0], got[k][1], f"minority-row-blank->{k}"
    for k in ("period", "ordinary"):
        if k in got:
            return got[k][0], got[k][1], k
    return None, None, "none"


def main():
    files = sorted(f for f in os.listdir(PAGES) if f.endswith(".html"))
    print("cached NSE detail pages: %d" % len(files))
    out, notes, diff = {}, Counter(), []
    for _i, fn in enumerate(files):
        m = re.match(r"financial_res_(.+)_(\d+)\.html$", fn)
        if not m:
            continue
        sym, seq = m.group(1), m.group(2)
        try:
            h = open(os.path.join(PAGES, fn), encoding="utf-8", errors="replace").read()
            meta, rows = NA.parse_detail(h)
        except Exception:
            notes["parse-error"] += 1
            continue
        po, _lo = pat_old(rows)
        pn, ln, note = pat_new(rows)
        notes[note] += 1
        rec = {
            "sym": sym,
            "seq": seq,
            "unit": meta.get("unit"),
            "div": meta.get("div"),
            "basis": meta.get("Consolidated / Non-Consolidated"),
            "period": meta.get("Period Ended"),
            "pat_old": po,
            "pat_new": pn,
            "row_new": ln,
            "note": note,
        }
        out[seq] = rec
        if (po is None) != (pn is None) or (po is not None and pn is not None and abs(po - pn) > 0.005):
            diff.append(rec)
    print(f"\nrow chosen: {dict(notes)}")
    print("pages where the corrected rule changes PAT: %d" % len(diff))
    for r in diff[:12]:
        print(
            "   %-14s seq %-9s %s  old=%-10s new=%-10s (%s)"
            % (r["sym"], r["seq"], r["period"], r["pat_old"], r["pat_new"], r["note"])
        )
    json.dump({"_doc": "corrected PAT-row extraction of the cached NSE pages", "pages": out}, open(OUT, "w"), indent=1)
    print(f"\nwrote {os.path.basename(OUT)}")


if __name__ == "__main__":
    main()
