# -*- coding: utf-8 -*-
"""Residue batch: BASF consolidated = standalone for the 2021→Sep-2023 no-subsidiary window.

BASF's consolidation history, from the exchange's own record + its filings:
  * con quarterly XBRLs exist up to Dec-2020 (INDAS_67505/63038) — subsidiaries existed then;
  * Dec-2021 → Sep-2023: the NSE index lists a STANDALONE row for every quarter and NO
    consolidated row (E1+E2);
  * the audited FY23 results filing (Financialresults2023_10052023134500.pdf, 24 pages incl. the
    full PW auditor report + annexures) contains ZERO consolidated content — an audited
    standalone-only annual filing is the company's own assertion there was nothing to consolidate
    in FY23 (§51a: con quarterly is compulsory when subsidiaries exist);
  * the Jun-2024 auditor report notes the (new) entity became a subsidiary of the Parent
    "effective December 11, 2023", and con quarterly filings resume EXACTLY at Dec-2023;
  * stored PAT parity: con PAT == std PAT to the paisa across the window (82.39 Mar-23,
    112.68 Jun-23).

⚠️ KNOWN CONTRADICTION, deliberately NOT touched here: stored 20221231 revC 2860.42 differs from
revS 2898.1. In a window where the audited FY23 filing is standalone-only, a differing Dec-22
"consolidated" is impossible as labeled — that cell is the ETERNAL-class junk (probably a restated
continuing-ops std comparative mined into the con slot) and sits with the MGL/PATANJALI
adjudication task. This script is FILL-ONLY on null cells and does not modify it.

Fills (revC<-revS, opC<-opS, ebitC<-ebitS where con is null, std present):
  20211231, 20220930, 20230331, 20230630
Run: python -X utf8 scripts/fill2020_tools/apply_basf_nosub_identity.py [--apply]
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
LEDGER = os.path.join(SCRIPTS, "named_rev_cell_fills.json")

SYM = "BASF"
QES = ["20211231", "20220930", "20230331", "20230630"]
TWINS = [(1, 0, "revC"), (3, 2, "opC"), (8, 7, "ebitC")]
EV = ("no-subsidiary window identity: NSE index std-only Dec-21→Sep-23 (last con XBRL Dec-2020, "
      "con resumes Dec-23 when a new entity became a subsidiary effective 11-Dec-2023 per the "
      "Jun-24 auditor report); audited FY23 filing 10-May-2023 is standalone-only (zero con "
      "content in 24pp); stored con PAT == std PAT across the window")


def main():
    dry = "--apply" not in sys.argv
    filled = {}
    for path in (os.path.join(ROOT, "docs", "sf_revop.json"),
                 os.path.join(SCRIPTS, "revop_fundamentals.json")):
        d = json.load(open(path))
        for qe in QES:
            row = d.get(SYM, {}).get(qe)
            if not row:
                print("%-26s %s no row" % (os.path.basename(path), qe))
                continue
            while len(row) < 9:
                row.append(None)
            got = []
            for c_i, s_i, name in TWINS:
                if row[c_i] is None and row[s_i] is not None:
                    row[c_i] = row[s_i]
                    got.append("%s=%s" % (name, row[s_i]))
            d[SYM][qe] = row
            filled.setdefault(qe, got)
            print("%-26s %s %s %s" % (os.path.basename(path), qe,
                                      "would fill" if dry else "filled",
                                      ", ".join(got) or "(nothing null)"))
        if not dry:
            json.dump(d, open(path, "w"), separators=(",", ":"))
    if not dry:
        led = json.load(open(LEDGER)) if os.path.exists(LEDGER) else {}
        for qe, got in filled.items():
            if got:
                led["%s|%s" % (SYM, qe)] = {"identity": got, "src": "no-sub-window-identity",
                                            "evidence": EV, "applied": "2026-08-10 residue batch"}
        json.dump(led, open(LEDGER, "w"), indent=1, sort_keys=True)
        print("journalled -> %s" % os.path.basename(LEDGER))
    else:
        print("DRY RUN -- nothing written.")


if __name__ == "__main__":
    main()
