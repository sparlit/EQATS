# -*- coding: utf-8 -*-
"""§109e BY-PRODUCTS — adjudicate, and propose only what the gate lets through.

WHAT THIS CAMPAIGN MEASURED FIRST (each number is in the run log, none is assumed):

1. NSE's SINGLE row is not automatically the as-filed vintage.  Among by-product cells 82/518 have
   their only NSE row filed >365 days after the quarter (control: 108/2863 = 3.8%), and in every
   such case checked BSE detres backs the STORE.  A row filed long after the period is a
   re-filing — it cannot arbitrate what was filed originally.  GATE: NSE row <= 180d after qe.

2. MC's deep feed serves the RESTATED vintage 42.1% of the time (102 of 242 reached cells of the
   257 §109 heals whose as-filed answer is known).  So:
     * MC == NSE-as-filed  CONFIRMS the as-filed value — either MC is on that vintage, or MC is on
       a restatement that did not change the number, and then the number is right either way.
     * MC == the STORE is AMBIGUOUS — the store may be right, or store and MC may both be on a
       restatement NSE does not list.  It never confirms a heal, and it always blocks one.

3. The consolidated bottom line on the archive's page ("Net Profit after taxes, minority interest
   and share of profit of associates") is NOT the owners' figure our store keeps.  BAJAJHLDNG
   Mar-2016: page P=92.64, associates=+471.14 -> page prints -378.50 while store and MC both hold
   563.78 = P + A; ASHOKA Dec-2015 page -31.54 vs store/MC 13.26 = P + M + A.  So a con cell needs
   MC to AGREE with the page before the page can be believed.

THE GATE (§109d, unchanged in spirit — evidence AND no available reader may contradict):
   target   = NSE's as-filed value for the cell's own basis
   timely   = that row filed <= 180d after quarter end
   evidence = detres agrees with the target (std) OR MC agrees with the target (either basis)
   veto     = ANY available reader sits on the STORE instead
   material = the store is outside near() of the target (0.35 cr / 0.5%)

OUT: _vintage109_adjud.json + a proposals block ready for the ledgers.
"""
import json, os
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
TIMELY_DAYS = 180
NEAR_ABS, NEAR_REL = 0.35, 0.005
TIGHT_ABS, TIGHT_REL = 0.35, 0.005


def near(a, b, ab=NEAR_ABS, rl=NEAR_REL):
    return a is not None and b is not None and abs(a - b) <= max(ab, abs(b) * rl)


def agree(a, b, ab=2.0, rl=0.03):
    """§42's own cell tolerance — two readers of the same statement, rounding differently."""
    return a is not None and b is not None and abs(a - b) <= max(ab, abs(b) * rl)


def mc_pat(r):
    m = r.get("mc") or {}
    if r["basis"] == "con" and m.get("pat_own") is not None:
        return m.get("pat_own")
    return m.get("pat_total")


def adjudicate(r):
    """-> (verdict, evidence[], note)"""
    st, tgt, basis = r["stored"], r["nse_pat"], r["basis"]
    det = r["detres_pat"] if basis == "std" else None
    mc = mc_pat(r)
    gap = r["gap_qe_to_nsefiled"]

    if st is None or tgt is None:
        return "UNREADABLE", [], "no stored value or no NSE reading"
    if near(st, tgt):
        return "STORE-CORRECT", ["NSE"], "store already equals NSE's as-filed value"

    # --- vetoes, cheapest first -------------------------------------------------
    if det is not None and near(det, st):
        return "STORE-BACKED", ["DETRES"], "BSE detres (as-filed by construction, §42) reads the stored value"
    if gap is None or gap > TIMELY_DAYS:
        if mc is not None and near(mc, st):
            return "STORE-BACKED", ["MC"], ("NSE's only row was filed %s days after the quarter — a "
                                            "re-filing, not the as-filed vintage — and MC reads the stored value" % gap)
        return "NSE-ROW-IS-LATE", [], ("NSE's only row for this period was filed %s days after quarter "
                                       "end; it cannot arbitrate the as-filed value" % gap)
    if mc is not None and near(mc, st):
        return "MC-BACKS-STORE", ["MC"], ("MC reads the stored value; MC serves the restated vintage "
                                          "42%% of the time, so this is ambiguous, not a clearance")

    # --- evidence ---------------------------------------------------------------
    ev = []
    if det is not None and near(det, tgt, TIGHT_ABS, TIGHT_REL):
        ev.append("DETRES")
    if mc is not None and near(mc, tgt, TIGHT_ABS, TIGHT_REL):
        ev.append("MC")
    if not ev:
        if det is None and mc is None:
            return "NO-SECOND-READER", [], "NSE alone; neither detres nor MC has a reading for this cell"
        return "READERS-DISAGREE", [], ("no reader reproduces either the store or NSE "
                                        "(detres=%s, mc=%s)" % (det, mc))
    # ★ A READER ON A THIRD VALUE CONTRADICTS TOO. "No reader may contradict" was first read as
    # "no reader sits on the store", which lets a cell be healed towards a target an independent
    # reader rejects outright — ASSAMCO Mar-2017: NSE and MC both -45.63, detres -49.81, store
    # -48.52. Nothing sits on the store, yet detres refuses the target. Queue it for a fourth
    # reader instead of picking the majority. (§109d's own hole, one step further out.)
    # READER PRECEDENCE, and it is not a vote.
    #   detres is as-filed BY CONSTRUCTION (§42) — its dissent always vetoes.
    #   MC is an aggregator that serves a RESTATED vintage 42% of the time, so a third value from
    #   MC is often just another vintage, not a refutation: DLF Mar-2016 has MC on pat 1441.53 AND
    #   rev 1968.15, and 1968.15 is exactly the revenue our store held — a coherent restated row,
    #   beside two EXCHANGE readers that agree to the paisa (NSE page 1088.94, BSE detres 1088.94).
    #   So MC's dissent cannot veto a target BOTH exchange readers reproduce; anywhere else it does.
    if det is not None and not agree(det, tgt):
        return "READERS-DISAGREE", [], ("BSE detres reads %s — it reproduces neither the stored %s "
                                        "nor the as-filed %s; detres is as-filed by construction, "
                                        "so this needs a further reader" % (det, st, round(tgt, 2)))
    two_exchange = det is not None and near(det, tgt, 0.02, 0.0002)
    if mc is not None and not agree(mc, tgt) and not two_exchange:
        return "READERS-DISAGREE", [], ("MC reads %s — neither the stored %s nor the as-filed %s, "
                                        "and no second EXCHANGE reader confirms the target"
                                        % (mc, st, round(tgt, 2)))
    return "HEAL", ev, ""


def adjudicate_pair(r):
    """RULE B — NSE could not arbitrate (late row, or it contradicts both readers), but BSE detres
    and MC agree with EACH OTHER against the store. detres is as-filed by construction (§42); MC
    is on the as-filed vintage or on a restatement that did not move the number — either way the
    pair fixes the as-filed value. Standalone only: detres does not serve consolidated (§42).
    """
    if r["basis"] != "std":
        return None
    det, mc, st = r["detres_pat"], mc_pat(r), r["stored"]
    if det is None or mc is None or st is None:
        return None
    if not near(det, mc, TIGHT_ABS, TIGHT_REL):
        return None
    if near(det, st) or near(mc, st):
        return None
    # NSE may only be set aside when it CANNOT speak — a late re-filing, or a page whose PAT line
    # did not parse. A TIMELY, READABLE NSE row that disagrees with the pair is a contradiction,
    # not a silence: CUBEXTUB Mar-2017 (NSE 5.07 filed qe+79d vs detres 0.21 / MC 0.21) is a
    # three-way split and belongs in the queue.
    nse, gap = r["nse_pat"], r["gap_qe_to_nsefiled"]
    unreadable = nse is None or abs(nse) <= 0.0049
    late = gap is None or gap > TIMELY_DAYS
    if not (unreadable or late or agree(nse, det)):
        return None
    return round(det, 2)


def main():
    b = json.load(open(os.path.join(HERE, "_vintage109_byprod.json")))["cells"]
    out, cnt, bycls = {}, Counter(), defaultdict(Counter)
    for k, r in sorted(b.items()):
        v, ev, note = adjudicate(r)
        r.pop("pair_target", None)
        if v in ("NSE-ROW-IS-LATE", "READERS-DISAGREE", "NO-SECOND-READER", "MC-BACKS-STORE"):
            pt = adjudicate_pair(r)
            if pt is not None and v != "MC-BACKS-STORE":
                r["pair_target"], v, ev = pt, "HEAL-PAIR", ["DETRES", "MC"]
                note = ("NSE's row could not arbitrate (%s); BSE detres and MC agree on %s "
                        "against the stored %s" % (note or v, pt, r["stored"]))
        r["verdict"], r["evidence"], r["note"] = v, ev, note
        out[k] = r
        cnt[v] += 1
        bycls[r["cls"]][v] += 1
    print("VERDICTS over %d by-product cells" % len(out))
    for v, n in cnt.most_common():
        print("   %-22s %4d" % (v, n))
    print("\nby re-derived class:")
    for c in sorted(bycls):
        print("  %-44s %s" % (c, dict(bycls[c].most_common())))
    heals = [r for r in out.values() if r["verdict"] in ("HEAL", "HEAL-PAIR")]
    print("\nHEAL: %d cells (%s) over %d symbols; evidence %s"
          % (len(heals), dict(Counter(r["basis"] for r in heals)),
             len({r["sym"] for r in heals}),
             dict(Counter("+".join(r["evidence"]) for r in heals))))
    json.dump({"_doc": "§109e by-product adjudication", "cells": out},
              open(os.path.join(HERE, "_vintage109_adjud.json"), "w"), indent=1)
    print("wrote _vintage109_adjud.json")


if __name__ == "__main__":
    main()
