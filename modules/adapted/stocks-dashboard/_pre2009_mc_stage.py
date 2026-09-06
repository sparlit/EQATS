# -*- coding: utf-8 -*-
"""PRE-2009 std-revenue campaign — stage Moneycontrol deep-feed cells with an ERA-SPECIFIC
convention gate.  (scripts/PLAN_PRE2009_STDREV.md; runbook §81 aggregator route.)

WHY THIS EXISTS RATHER THAN _mc_batch_fill.py
---------------------------------------------
_mc_batch_fill.py votes on the revenue convention across the symbol's WHOLE history. That is
right for 2009+, and wrong here, because MC's pre-2009 payload is a different document:

  * MEASURED 2026-08-26 over all 322 gap symbols: the pre-2009 rows carry only
    "Net Sales/Income from operations" (rev_ops).  "Total Income From Operations" (rev_total,
    the Clause-41 label) appears only from ~2008-06.  So a symbol whose 2009+ convention votes
    `rev_total` finds `None` on every 2002-07 quarter -> silent zero yield.
  * Worse, MC's pre-2009 "Net Sales" is GROSS OF EXCISE DUTY for many manufacturers while our
    stored revStd is net: CENTENKA ratio 0.82-0.86, LINDEINDIA 0.90, RELIANCE 0.91, NATIONALUM
    0.92-0.94.  Store-wide, MC rev_ops reproduces our stored pre-2009 revStd on only 63.6% of
    the 4,430 overlapping cells.  A whole-history vote would have called those symbols "rev_ops"
    off their 2009+ agreement and then written the gross figure into a net-convention series.
    (runbook: feedback-aggregator-two-revenue-definitions)
  * MC's pre-2009 payload for BANKS carries NO revenue row at all -- only PAT and Depreciation
    (measured on FEDERALBNK, KTKBANK).  So the "Interest Earned" convention the plan expected is
    simply absent here; banks must go to the NSE archive, not to MC.

GATE CALIBRATION (measured 2026-08-26, leave-one-out over 398 (symbol, revenue-field) series
with >=5 pre-2009 overlaps; the question scored is the one a fill actually asks -- "does MC's
value for THIS quarter equal our line?"):

    whole-era, >=3 agreeing, 0 disagreeing (batches 1 and 4)   precision 0.918  recall 0.293
    +/-1yr window, >=2 agreeing, 0 disagreeing                 precision 0.947  recall 0.565
    look-forward 2yr, >=5 agreeing, 0 disagreeing              precision 0.967  recall 0.780
    +/-2yr window,  >=5 agreeing, 0 disagreeing  <-- DEFAULT    precision 0.986  recall 0.648

The whole-era vote is the weakest because OUR OWN stored pre-2009 series is multi-route --
wayback 2002-04, NSE archive 2005-07, BSE detres 2008+ -- and can change revenue convention
mid-era.  A symbol-level verdict averages over that break; a per-cell window gate does not.
Cross-sub-era transfer was measured directly and is only ~0.86 precise in BOTH directions
(2005-08 -> 2002-04 and back), which is why the window is local and why 2000-01 cells are
gated on their 2002-03 neighbours rather than on a symbol-wide verdict.

Two earlier calibrations of this same gate returned 0.39 and 0.87.  Both scored a symbol as
"MC's line is not ours" whenever ANY overlapping quarter differed, which condemns a series that
differs on one restated quarter in twenty (MARICO, ABB, SIEMENS all sit at 0.92-0.94).  The
metric only became meaningful once it asked about the individual cell being written.
(memory: feedback-measure-the-metric-you-ship, feedback-calibrate-gate-by-holdout)

THE GATE (all four must hold before a cell is staged)
  1. convention established for THIS CELL: >= --min-agree stored overlaps within +/- --win
     CALENDAR YEARS agree with MC on one field and ZERO in that window disagree, at
     max(0.5cr, 1%).  (--gate era reproduces batches 1 and 4: one verdict per symbol over
     2002-2008, >=3 agreeing / 0 disagreeing.)
  2. MC carries that same field on the target quarter.
  3. MC's pat_total matches the stored sf_fundamentals npStd (previewed here, RE-CHECKED by
     _apply_reads.py at write time -- that is the gate that actually binds).
  4. the cell is in the campaign's measured gap (npStd present, revStd absent).

Run:  python -X utf8 scripts/_pre2009_mc_stage.py --gaps <gaps.json> --emit <emit.json>
        [--gate window|era] [--win 2] [--min-agree 5] [--only SYM,SYM]
      then:  python -X utf8 scripts/_mc_add.py < <emit.json>  &&  python -X utf8 scripts/_apply_reads.py
"""
import os, sys, json, collections

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(HERE, "agg_tools"))
import agg_sources as A

LO, HI = 20020101, 20090101


def close(a, b, ta=0.5, tp=0.01):
    if a is None or b is None:
        return False
    return abs(a - b) <= max(ta, tp * max(abs(a), abs(b)))


def anchor_ok(a, b):
    """Same tolerance _apply_reads.py uses, so the preview matches the binding gate."""
    if a is None or b is None:
        return False
    return abs(a - b) <= max(2.0, 0.03 * max(abs(a), abs(b)))


def mc_sourced(sym):
    """(sym, qe) pairs already filled FROM MONEYCONTROL by this campaign.

    They must be EXCLUDED from the evidence set. A cell written from MC agrees with MC by
    construction, so counting it as an agreeing neighbour lets the gate confirm itself: fill one
    quarter, and it votes to fill the next. Measured 2026-08-26 -- with these left in, a re-run of
    the batch-6 gate over an already-filled store staged 43 further cells whose "agreement" was
    partly its own output."""
    try:
        led = json.load(open(os.path.join(HERE, "_mc_reads.json"), encoding="utf8"))
    except Exception:
        return set()
    return {(s, int(qe)) for s, cells in led.items() for qe in cells}


def verdicts(srev, q, lo=None, hi=None, exclude=()):
    """-> {field: {qe: bool}} -- does MC's field reproduce our stored revStd for that quarter."""
    out = {"rev_ops": {}, "rev_total": {}}
    for qe_s, rr in srev.items():
        qe = int(qe_s)
        if lo is not None and not (lo <= qe < hi):
            continue
        if qe in exclude:
            continue
        st, mc = rr[0], q.get(qe)
        if st is None or not mc:
            continue
        for f in out:
            v = mc.get(f)
            if v is not None:
                out[f][qe] = close(st, v)
    return out


def window_conv(vd, qe, win, minn):
    """Per-CELL convention verdict: the field whose stored overlaps within +/-`win` CALENDAR
    YEARS of `qe` number at least `minn` and ALL agree. -> (field, n) or (None, 0)."""
    y = qe // 10000
    for f in ("rev_ops", "rev_total"):
        nb = [ok for q2, ok in vd[f].items() if q2 != qe and abs(q2 // 10000 - y) <= win]
        if len(nb) >= minn and all(nb):
            return f, len(nb)
    return None, 0


def main():
    av = sys.argv
    gaps_path = av[av.index("--gaps") + 1]
    out_path = av[av.index("--emit") + 1]
    gate = av[av.index("--gate") + 1] if "--gate" in av else "window"
    win = int(av[av.index("--win") + 1]) if "--win" in av else 2
    min_agree = int(av[av.index("--min-agree") + 1]) if "--min-agree" in av \
        else (5 if gate == "window" else 3)
    only = set(av[av.index("--only") + 1].split(",")) if "--only" in av else None

    gaps = json.load(open(gaps_path))
    mcdone = mc_sourced(None)
    rev = json.load(open(os.path.join(ROOT, "docs", "sf_revop.json")))
    fund = json.load(open(os.path.join(ROOT, "docs", "sf_fundamentals.json")))

    emit, report = {}, {"gate": gate, "win": win, "min_agree": min_agree, "per_sym": {}}
    tally = collections.Counter()
    for sym in sorted(gaps):
        if only and sym not in only:
            continue
        q, note = A.mc_quarters(sym, con=False)
        srev = rev.get(sym) or {}
        fmap = {r[0]: r for r in fund.get(sym, [])}
        # fin (financial-format) is DELIBERATELY NOT ASSERTED by this route.
        # It used to be inherited symbol-wide ("any stored row has fin=1 -> all my cells get
        # fin=1"), which was wrong twice over and caused a real overwrite (BALRAMCHIN 2005-03,
        # stored fin=0 -> 1; _apply_reads sets cell[6]=1 unconditionally when the read says 1,
        # so an asserted 1 is NOT fill-only and can clobber a stored 0):
        #   * fin is a per-FILING property, not a company constant -- build_revop.py sets it from
        #     the XBRL carrying InterestEarned / NetPremiumIncome / PremiumEarned, so it legitimately
        #     varies quarter to quarter and route to route.
        #   * the stored flag is unreliable store-wide, so inheriting it PROPAGATES contamination.
        #     Measured 2026-08-26: BALRAMCHIN (sugar) carries fin=1 on 63 of its 100 rows; and even
        #     in the reliable post-2018 XBRL era the majority vote calls MOTILALOFS (a broker)
        #     NOT financial and BALRAMCHIN financial on 1 row. There is no clean signal to inherit.
        # MC's feed says nothing about filing format, so this route reports 0 = "no evidence",
        # which is exactly what _apply_reads already defaults an empty cell to, and which can
        # never overwrite a stored value.
        finflag = 0
        ex = {qe for (s2, qe) in mcdone if s2 == sym}   # never let our own MC fills vote
        vd_all = verdicts(srev, q, exclude=ex)        # every quarter -- for the window gate
        vd_era = verdicts(srev, q, LO, HI, exclude=ex)  # 2002-2008 only -- for the era gate
        agree, disagree = collections.Counter(), collections.Counter()
        for f in ("rev_ops", "rev_total"):
            for ok in vd_era[f].values():
                (agree if ok else disagree)[f] += 1
        era_conv = next((f for f in ("rev_ops", "rev_total")
                         if agree[f] >= min_agree and disagree[f] == 0), None)
        staged = 0
        for qe in gaps[sym]:
            mc = q.get(qe)
            if not mc:
                tally["no_mc_quarter"] += 1
                continue
            if gate == "window":
                conv, nag = window_conv(vd_all, qe, win, min_agree)
                why = "window +/-%dyr agree=%d/disagree=0" % (win, nag)
            else:
                conv = era_conv
                nag = agree[era_conv] if era_conv else 0
                why = "era 2002-2008 agree=%d/disagree=0" % nag
            if conv is None or mc.get(conv) is None:
                tally["no_conv_or_field"] += 1
                continue
            row = fmap.get(qe)
            sp = row[1] if row else None
            if not anchor_ok(sp, mc.get("pat_total")):
                tally["anchor_preview_fail"] += 1
                continue
            emit.setdefault(sym, {})[str(qe)] = {
                "basis": "std", "rev": mc[conv], "pat_seen": mc["pat_total"], "fin": finflag,
                "src": ("moneycontrol std %s=%s pat=%s (deep feed, as-filed; conv=%s gated by %s)"
                        " [pre2009 2026-08-26]"
                        % (conv, mc[conv], mc["pat_total"], conv, why))}
            staged += 1
            tally["staged"] += 1
        if staged or era_conv:
            report["per_sym"][sym] = {"era_conv": era_conv, "agree": dict(agree),
                                      "disagree": dict(disagree), "staged": staged,
                                      "gap": len(gaps[sym]), "note": note}
    json.dump(emit, open(out_path, "w"), indent=1, sort_keys=True)
    json.dump(report, open(os.path.join(HERE, "_pre2009_mc_report.json"), "w"), indent=1, sort_keys=True)
    print("staged %d cells across %d symbols -> %s" % (tally["staged"], len(emit), out_path))
    print("gate=%s win=%d min_agree=%d" % (gate, win, min_agree))
    print("blocked: %s" % dict(tally))


if __name__ == "__main__":
    main()
