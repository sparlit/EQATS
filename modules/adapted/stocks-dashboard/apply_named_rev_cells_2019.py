# -*- coding: utf-8 -*-
"""FILL-2019: revenue cells read BY HAND from the filings, with the whole anchor chain journalled.

Same contract as apply_named_rev_cells.py (the 2020-22 campaign's version): fill-only, one slot,
and every cell carries the document, the column evidence, the anchor and an independent identity
check. Ledger: scripts/named_rev_cell_fills_2019.json (tracked).

  ABCAPITAL 2019-03  revC 4729.82
      Read TWICE, from two independent as-filed documents that agree to the paisa:
      (a) the AUDITED Mar-2019 filing (BSE announcement 2019-05-04, "Audited Financial Results For
          The Quarter And Year Ended 31st March, 2019"), consolidated statement, column headed
          "Quarter Ended 31st Mar 2019": Total Revenue from operations 4,729.82 · Other Income 0.98
          · Total Income (1+2) 4,730.80 · Profit attributable to Owners of the Company 258.40;
      (b) the Jun-2019 filing (announcement 2019-08-02), whose consolidated statement prints the
          comparative column headed "31st March, 2019 (Refer Note 6)" with the SAME
          4,729.82 / 0.98 / 4,730.80 / 258.40.
      Anchors: owners-PAT 258.40 == our stored consolidated PAT for 2019-03 EXACTLY (both docs);
      internal identity 4,729.82 + 0.98 == 4,730.80 printed, exact, in both docs; scale declared
      "crore" in the header (neighbouring stored revC 3,025-3,780 confirm the magnitude).
      ⚠️ Column identity comes from the PRINTED HEADER DATE, not from position — (b) is a
      comparative column in a later filing, exactly the case §55b exists for.
      NOT anchored on the FY sum: the four stored FY19 con quarters total 15,125.23 against the
      printed FY 15,163.51 (0.25% apart), so the FY identity is recorded as NOT reconciling and is
      not used as evidence. The two-document agreement plus the exact PAT anchor is what lands it.
      This cell was invisible to every automated route because ABCAPITAL's 2019 filings carry a
      TRIPLE-RENDERED text layer (every word and figure stacked three times at the same
      coordinates), so no label regex matches — see DATA_RUNBOOK §73 and deoverlay_rev_reader.py.

Run: python -X utf8 scripts/fill2020_tools/apply_named_rev_cells_2019.py [--apply]
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)

REVOP_DOCS = os.path.join(ROOT, "docs", "sf_revop.json")
REVOP_LEDGER = os.path.join(SCRIPTS, "revop_fundamentals.json")
FUND = os.path.join(ROOT, "docs", "sf_fundamentals.json")
LEDGER = os.path.join(SCRIPTS, "named_rev_cell_fills_2019.json")

# sf_revop row: [revStd, revCon, opStd, opCon, patStd, patCon, fin, ebitStd, ebitCon]
SLOT = {"revS": 0, "revC": 1}

CELLS = {
    "ABCAPITAL|20190331": {
        "revC": 4729.82,
        "src": "bse-filing-pdf-manual-read (two documents)",
        "applied": "2026-08-10 FILL-2019 named cells",
        "anchor_pat_con_stored": 258.40,
        "evidence": (
            "Audited Mar-2019 filing (BSE ann 2019-05-04) consolidated statement, column headed "
            "'Quarter Ended 31st Mar 2019': Total Revenue from operations 4,729.82; Other Income "
            "0.98; Total Income (1+2) 4,730.80; Profit attributable to Owners 258.40 == stored con "
            "PAT exactly. The Jun-2019 filing (ann 2019-08-02) prints the same figures in its "
            "comparative column headed '31st March, 2019 (Refer Note 6)'. Scale 'crore' declared. "
            "Identity 4729.82+0.98==4730.80 exact in both. FY-sum does NOT reconcile (stored FY19 "
            "quarters 15,125.23 vs printed 15,163.51, 0.25%) and is deliberately not used."),
        "reader_note": (
            "invisible to the automated sweep: ABCAPITAL's 2019 PDFs carry a triple-rendered text "
            "layer, so 'Revenue from operations' never appears contiguously (runbook §73)"),
    },
}


def main():
    apply_it = "--apply" in sys.argv
    revop = json.load(open(REVOP_DOCS))
    ledger = json.load(open(REVOP_LEDGER))
    fund = json.load(open(FUND))
    fmap = {s: {r[0]: r for r in rows} for s, rows in fund.items()}
    journal = json.load(open(LEDGER)) if os.path.exists(LEDGER) else {}

    plan = []
    for key, rec in sorted(CELLS.items()):
        sym, qe_s = key.split("|")
        qe = int(qe_s)
        row = (revop.get(sym) or {}).get(qe_s)
        if row is None:
            print("SKIP %s — no sf_revop row" % key)
            continue
        # re-prove the anchor against CURRENT stored data before writing anything
        stored_con = (fmap.get(sym, {}).get(qe) or [None] * 4)[3]
        want = rec.get("anchor_pat_con_stored")
        if want is not None and (stored_con is None or abs(stored_con - want) > 0.01):
            print("REFUSE %s — stored con PAT is now %s, the ledger anchored on %s"
                  % (key, stored_con, want))
            continue
        for field, slot in SLOT.items():
            v = rec.get(field)
            if v is None:
                continue
            if row[slot] is not None:
                print("SKIP %s %s — already %s (fill-only)" % (key, field, row[slot]))
                continue
            plan.append((sym, qe_s, slot, field, v, rec))
    for sym, qe_s, slot, field, v, rec in plan:
        print("%-12s %s %s = %s   [%s]" % (sym, qe_s, field, v, rec["src"]))
    if not apply_it:
        print("\n(dry run — %d cell(s) would be written. Re-run with --apply)" % len(plan))
        return
    for sym, qe_s, slot, field, v, rec in plan:
        revop[sym][qe_s][slot] = v
        lrow = ledger.setdefault(sym, {}).get(qe_s)
        if lrow is None:
            ledger[sym][qe_s] = list(revop[sym][qe_s])
        elif lrow[slot] is None:
            lrow[slot] = v
        journal["%s|%s" % (sym, qe_s)] = dict(rec)
    json.dump(revop, open(REVOP_DOCS, "w"), separators=(",", ":"))
    json.dump(ledger, open(REVOP_LEDGER, "w"), separators=(",", ":"))
    json.dump(journal, open(LEDGER, "w"), indent=1, sort_keys=True)
    print("\nAPPLIED %d cell(s); journalled to %s" % (len(plan), os.path.basename(LEDGER)))


if __name__ == "__main__":
    main()
