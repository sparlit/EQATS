# -*- coding: utf-8 -*-
"""Null CONSOLIDATED cells that are a COPY of standalone for companies that stopped filing con.

THE DEFECT (root cause fixed in build_fundamentals.is_con_basis, 2026-08-06). NSE's `consolidated`
field has exactly two values, "Consolidated" and "Non-Consolidated" -- and `"consol" in
"non-consolidated"` is TRUE. When a filing's XBRL omitted the NatureOfReportStandaloneConsolidated
tag, the parser fell back to that label, classified a STANDALONE filing as consolidated, and wrote
its profit into the con slot. The daily upsert is fill-only, so the fabricated value stuck.

Found because the user checked screener.in and asked how we could hold consolidated PAT for 3MINDIA
when it stopped filing consolidated after Jun-2024. Wrong data is worse than missing data.

THIS SCRIPT PURGES ONLY WHAT IS INDEPENDENTLY CONFIRMED. For every company below, the NSE results
archive was queried directly: EVERY filing from the run-start onward is Non-Consolidated and there
are ZERO Consolidated filings. Their stored con is therefore not a filing at all.

    company     last real con filed     copied run          NSE rows after / con among them
    RALLIS      2022-03                 2022-06 ->          11 / 0
    ABB         2022-03                 2022-09 ->          10 / 0
    CAMPUS      2022-03                 2022-09 ->          11 / 0
    RAILTEL     2023-06                 2023-09 ->           6 / 0
    JTEKTINDIA  2023-09                 2023-12 ->           5 / 0
    AAVAS       2024-03                 2024-06 ->           3 / 0
    3MINDIA     2024-06                 2024-09 ->           2 / 0
    MANYAVAR    2024-09                 2024-12 ->           1 / 0

DELIBERATELY NOT PURGED: ~52 further companies show the same shape but their run starts in 2025+,
where scripts/xbrl_nature.json thins out and the NSE archive has no rows -- "no consolidated
declaration since" may simply be a stale cache. They are SUSPECT, NOT CONFIRMED, and must be
verified per company against the filings (route ladder §57) before anyone touches them.

Nulls only a cell that is currently EXACTLY EQUAL to its standalone twin (that equality IS the copy
signature); a divergent con is real data and is never touched. Journals every nulled cell with its
prior value to scripts/copied_con_purge.json so the action is reversible and auditable.

Run:  python -X utf8 scripts/purge_copied_con.py [--apply]
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FUND = os.path.join(ROOT, "docs", "sf_fundamentals.json")
FUND_M = os.path.join(HERE, "fundamentals.json")
REVOP = os.path.join(ROOT, "docs", "sf_revop.json")
REVOP_M = os.path.join(HERE, "revop_fundamentals.json")
LEDGER = os.path.join(HERE, "copied_con_purge.json")

# symbol -> first quarter of the copied run (inclusive), read from the shared ledger. This was a
# hardcoded list of 8 NSE-verified names; the ledger is now the single source of truth for both
# this purge and the coverage audit. Companies that filed consolidated and then STOPPED: anything
# from their stop quarter onward that still EQUALS standalone is a copy, not a filing.
# USER RULE 2026-08-06: no real consolidated filing for 4+ quarters => treat as stopped.
CONFIRMED = json.load(open(os.path.join(HERE, "no_con_filing.json")))["stopped_filing_con"]
TOL = 0.011


def same(a, b):
    return a is not None and b is not None and abs(a - b) <= max(TOL, abs(a) * 0.001)


def main():
    apply_it = "--apply" in sys.argv
    journal = {}
    # ---- PAT (sf_fundamentals shape: [qe, std, annStd, con, annCon])
    for path in (FUND, FUND_M):
        d = json.load(open(path))
        n = 0
        for sym, start in CONFIRMED.items():
            for r in d.get(sym, []):
                if r[0] < start or len(r) < 4:
                    continue
                if same(r[1], r[3]):
                    if path == FUND:
                        journal["%s|%d|patC" % (sym, r[0])] = {"was": r[3], "std": r[1]}
                    r[3] = None
                    if len(r) > 4:
                        r[4] = None
                    n += 1
        if apply_it:
            json.dump(d, open(path, "w"), separators=(",", ":"))
        print("%-30s patC nulled: %d" % (os.path.basename(path), n))
    # ---- REVENUE (sf_revop shape: {qe: [revS, revC, opS, opC, patS, patC, fin, ebitS, ebitC]})
    for path in (REVOP, REVOP_M):
        d = json.load(open(path))
        n = 0
        for sym, start in CONFIRMED.items():
            for qe, row in (d.get(sym) or {}).items():
                if int(qe) < start or not row or len(row) < 6:
                    continue
                if same(row[0], row[1]):
                    if path == REVOP:
                        journal["%s|%s|revC" % (sym, qe)] = {"was": row[1], "std": row[0]}
                    row[1] = None
                    n += 1
                if same(row[4], row[5]):          # PAT mirror slot inside sf_revop
                    row[5] = None
                if len(row) > 8 and same(row[7], row[8]):
                    row[8] = None
                if len(row) > 3 and same(row[2], row[3]):
                    row[3] = None
        if apply_it:
            json.dump(d, open(path, "w"), separators=(",", ":"))
        print("%-30s revC nulled: %d" % (os.path.basename(path), n))
    print("total journalled cells: %d%s" % (len(journal), "" if apply_it else "   (DRY RUN)"))
    if apply_it and journal:
        led = json.load(open(LEDGER)) if os.path.exists(LEDGER) else {}
        led.update(journal)
        json.dump(led, open(LEDGER, "w"), indent=1, sort_keys=True)
        print("journalled -> %s (reversible)" % os.path.basename(LEDGER))


if __name__ == "__main__":
    main()
