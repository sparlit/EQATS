# -*- coding: utf-8 -*-
"""FILL-2020 con-PAT: DIAGNOSTIC dump of the 37 refusals in scripts/con_pat_nse_reads.json.

Writes nothing. For each refused (sym, qe) it re-fetches the page recorded in the inventory and
prints the meta block plus every row whose label mentions profit / minority / associate / EPS /
equity / face value, so a refusal can be triaged instead of accepted untriaged (runbook §0).

Run:  python3 -X utf8 scripts/fill2020_tools/diag_con_pat_refusals.py [--class TAG] [--only SYM]
      TAG in {owners, basis, sprime, eps, blank, all}
"""
import importlib.util
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, SCRIPTS)

_spec = importlib.util.spec_from_file_location("nar", os.path.join(SCRIPTS, "_nse_archive_revop.py"))
NAR = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(NAR)
NAR.JAR = NAR.BF.nse_jar()

INV = os.path.join(HERE, "_con_nse_inventory.json")
READS = os.path.join(SCRIPTS, "con_pat_nse_reads.json")
CACHE = os.path.join(SCRIPTS, "_nsearch_cache")
DOCS = os.path.join(ROOT, "docs", "sf_fundamentals.json")

R_INTEREST = re.compile(r"profit|loss|minority|associat|earning per|face value|equity|revenue|"
                        r"income from operations|interest earned|tax", re.I)

CLASSES = {"owners": "no-owners-row", "basis": "basis-mismatch", "sprime": "S'-mismatch",
           "eps": "E-recon failed", "blank": "blank-template"}


def classify(v):
    s = v.get("skip") or ""
    for tag, needle in CLASSES.items():
        if needle in s:
            return tag
    return "other" if s else "filled"


def main():
    args = sys.argv[1:]
    want = args[args.index("--class") + 1] if "--class" in args else "all"
    only = set(args[args.index("--only") + 1].split(",")) if "--only" in args else None
    reads = json.load(open(READS))
    inv = json.load(open(INV))
    fund = json.load(open(DOCS))
    os.makedirs(CACHE, exist_ok=True)

    work = []
    for k, v in sorted(reads.items()):
        cls = classify(v)
        if cls in ("filled",):
            continue
        if want != "all" and cls != want:
            continue
        sym, qe = k.split("|")
        if only and sym not in only:
            continue
        work.append((sym, int(qe), cls, v))
    print("refusals to diagnose: %d\n" % len(work), flush=True)

    for sym, qe, cls, v in work:
        link = (inv.get(sym, {}).get("qtr") or {}).get(str(qe))
        row = {r[0]: r for r in fund.get(sym, [])}.get(qe)
        stored_std = row[1] if row else None
        stored_con = row[3] if row and len(row) > 3 else None
        print("=" * 100)
        print("%-12s %d  [%s]  skip=%s" % (sym, qe, cls, v.get("skip")))
        print("   stored std=%s con=%s   link=%s" % (stored_std, stored_con, link))
        if not link:
            print("   NO LINK IN INVENTORY")
            continue
        path = os.path.join(CACHE, "diag_%s_%d_c.html" % (sym.replace("&", "_"), qe))
        try:
            html = NAR.get_detail(link, sym, path)
        except Exception as ex:
            print("   FETCH FAIL %s" % type(ex).__name__)
            continue
        meta, rows = NAR.parse_detail(html)
        m = re.search(r"Cumulative\s*/\s*Non-?Cumulative\s*\|?\s*(Non-?Cumulative|Cumulative)", html, re.I)
        print("   meta: basis=%r period=%r symbol=%r unit=%r div=%s cumul=%r fmt=%r" % (
            meta.get("Consolidated / Non-Consolidated"), meta.get("Period Ended"),
            meta.get("Symbol"), meta.get("unit"), meta.get("div"),
            m.group(1) if m else None, meta.get("fmt")))
        for lab, val in rows:
            if R_INTEREST.search(lab):
                print("      %-78s %12.4f" % (lab[:78], val))
        time.sleep(0.7)
        print()


if __name__ == "__main__":
    main()
