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
"""Second pass over the NSE archived-HTML pages the main tool skipped as `no-rev-row`.

WHY they are not missing values. The pre-~2012 NSE archive layout has a different row
vocabulary: there is often no "Net sales/income from operations" line at all, and the top line
is "Other Operating Income" — or the revenue row is simply not printed when it is nil. Reading
that as "no revenue row" throws away cells the page can still answer, because the old layout
prints an identity that pins revenue exactly:

    Profit from Operations before Other Income, Interest & Exceptional Items
        = Revenue − Total Expenditure

so  rev = TotalExpenditure + ProfitFromOps.  Measured on ORISSAMINE 2011-09-30: 15.0543 +
(−13.3329) = 1.7214, which reproduces that page's printed "Other Operating Income" to the
paisa — the derivation is self-checking wherever such a row exists.

GATES (a cell is written only if all pass):
  1. PAT anchor — the page's PAT must equal the stored sf_fundamentals PAT for (sym,qe,basis),
     same tolerance as the main tool. A misparse fails the anchor instead of corrupting data.
  2. Both identity rows present. No guessing from one of them.
  3. Cross-check when the page prints any revenue-ish row (Other Operating Income / Net Sales /
     Total Income from Operations): the derived value must reproduce it within 1 paisa, else the
     cell is SKIPPED as `identity-vs-printed-mismatch` (the identity is then not describing what
     we think it is).
  4. A derived value of exactly 0.00 is NOT written here. It is a real possibility (a filer with
     no operating revenue that quarter) but it is also what a missing row looks like after the
     arithmetic, and the two are indistinguishable from this page alone — they go to
     `_nsearch_oldfmt_zeros.json` for a second source to adjudicate. (§0: record `unknown`
     rather than bridge the gap.)

Output: scripts/_nsearch_reads_oldfmt.json, in the same shape _apply_reads.py already globs
(`_nsearch_reads_*.json`), so the write path and its re-anchor are unchanged.

Run: python -X utf8 scripts/_nsearch_oldfmt_rev.py --gaps scripts/_gaps_n500_stdfill.json
"""
import contextlib
import importlib.util
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

_spec = importlib.util.spec_from_file_location("nar", os.path.join(HERE, "_nse_archive_revop.py"))
M = importlib.util.module_from_spec(_spec)
with contextlib.suppress(SystemExit):
    _spec.loader.exec_module(M)

OUT = os.path.join(HERE, "_nsearch_reads_oldfmt.json")
ZEROS = os.path.join(HERE, "_nsearch_oldfmt_zeros.json")
SKIPS = os.path.join(HERE, "_nsearch_oldfmt_skips.json")

R_TOTEXP = re.compile(r"^total expenditure$|^total expenses$", re.IGNORECASE)
# The "/(Loss)" half is OPTIONAL — the 2011-12 layout prints a bare "Profit from Operations
# before Other Income, Interest & Exceptional Items". Making it mandatory (the main tool's
# R_OP_IND still does) silently loses every pre-2013 page: measured on ORISSAMINE, 2 of 8 cells.
R_OPBEFORE = re.compile(
    r"profit\s*(?:\(\+\))?\s*(?:/?\s*\(?loss\)?\s*(?:\(-\))?\s*)?from operations before other income", re.IGNORECASE
)
# Any row that states revenue directly, for the cross-check. ORDER MATTERS: pick() returns the
# FIRST pattern that matches, so the TOTAL must be tried before its components. The (a) net-sales
# and (b) other-operating-income lines sum to "Total income from operations (net) (a+b)"; matching
# (a) first compares the derivation against a sub-line and the gate fires on a correct read —
# measured, it rejected 5 sound DBREALTY/ORBITCORP cells (printed 0.0000 = the (a) row alone).
R_REVISH = (
    re.compile(r"total income from operations", re.IGNORECASE),
    re.compile(r"^revenue from operations?\b", re.IGNORECASE),
    re.compile(r"net sales\s*/\s*income from operations?", re.IGNORECASE),
    re.compile(r"^other operating income$", re.IGNORECASE),
)


def main():
    argv = sys.argv
    gapf = argv[argv.index("--gaps") + 1] if "--gaps" in argv else os.path.join(HERE, "_gaps_n500_stdfill.json")
    only = set(argv[argv.index("--only") + 1].split(",")) if "--only" in argv else None
    gaps = json.load(open(gapf))
    fund = json.load(open(os.path.join(ROOT, "docs", "sf_fundamentals.json")))
    fmap = {s: {r[0]: r for r in rows} for s, rows in fund.items()}
    prior = json.load(open(os.path.join(HERE, "_nsearch_skips.json")))

    # only the cells the main pass refused with no-rev-row, and only on the std side
    todo = {}
    for k, v in prior.items():
        p = k.split("|")
        if len(p) < 3 or p[2] != "std" or not v.startswith("no-rev-row"):
            continue
        sym, qe = p[0], int(p[1])
        if only and sym not in only:
            continue
        if str(qe) in [str(x) for x in gaps.get(sym, [])]:
            todo.setdefault(sym, set()).add(qe)
    print("cells to retry: %d across %d syms" % (sum(len(v) for v in todo.values()), len(todo)), flush=True)

    M.JAR = M.BF.nse_jar()
    out = json.load(open(OUT)) if os.path.exists(OUT) else {}
    zeros = json.load(open(ZEROS)) if os.path.exists(ZEROS) else {}
    skips = {}
    nfill = 0
    for sym in sorted(todo):
        try:
            rows = M.list_rows(sym)
        except Exception:
            skips[f"{sym}|list"] = "list-fetch-failed"
            continue
        for r in rows:
            qe = M.iso_qe(r.get("toDate"))
            if qe not in todo[sym] or not r.get("resultDetailedDataLink"):
                continue
            if "Non" not in (r.get("consolidated") or "Non"):
                continue  # std rows only
            link = r["resultDetailedDataLink"]
            dp = os.path.join(M.CACHE, re.sub(r"[^A-Za-z0-9_.]", "_", link.rsplit("/", 1)[-1]))
            try:
                html = M.get_detail(link, sym, dp)
            except Exception:
                skips["%s|%d" % (sym, qe)] = "detail-fetch-failed"
                continue
            meta, prows = M.parse_detail(html)
            if "Non" not in (meta.get("Consolidated / Non-Consolidated") or "Non"):
                continue
            key = "%s|%d" % (sym, qe)
            frow = fmap.get(sym, {}).get(qe)
            if not frow:
                skips[key] = "no-stored-pat-row"
                continue
            stored = frow[1]
            pat = M.pick(prows, M.R_PAT_OWN) if meta.get("fmt") != "Banking" else None
            pat2 = M.pick(prows, M.R_PAT_ANY)
            hit = next((c for c in (pat, pat2) if M.close(c, stored)), None)
            if hit is None:
                skips[key] = f"pat-anchor {pat2} vs stored {stored}"
                continue
            totexp = M.pick(prows, R_TOTEXP)
            opbef = M.pick(prows, R_OPBEFORE)
            if totexp is None or opbef is None:
                skips[key] = f"identity-rows-absent (totexp={totexp} opbefore={opbef})"
                continue
            rev = round(totexp + opbef, 4)
            printed = M.pick(prows, *R_REVISH)
            if printed is not None and abs(printed - rev) > 0.01:
                skips[key] = f"identity-vs-printed-mismatch derived={rev:.4f} printed={printed:.4f}"
                continue
            if abs(rev) < 0.005:
                zeros[key] = {
                    "derived": rev,
                    "pat_seen": round(hit, 2),
                    "totexp": totexp,
                    "op_before": opbef,
                    "printed_rev_row": printed,
                    "src": "nse-archive {} ({})".format(link.rsplit("/", 1)[-1], meta.get("unit", "lakhs")),
                }
                continue
            out.setdefault(sym, {})[str(qe)] = {
                "rev": rev,
                "op": None if opbef == 0.0 else round(opbef, 2),
                "pat_seen": round(hit, 2),
                "basis": "std",
                "fin": 0,
                "src": "nse-archive OLD-FORMAT identity rev=totexp+opbefore {} ({}, {}){}".format(
                    link.rsplit("/", 1)[-1],
                    meta.get("unit", "lakhs"),
                    meta.get("fmt", "?"),
                    "" if printed is None else f"; cross-checks printed row {printed:.4f}",
                ),
            }
            nfill += 1
            print(
                "%-12s %d std -> rev %.4f (anchor %.2f)%s"
                % (sym, qe, rev, hit, "" if printed is None else " [xcheck ok]"),
                flush=True,
            )
    json.dump(out, open(OUT, "w"), indent=1, sort_keys=True)
    json.dump(zeros, open(ZEROS, "w"), indent=1, sort_keys=True)
    json.dump(skips, open(SKIPS, "w"), indent=1, sort_keys=True)
    print("DONE: %d cells filled, %d parked as derived-zero, %d skipped" % (nfill, len(zeros), len(skips)), flush=True)


if __name__ == "__main__":
    main()
