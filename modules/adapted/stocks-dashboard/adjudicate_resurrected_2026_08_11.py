# -*- coding: utf-8 -*-
"""RESURRECTED-CELL ADJUDICATION — settle 10 cells that a hold and a live value disagree about.

WHERE THESE CAME FROM. The 2018 session found two retracted cells live again and asked me to screen
my Moneycontrol ledgers. Registering those ledgers in verify_fills_live.py and adding the RESURRECTED
check (a held cell asserts ABSENCE, so a live match is the failure) turned up 10 distinct cells, not
2 — every one of them claimed by two ledgers with CONTRADICTORY verdicts, held in one and active in
the other, so whichever applier ran last decided the store's contents.

★ A HOLD IS A HYPOTHESIS, NOT A VERDICT. Both screens held on the same weak test: "MC's consolidated
equals OUR stored standalone, and this company consolidates differently elsewhere". That test cannot
separate the aggregator repeating standalone from a company whose consolidated genuinely equals its
standalone. The only test that discriminates is SOURCE-INTERNAL, on the SAME FIELD, and needs nothing
from our store:

    MC's consolidated row  vs  MC's OWN standalone row, same quarter, SAME LABEL.
      differs at all  -> a real consolidated table for that field. A copy is not off by 0.24.
      byte-identical  -> UNRESOLVED. NOT "fallback proven".

★★★ WHY THE IDENTICAL CASE IS UNRESOLVED AND NOT A VERDICT — the calibration that cost me a wrong
retraction. I first read byte-identity as proof of the fallback and retracted four cells on it. Then
I calibrated against GAYAPROJ 2019-03 and PIIND 2019-03, the two cells already PROVEN fallbacks
(revenue identical to the cent). Both of them ALSO carry:
      - a PAT line that DIFFERS from MC's own standalone (GAYAPROJ by 4.39, PIIND by 1.30), and
      - a consolidated-ONLY "Net P/L After M.I & Associates" row that standalone has no equivalent for.
So neither "the PAT differs" nor "there is a minority-interest row" proves a genuine consolidated
table — both signals appear in known fallbacks. And symmetrically, identical revenue does not prove a
copy: a company whose subsidiaries are equity-accounted files consolidated revenue EQUAL to
standalone while its profit differs (the MOIL / CHENNPETRO shape). The two explanations are
indistinguishable from this source. Settling them needs the FILING (§57/§58), not the aggregator.
Each field must be judged on its own row: BATAINDIA's revenue is unresolved while its PAT, which
differs by 0.80, is fine.

Measured 2026-08-11 on all 10 (fetched MC's std series where the cache lacked it):
    UNRESOLVED revenue -> retracted, reason states it is unproven, not a proven copy:
        BATAINDIA 2018-09, BEML 2018-09, FINCABLES 2018-09, SCI 2018-09
    GENUINE (MC con revenue differs from MC's OWN std revenue) -> hold lifted, value stands:
        CENTURYPLY 2018-12 (0.28), COCHINSHIP 2018-12 (0.69), GLAXO 2018-12 (0.32),
        SJVN 2018-09 (0.38), SJVN 2018-12 (0.03), SHREECEM 2018-06 (0.24 rev, 0.12 PAT)
Weakest of the genuine set is SJVN 2018-12 at 0.03 on a 484 crore figure — above the 0.005 copy
threshold, but small enough that it is the one to re-read first if a document ever contradicts it.

Lifting a hold matters as much as retracting a value: verify_fills_live --repair-held NULLS anything
still flagged, so leaving a wrong hold in place arms a tool to delete a correct number later.

Run: python -X utf8 scripts/fill2020_tools/adjudicate_resurrected_2026_08_11.py [--apply]
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
REVOP = os.path.join(ROOT, "docs", "sf_revop.json")
FUND = os.path.join(ROOT, "docs", "sf_fundamentals.json")
LEDGERS = ["mc_history_fills.json", "mc_quarterly_fills.json", "mc_pat_fills.json"]

PROOF = ("SOURCE-INTERNAL test 2026-08-11: Moneycontrol's consolidated row %s Moneycontrol's OWN "
         "standalone row for this quarter, same label (con %s vs std %s). ")
FB_WHY = (PROOF + "UNRESOLVED, NOT a proven copy: identical is exactly what BOTH explanations "
          "predict — the aggregator repeating standalone, and a company whose subsidiaries are "
          "equity-accounted so consolidated revenue genuinely equals standalone. Calibrated against "
          "GAYAPROJ 2019-03 and PIIND 2019-03, both PROVEN fallbacks, which nonetheless show a "
          "differing PAT line and a consolidated-only minority-interest row — so neither of those "
          "signals settles it either. Withheld because an unverifiable consolidated figure is worse "
          "than an admitted gap; settle it from the FILING (§57/§58), not from this source.")
OK_WHY = (PROOF + "It DIFFERS by %.2f, and a copy is not off by that, so MC is serving a real "
          "consolidated table for this field. The earlier hold rested on 'con equals OUR stored "
          "standalone', which is a different comparison and cannot tell the aggregator repeating "
          "standalone from a genuine equal-value consolidation. Hold LIFTED; value stands.")

# (sym, qe, field, value, mc_con, mc_std, withhold)  -- judged PER FIELD; see the docstring
CELLS = [
    ("BATAINDIA",  20180930, "rev", 673.07,  673.07,  673.07,  True),
    ("BEML",       20180930, "rev", 734.05,  734.05,  734.05,  True),
    ("FINCABLES",  20180930, "rev", 713.97,  713.97,  713.97,  True),
    ("SCI",        20180930, "rev", 939.81,  939.81,  939.81,  True),
    ("CENTURYPLY", 20181231, "rev", 579.17,  579.17,  578.89,  False),
    ("COCHINSHIP", 20181231, "rev", 717.11,  717.11,  716.42,  False),
    ("GLAXO",      20181231, "rev", 825.03,  825.03,  825.35,  False),
    ("SJVN",       20180930, "rev", 751.52,  751.52,  751.90,  False),
    ("SJVN",       20181231, "rev", 484.46,  484.46,  484.49,  False),
    ("SHREECEM",   20180630, "rev", 3070.15, 3070.15, 3069.91, False),
    ("SHREECEM",   20180630, "pat", 279.36,  279.36,  279.48,  False),
    # BATAINDIA's REVENUE is unresolved above, but its PAT is a different row and must be judged on
    # that row: MC's consolidated PAT differs from MC's own standalone PAT by 0.80. Stamping the
    # revenue verdict onto the PAT ledger — which the first version of this script did — is the same
    # category error as reading one field's anchor as validation of another.
    ("BATAINDIA",  20180930, "pat", 54.86,   54.86,   55.66,   False),
]
# which ledgers speak for which field — a revenue verdict must never be written into the PAT ledger
FIELD_LEDGERS = {"rev": ["mc_history_fills.json", "mc_quarterly_fills.json"],
                 "pat": ["mc_pat_fills.json"]}
TOL = 0.011


def main():
    apply_it = "--apply" in sys.argv
    revop = json.load(open(REVOP))
    fund = json.load(open(FUND))
    fmap = {s: {r[0]: r for r in rows} for s, rows in fund.items()}
    leds = {n: json.load(open(os.path.join(SCRIPTS, n))) for n in LEDGERS
            if os.path.exists(os.path.join(SCRIPTS, n))}

    retracted = lifted = restored = 0
    for sym, qe, field, val, mcc, mcs, fb in CELLS:
        why = (FB_WHY % ("EQUALS", mcc, mcs) if fb
               else OK_WHY % ("DIFFERS from", mcc, mcs, abs(mcc - mcs)))
        key = "%s|%d|con" % (sym, qe)
        for name in FIELD_LEDGERS[field]:
            led = leds.get(name)
            e = led.get(key) if led else None
            if not isinstance(e, dict):
                continue
            if fb:
                e["held"] = why
            else:
                e.pop("held", None)
                e["fallback_check"] = why
        # the payload itself
        if field == "rev":
            row = (revop.get(sym) or {}).get(str(qe))
            if row is None or len(row) < 2:
                print("  !! %s %d: no sf_revop row" % (sym, qe))
                continue
            cur = row[1]
            if fb and cur is not None and abs(cur - val) <= TOL:
                row[1] = None
                retracted += 1
                print("  RETRACTED  %-11s %d con rev %s (fallback proven)" % (sym, qe, val))
            elif not fb:
                if cur is None:
                    row[1] = val
                    restored += 1
                    print("  RESTORED   %-11s %d con rev %s (genuine, was retracted)" % (sym, qe, val))
                lifted += 1
        else:
            row = (fmap.get(sym) or {}).get(qe)
            if row is None or len(row) < 4:
                print("  !! %s %d: no sf_fundamentals row" % (sym, qe))
                continue
            if fb and row[3] is not None and abs(row[3] - val) <= TOL:
                row[3] = None
                retracted += 1
            elif not fb:
                if row[3] is None:
                    row[3] = val
                    restored += 1
                lifted += 1

    print("\nretracted %d  |  holds lifted %d  |  values restored %d" % (retracted, lifted, restored))
    if not apply_it:
        print("(dry run — re-run with --apply)")
        return
    json.dump(revop, open(REVOP, "w"), separators=(",", ":"))
    json.dump(fund, open(FUND, "w"), separators=(",", ":"))
    for name, led in leds.items():
        json.dump(led, open(os.path.join(SCRIPTS, name), "w"), indent=1, sort_keys=True)
    print("APPLIED to the payloads and %d ledgers" % len(leds))


if __name__ == "__main__":
    main()
