# -*- coding: utf-8 -*-
"""FILL-2020 rev track: POST-2020 standalone revenue via the BSE detailed-results JSON (§42).

Thin driver over fill_std_rev_detres.check() — the sibling session built that gate for the
2015-2019 window and it is not year-limited: §42's quarter id space runs 2015 -> today, and the
landing rule is the same one. Reusing the function rather than copying it means one gate, one place.

THE GATE (fill_std_rev_detres's docstring, in one line): revenue has no anchor of its own — it IS
the gap — but the same detres row prints Net Profit, and we hold standalone PAT for these quarters
(that is precisely why they are revenue-only gaps), so the page's NP/10 must match our stored std
PAT within max(2cr, 3%) before its revenue is read.

Scope: the revS list of _rev2020_targets.json (quarters 20200331..20260331). Standalone only —
§42 has no working consolidated endpoint, so con gaps are out of reach here by construction.

Writes revenue only (slot 0). Operating profit is left alone: it is a reconstruction from expense
components and a wrong OPM is a visible site bug.

Run:  python -X utf8 scripts/fill2020_tools/fill_rev_detres_post2020.py [--apply] [--only SYM,SYM]
"""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, HERE)

import fill_std_rev_detres as D          # noqa: E402  — one gate, one implementation

TARGETS = os.path.join(HERE, "_rev2020_targets.json")
LEDGER = os.path.join(SCRIPTS, "post2020_rev_detres_fills.json")
SKIPS = os.path.join(SCRIPTS, "_post2020_rev_detres_skips.json")


def main():
    argv = sys.argv
    apply_it = "--apply" in argv
    only = set(argv[argv.index("--only") + 1].split(",")) if "--only" in argv else None

    targets = json.load(open(TARGETS))
    revop = json.load(open(D.REVOP_DOCS))
    ledger = json.load(open(D.REVOP_SCR))
    fund = json.load(open(D.FUND))
    fmap = {s: {r[0]: r for r in rows} for s, rows in fund.items()}
    codes = json.load(open(D.SCRIPS))["by_id"]
    fills = json.load(open(LEDGER)) if os.path.exists(LEDGER) else {}
    skips = json.load(open(SKIPS)) if os.path.exists(SKIPS) else {}

    syms = [s for s in sorted(targets) if targets[s]["revS"]]
    if only:
        syms = [s for s in syms if s in only]

    nread = 0
    for si, sym in enumerate(syms, 1):
        scrip = D.SCRIP_OVERRIDE.get(sym) or codes.get(sym)
        if not scrip:
            skips["%s|code" % sym] = "no BSE scrip code"
            continue
        for qe in sorted(targets[sym]["revS"]):
            key = "%s|%d" % (sym, qe)
            if key in fills:
                continue
            stored_pat = (fmap.get(sym, {}).get(qe) or [None, None])[1]
            if stored_pat is None:
                skips[key] = "no stored std PAT to anchor against"
                continue
            try:
                rev, note = D.check(str(scrip), qe, stored_pat)
            except Exception as e:
                skips[key] = "fetch-%s" % type(e).__name__
                time.sleep(2.0)
                continue
            if rev is None:
                skips[key] = note
            else:
                fills[key] = {"rev": rev, "basis": "std", "stored_pat": stored_pat,
                              "src": "BSE detres %s qtr %s" % (scrip, D.qid(qe)), "gate": note}
                nread += 1
                print("%-13s %d std rev %-12.2f (%s)" % (sym, qe, rev, note), flush=True)
            time.sleep(0.7)             # BSE rate-limits hard; a 162-byte body is the stub (§0)
        if si % 20 == 0:
            json.dump(fills, open(LEDGER, "w"), indent=1, sort_keys=True)
            json.dump(skips, open(SKIPS, "w"), indent=0, sort_keys=True)
            print("  [%d/%d] %d read" % (si, len(syms), nread), flush=True)

    json.dump(fills, open(LEDGER, "w"), indent=1, sort_keys=True)
    json.dump(skips, open(SKIPS, "w"), indent=0, sort_keys=True)
    print("\nREAD %d this run (%d ledgered), %d refused" % (nread, len(fills), len(skips)))

    if not apply_it:
        print("(dry run — ledgers written, data files untouched)")
        return

    applied = 0
    for key, v in sorted(fills.items()):
        sym, qe_s = key.split("|")
        row = (revop.get(sym) or {}).get(qe_s)
        if row is None or row[0] is not None:        # fill-only
            continue
        row[0] = v["rev"]
        applied += 1
        lrow = ledger.setdefault(sym, {}).get(qe_s)
        if lrow is None:
            ledger[sym][qe_s] = list(row)
        elif lrow[0] is None:
            lrow[0] = v["rev"]
    json.dump(revop, open(D.REVOP_DOCS, "w"), separators=(",", ":"))
    json.dump(ledger, open(D.REVOP_SCR, "w"), separators=(",", ":"))
    print("APPLIED %d standalone revenue cells" % applied)


if __name__ == "__main__":
    main()
