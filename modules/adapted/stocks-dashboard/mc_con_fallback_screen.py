# -*- coding: utf-8 -*-
"""★ MONEYCONTROL'S CONSOLIDATED TABLE FALLS BACK TO STANDALONE — screen before applying anything.

THE DEFECT, measured 2026-08-11 before a single cell was written. Moneycontrol serves a
`cons_quarterly` table for a company even in quarters where the company filed NO consolidated
result — and in those quarters the row carries the STANDALONE figure. Land it and you have
manufactured a consolidated number that is really the standalone one: the con-copy defect class
§67 had to re-adjudicate 18 heals over, arriving this time through an aggregator instead of a
reader.

It is invisible to the series gate. The gate proves MC's consolidated series is OUR company's
consolidated series by reproducing stored con values elsewhere — and it does, correctly. The
fallback is PER QUARTER, inside a series that is otherwise right.

★ THE TEST APPLIED NOW (2026-08-11) IS SOURCE-INTERNAL, and it replaced the one below:

    MC's consolidated  vs  MC's OWN standalone, same quarter, SAME LABEL.
      differs   -> a real consolidated table FOR THAT FIELD. Kept.
      identical -> UNRESOLVED. Held, and deliberately NOT called "fallback proven": identical is
                   exactly what BOTH explanations predict — the aggregator repeating standalone, and
                   an equity-accounted structure whose consolidated genuinely equals its standalone.
                   Calibrated against GAYAPROJ 2019-03 and PIIND 2019-03, both PROVEN fallbacks,
                   which nonetheless BOTH show a PAT line differing from their own standalone (4.39
                   and 1.30) and a consolidated-only minority-interest row — so neither of those
                   signals settles it either. Only the filing does (§57/§58).

⚠️ THE OLD DISCRIMINATOR BELOW IS THE WEAK ONE, kept as the historical record. Comparing MC's
consolidated to OUR stored standalone cannot separate the two explanations, and it refuted 6 of the
10 cells it was re-run on — SHREECEM's retraction rested on "con equals our stored std" when 3070.15
is not 3069.91. Our own store now only breaks ties when the source has no standalone twin at all.

THE OLD DISCRIMINATOR (no fetch, our own data):

    MC's con value == our stored STD value for the same quarter
      AND the company's own history shows con != std in ANY other quarter
        -> HOLD. The company demonstrably consolidates differently, so an identical figure here
           is MC repeating standalone, not a real consolidated result.

    MC's con value == our stored STD value, and our history NEVER shows con != std
        -> KEEP. Genuine no-consolidation-difference company (the MOIL / CHENNPETRO shape, where
           consolidated revenue equals standalone because subsidiaries are equity-accounted).

Measured on the first whole-history run:
    con revenue : 852 cells equal our stored std -> 525 HELD (206 companies), 327 kept (114)
    con PAT     : 256 cells equal our stored std -> 254 HELD (102 companies), 20 kept (7)
Worst offenders by evidence against them: KRBL (our store shows con!=std in 28 quarters), JHS 20,
BILVYAPAR 17, MINDTREE 15.

Annotates the ledgers in place with `held` + the reason; the appliers skip anything held. Nothing
is deleted — a held cell is a candidate for a real consolidated source, not a dead one.

Run: python -X utf8 scripts/fill2020_tools/mc_con_fallback_screen.py [--apply-flags]
"""
import json
import os
import sys

HERE_ = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE_)
import mc_quarterly_fetch as MC                                   # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)

REVOP = os.path.join(ROOT, "docs", "sf_revop.json")
FUND = os.path.join(ROOT, "docs", "sf_fundamentals.json")
REV_LEDGERS = ["mc_history_fills.json", "mc_quarterly_fills.json"]
PAT_LEDGERS = ["mc_pat_fills.json"]


def mat(a, b):
    return a is not None and b is not None and abs(a - b) > max(0.05, 0.001 * abs(b))


def same(a, b):
    """A FALLBACK IS BYTE-IDENTICAL, so this test must be near-exact — not the 0.1% band used for
    series anchoring. Measured the difference it makes: at 0.1%, JKPAPER 2019-03 (con 807.16 vs std
    806.76, a real 0.40 consolidation difference) and PCBL (920.99 vs 921.43) were both flagged as
    copies and would have been held for nothing, while the genuine copies GAYAPROJ and PIIND sit at
    diff exactly 0.0. Anchoring tolerance absorbs rounding between two SOURCES; this test compares
    two numbers that are either the same number or not."""
    return a is not None and b is not None and abs(a - b) <= 0.005


def cur_value(sym, qe, basis, is_pat, revop, fmap):
    """What the payload holds for this cell right now, or None."""
    if is_pat:
        row = (fmap.get(sym) or {}).get(qe)
        slot = 1 if basis == "std" else 3
    else:
        row = (revop.get(sym) or {}).get(str(qe))
        slot = 0 if basis == "std" else 1
    return row[slot] if row and len(row) > slot else None


def main():
    write = "--apply-flags" in sys.argv
    revop = json.load(open(REVOP))
    fund = json.load(open(FUND))
    fmap = {s: {r[0]: r for r in rows} for s, rows in fund.items()}

    # companies whose OWN stored history proves a consolidation difference exists
    rev_diff = {s for s, q in revop.items()
                if any(r[0] and r[1] is not None and r[0] > 0 and mat(r[1], r[0]) for r in q.values())}
    pat_diff = {s for s, rows in fmap.items()
                if any(len(r) > 3 and mat(r[3], r[1]) for r in rows.values())}

    total_held = 0
    for name in REV_LEDGERS + PAT_LEDGERS:
        p = os.path.join(SCRIPTS, name)
        if not os.path.exists(p):
            continue
        led = json.load(open(p))
        is_pat = name in PAT_LEDGERS
        held = kept = review = 0
        for k, v in led.items():
            if k.count("|") != 2 or not isinstance(v, dict) or v.get("held"):
                continue
            sym, qe, basis = k.split("|")
            if basis != "con":
                continue
            val = v.get("pat") if is_pat else v.get("rev")
            if val is None:
                continue
            if is_pat:
                row = fmap.get(sym, {}).get(int(qe))
                std = row[1] if row and len(row) > 1 else None
                proves = sym in pat_diff
            else:
                row = (revop.get(sym) or {}).get(qe)
                std = row[0] if row else None
                proves = sym in rev_diff
            # ★ THIRD STATE — the empty-twin case (raised by the aggregator session, 2026-08-11).
            # When our OWN std cell for that quarter is null there is nothing to compare against,
            # and the cell was previously falling straight through UNCHECKED — neither held nor
            # examined. "Keep" would be unearned. But a better test exists than holding blindly:
            # compare MC's consolidated to MC's OWN standalone for that quarter. That is
            # source-internal, needs nothing from our store, and is the direct form of the question.
            if std is None:
                mc_std = None
                code = v.get("sc_id")
                if code:
                    raw = MC.series_raw(code, "std", 400)
                    row_label = v.get("row_label")
                    for r in raw:
                        if MC.qe_of(r.get("yrc0")) == int(qe):
                            mc_std = MC.num(r.get(row_label)) if row_label else None
                            if mc_std is None:
                                mc_std = MC.num(r.get("Net Profit/(Loss) For the Period") if is_pat
                                                else r.get("Net Sales/Income from operations"))
                            break
                if mc_std is not None and same(val, mc_std) and proves:
                    v["held"] = ("no stored standalone twin, so compared SOURCE-INTERNALLY: MC's "
                                 "consolidated equals MC's OWN standalone for this quarter, and this "
                                 "company shows con != std elsewhere — the fallback, caught without "
                                 "needing our twin.")
                    held += 1
                elif mc_std is None:
                    v["held"] = ("HOLD-NO-TWIN: our standalone cell for this quarter is empty AND "
                                 "MC serves no standalone row for it, so the fallback test cannot "
                                 "run at all. Unverifiable rather than verified — not written.")
                    held += 1
                else:
                    v["fallback_check"] = "no stored twin; MC's own con and std differ here — genuine"
                continue
            # ★ SOURCE-INTERNAL FIRST (2026-08-11). Whatever our own standalone says, the question
            # is whether MC's consolidated table is a copy of MC's OWN standalone table. Fetch the
            # same label from the std series and compare there; our store only breaks ties.
            mc_twin = None
            code = v.get("sc_id")
            label = v.get("row_label")
            if code and label:
                for r2 in MC.series_raw(code, "std", 400):
                    if MC.qe_of(r2.get("yrc0")) == int(qe):
                        mc_twin = MC.row_value(r2, label)
                        break
            if mc_twin is not None and not same(val, mc_twin):
                v["fallback_check"] = ("MC consolidated %.2f DIFFERS from MC's OWN standalone %.2f on "
                                       "the same label — a real consolidated table for this field."
                                       % (val, mc_twin))
                kept += 1
                continue
            if mc_twin is not None and same(val, mc_twin):
                why = ("MC's consolidated equals MC's OWN standalone to the cent on the same label "
                       "for this quarter. UNRESOLVED, not a proven copy: identical is what BOTH "
                       "explanations predict — the aggregator repeating standalone, and an "
                       "equity-accounted structure whose consolidated really does equal its "
                       "standalone. Settle from the filing (§57/§58), not this source.")
                # ★ A LIVE CELL IS NOT HELD RETROACTIVELY. `held` asserts the slot must stay EMPTY,
                # so stamping it on a value already in the payload manufactures a RESURRECTED alarm
                # and, worse, invites --repair-held to delete a value that was never proven wrong.
                # Unwritten -> held. Already applied -> flagged for review, and the decision to
                # retract several hundred live cells is a deliberate one taken with evidence, not a
                # side effect of tightening a screen.
                live = cur_value(sym, int(qe), basis, is_pat, revop, fmap)
                if live is not None and abs(live - val) <= 0.011:
                    v["review_unresolved"] = why
                    review += 1
                else:
                    v["held"] = why
                    held += 1
                continue
            if not same(val, std):
                continue
            if proves:
                v["held"] = ("MC consolidated == our standalone for this quarter, and this company's "
                             "own history shows con != std elsewhere — Moneycontrol's consolidated "
                             "table falls back to standalone where no consolidated result was filed. "
                             "Writing it would manufacture a consolidated figure (§67 class).")
                held += 1
            else:
                # log HOW MUCH evidence the keep rests on — "never shows con != std" is far
                # stronger at 40 stored quarters than at 2 (their RAJESHEXPO point: a company can
                # do both, and a bare boolean loses that).
                n_same = (sum(1 for r in fmap.get(sym, {}).values()
                              if len(r) > 3 and r[1] is not None and r[3] is not None) if is_pat
                          else sum(1 for r in (revop.get(sym) or {}).values()
                                   if r[0] is not None and r[1] is not None))
                v["fallback_check"] = ("equals our standalone, but this company never shows con != std "
                                       "across %d overlapping stored quarters — genuine "
                                       "no-consolidation-difference, kept" % n_same)
                kept += 1
        total_held += held
        print("%-28s HELD %4d  |  kept %4d  |  LIVE-but-unresolved (review) %4d"
              % (name, held, kept, review))
        if write:
            json.dump(led, open(p, "w"), indent=1, sort_keys=True)
    print("\ntotal held across ledgers: %d" % total_held)
    if not write:
        print("(dry run — re-run with --apply-flags to annotate the ledgers)")


if __name__ == "__main__":
    main()
