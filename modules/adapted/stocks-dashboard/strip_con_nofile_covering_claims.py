# -*- coding: utf-8 -*-
"""Strip the con_nofile_identity_fills.json claims the con-copy retraction already emptied.

WHY THIS EXISTS. PLAN_CON_COPY_RETRACTION.md enumerates the ledgers that "cover" a con=std copy and
must be stripped in the same change as the retraction -- nosub_pat_fills.json (163 -> 20 entries) and
nosub_rev_pre2020_fills.json (1,205 -> 95) were both done. `con_nofile_identity_fills.json` is the
same KIND of ledger (its own premise: "con = std where NSE's filing index proves no consolidated
result exists" -- gates E1/E2/E3) but it was never enumerated, so its claims were left standing after
b395fa35 emptied the cells. That is precisely the failure this campaign's own notes warn about:
an attribution claim about ledgers requires enumerating scripts/*fills*.json by GLOB, not from memory.

THE COST OF LEAVING IT: verify_fills_live.py registers this ledger's revC, so 174 cells read as
MISSING (clobbered) -- and that check is BLOCKING in refresh-fundamentals.yml, so the whole
fundamentals payload stopped publishing and mailed on every run.

MEASURED BEFORE WRITING ANYTHING (2026-08-18):
  * 174 revC claims here whose payload cell is now empty;
  * 174 of 174 are recorded in scripts/con_copy_retractions.json, every one class=FABRICATED_PREFLOOR
    with its exchange first-con floor (e.g. BASF 20200331, floor 20200930);
  * ZERO unexplained losses -- so none of these is a conflict-recovery casualty to restore.
  * The sibling slots agree: opC empty for all 172 that claim it, ebitC empty for all 131. The
    campaign retracted the whole con family per cell, so stripping all three is consistent with the
    payload rather than a judgement of my own.

This does NOT adjudicate anything. The verdict is the user's standing ruling ("the con=std
no-subsidiary convention is a mistake -- do all"; a con slot may hold ONLY filing-backed values), the
retraction is already applied and journalled, and this is the covering-ledger bookkeeping the plan
already calls for. `evidence` is kept on every entry as the record of why the identity fill was
originally made; only the value claims go.

Run: python3 -X utf8 scripts/strip_con_nofile_covering_claims.py [--apply]
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SLOTS = {"revC": 1, "opC": 3, "ebitC": 8}


def main():
    apply = "--apply" in sys.argv
    revop = json.load(open(os.path.join(ROOT, "docs", "sf_revop.json"), encoding="utf-8"))
    retr = json.load(open(os.path.join(HERE, "con_copy_retractions.json"), encoding="utf-8"))
    p = os.path.join(HERE, "con_nofile_identity_fills.json")
    nof = json.load(open(p, encoding="utf-8"))
    fills = nof.get("fills", nof)

    stripped = skipped = 0
    for sym, qd in fills.items():
        if not isinstance(qd, dict):
            continue
        for qe, v in qd.items():
            if not isinstance(v, dict) or v.get("revC") is None:
                continue
            row = (revop.get(sym) or {}).get(str(qe))
            if not (row and len(row) > 1 and row[1] is None):
                continue                              # still live -- leave the claim alone
            if "%s|%s" % (sym, qe) not in retr:
                # An empty cell with NO retraction record is an unexplained loss, not a retraction.
                # Restoring or stripping it would both be guesses, so refuse and name it.
                print("  !! %s %s empty but NOT in con_copy_retractions — leaving it, needs a human"
                      % (sym, qe))
                skipped += 1
                continue
            for k in SLOTS:
                v.pop(k, None)
            v["retracted"] = ("con-copy retraction 2026-08-18 (%s, floor %s) emptied this cell; the "
                              "covering claim is stripped here so the ledger stops asserting a value "
                              "the payload no longer holds. Record: scripts/con_copy_retractions.json "
                              "key %s|%s. The E1/E2/E3 identity evidence above is kept as the record "
                              "of why the fill was originally made."
                              % (retr["%s|%s" % (sym, qe)].get("class", "?"),
                                 retr["%s|%s" % (sym, qe)].get("floor", "?"), sym, qe))
            stripped += 1

    print("\n  %s: %d covering claim(s) stripped, %d left for a human"
          % ("APPLIED" if apply else "DRY RUN", stripped, skipped))
    if apply and stripped:
        json.dump(nof, open(p, "w"), indent=1, sort_keys=True)
        print("  WROTE con_nofile_identity_fills.json")
    elif not apply:
        print("  re-run with --apply to write")
    return 0


if __name__ == "__main__":
    sys.exit(main())
