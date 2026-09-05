# -*- coding: utf-8 -*-
"""§111i — adjudicate the 59 disputed CON cells from the primary reads, and say WHY for each.

INPUTS (all measured, none assumed)
  _vintage111_reads.json   candidate hits located on the filings themselves (rung 3, BSE PDFs)
  declined67.json          the disputed heals (ledger `was` = pre-heal store, `fixed` = the heal)
  _vintage109_adjud.json   the 518-cell verdict record: NSE page PAT, MC owners/total, detres
  page_components.json     the NSE archive page's own component rows for these cells
  _reattr_owners.json      the owners-line reader, where it reaches this window

THE TEST. Our con slot holds owners-attributable profit. So for each cell:
  * a hit on an OWNERS row, in the PROFIT block (not the comprehensive one), at the target
    quarter's column, is DECISIVE for whichever candidate it lands on;
  * a hit on a TOTAL row is decisive the other way — it says that candidate is the total, and the
    total is not what this slot stores;
  * owners + NCI == total on the same rows is the internal anchor that the three rows really are
    one split (§111d's BAJAJHLDNG case is precisely a page where they are not).

Verdicts: STORE-CORRECT (revert the heal), HEAL-CORRECT (leave it), NEEDS-VISION (the filing on
record is a scan — the honest answer is a named next rung, never "unfillable", §57a).

OUT: _vintage111_verdicts.json
RUN: python3 -X utf8 vintage111_adjudicate.py [--verbose SYM]
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SP = os.environ.get("V111_WORK", HERE)
READS = os.path.join(SP, "_vintage111_reads.json")
DECL = os.path.join(SP, "declined67.json")
COMP = os.path.join(SP, "page_components.json")
ADJ = "/Users/dhruvan/stocks-wt/vintage109-evidence/_vintage109_adjud.json"
OUT = os.path.join(SP, "_vintage111_verdicts.json")


def near(a, b, abs_t=0.35, rel_t=0.006):
    return a is not None and b is not None and abs(a - b) <= max(abs_t, abs(b) * rel_t)


def prevq(qe):
    y, md = qe // 10000, qe % 10000
    return {331: (y - 1) * 10000 + 1231, 630: y * 10000 + 331,
            930: y * 10000 + 630, 1231: y * 10000 + 930}[md]


def anchor_cols(row, scale, qe, ann, fund, sym):
    """★ THE COLUMN MAP, CONFIRMED BY THE COLUMNS WE ALREADY KNOW (§59d tier A).

    A candidate value sitting on the right ROW is not yet an answer: it may be sitting in the wrong
    COLUMN, and a filing prints five of them (this quarter, the preceding quarter, the year-ago
    quarter, and two year-ended columns) — memory: feedback-same-date-different-column-role. But
    every column except the disputed one is a quarter whose consolidated value we ALREADY hold, so
    the row can validate its own map: TRIVENI's Mar-2018 statement reads
    [-10209, 6007, 6046, 11914, 25295] lakh, and -102.09 and 60.07 are exactly our stored Mar-2018
    and Dec-2017 con cells. Two independent anchors on one row fix the map, and then the remaining
    quarter column is decisive.

    Returns [(quarter, stored_value, index_in_row)] for every OTHER quarter this row reproduces.
    """
    q0 = quarter_of(ann)
    cands = []
    for q in (q0, prevq(q0), q0 - 10000 if q0 else 0, prevq(qe), qe - 10000):
        if q and q != qe and q not in [c[0] for c in cands]:
            r = next((x for x in fund.get(sym, []) if x[0] == q), None)
            v = r[3] if r and len(r) > 3 else None
            if v is not None:
                cands.append((q, v))
    hit = []
    for q, v in cands:
        for i, raw in enumerate(row):
            if near(raw * scale, v):
                hit.append((q, v, i))
                break
    return hit


def quarter_of(ann):
    """The quarter a filing dated `ann` is reporting (Indian filing calendar).

    A May-2018 filing reports the quarter ended 31-Mar-**2018**. An earlier version of this said
    (y-1), i.e. Mar-2017 — which for these Mar-2018 documents made the anchor candidate set equal
    to the TARGET quarter, so no anchor ever matched and thirteen genuinely tier-A reads were all
    labelled tier C. The anchors were right; the calendar was wrong.
    """
    if not ann:
        return 0
    y, m = int(ann) // 10000, (int(ann) // 100) % 100
    if 4 <= m <= 6:
        return y * 10000 + 331
    if 7 <= m <= 9:
        return y * 10000 + 630
    if 10 <= m <= 12:
        return y * 10000 + 930
    return (y - 1) * 10000 + 1231


def main():
    reads = json.load(open(READS, encoding="utf-8")) if os.path.exists(READS) else {}
    fund = json.load(open(os.path.join(os.path.dirname(HERE), "docs", "sf_fundamentals.json"),
                          encoding="utf-8"))
    SCALEF = {"crore": 1.0, "lakh": 0.01, "million": 0.1, "thousand": 1e-5}
    sel = json.load(open(DECL, encoding="utf-8"))
    comp = json.load(open(COMP, encoding="utf-8")) if os.path.exists(COMP) else {}
    adj = json.load(open(ADJ, encoding="utf-8"))["cells"]
    own = json.load(open(os.path.join(HERE, "_reattr_owners.json"), encoding="utf-8"))
    verb = sys.argv[sys.argv.index("--verbose") + 1] if "--verbose" in sys.argv else None

    out = {}
    for k, v in sorted(sel.items()):
        f = v["fix"]
        if f["basis"] != "con":
            continue
        ck = "%s|%s" % (f["sym"], f["qe"])
        r = reads.get(ck, {})
        store, heal = f["was"], f["fixed"]
        # every OWNERS-row hit in a PROFIT block, per candidate
        ev = {"store": [], "heal": []}   # plus "_anchored": hits landing in a KNOWN other column
        for fn, d in sorted(r.items()):
            for h in d.get("hits", []):
                if (h["kind"] in ("owners", "owners~ocr", "owners=tot-nci")
                        and h["block"] in ("profit", "?")):
                    anc = anchor_cols(h["row"], SCALEF[h["scale"]], int(f["qe"]), d.get("ann"),
                                      fund, f["sym"])
                    # ★ A HIT IN AN ANCHORED COLUMN IS A COINCIDENCE, NOT THE ANSWER. TV18BRDCST's
                    # Jun-2018 filing prints owners [-1248, -298, -1199, 862] lakh and 8.62 looks
                    # like the store's 8.39 — but the first three columns reproduce our Jun-2018,
                    # Mar-2018 and Jun-2017 cells exactly, so column 4 is YEAR-ENDED Mar-2018, not
                    # the Mar-2017 quarter. The anchors that prove the map also disqualify the hit.
                    if any(a[2] == h["ix"] for a in anc):
                        ev.setdefault("_anchored", []).append(
                            {"doc": fn, "cand": h["cand"], "ix": h["ix"], "anchors": anc})
                        continue
                    ev[h["cand"]].append({"doc": fn, "win": d.get("win"), "page": h["page"],
                                          "scale": h["scale"], "ix": h["ix"], "n": h["nvals"],
                                          "block": h["block"], "label": h["label"], "row": h["row"],
                                          "kind": h["kind"], "basis": h.get("basis"),
                                          "anchors": anc, "tier": "A" if len(anc) >= 2 else
                                          ("B" if len(anc) == 1 else "C")})
        tot = {"store": [], "heal": []}
        for fn, d in sorted(r.items()):
            for h in d.get("hits", []):
                if h["kind"] in ("total",) and h["block"] in ("profit", "?"):
                    tot[h["cand"]].append({"doc": fn, "win": d.get("win"), "page": h["page"],
                                           "label": h["label"], "row": h["row"]})
        a = adj.get(k, {})
        mc = a.get("mc") or {}
        docs = len(r)
        text_docs = sum(1 for d in r.values() if d.get("text_pages", 0) >= 2)
        rec = {"sym": f["sym"], "qe": f["qe"], "store": store, "heal": heal,
               "mc_own": mc.get("pat_own"), "mc_tot": mc.get("pat_total"),
               "nse_pat": a.get("nse_pat"), "detres": a.get("detres_pat"),
               "xbrl_own": own.get(ck), "v109": a.get("verdict"),
               "page_tot": (comp.get(k) or {}).get("tot"),
               "page_asso": (comp.get(k) or {}).get("asso"),
               "page_min": (comp.get(k) or {}).get("min"),
               "docs": docs, "text_docs": text_docs,
               "owners_hits_store": ev["store"], "owners_hits_heal": ev["heal"],
               "total_hits_store": tot["store"], "total_hits_heal": tot["heal"]}
        if ev["store"] and not ev["heal"]:
            rec["verdict"] = "STORE-CORRECT"
        elif ev["heal"] and not ev["store"]:
            rec["verdict"] = "HEAL-CORRECT"
        elif ev["store"] and ev["heal"]:
            rec["verdict"] = "OWNERS-ROW-BOTH"      # both values sit on an owners row somewhere
        elif docs == 0:
            rec["verdict"] = "NOT-FETCHED"
        elif text_docs == 0:
            rec["verdict"] = "NEEDS-VISION"
        else:
            rec["verdict"] = "NO-OWNERS-ROW-FOUND"
        out[k] = rec
    json.dump(out, open(OUT, "w"), indent=1)
    from collections import Counter
    c = Counter(x["verdict"] for x in out.values())
    print("cells %d   %s" % (len(out), dict(c)))
    for k, x in sorted(out.items()):
        flag = {"STORE-CORRECT": "STORE", "HEAL-CORRECT": "HEAL "}.get(x["verdict"], "?????")
        tiers = "".join(sorted({h["tier"] for h in x["owners_hits_store"]})) or "-"
        tierh = "".join(sorted({h["tier"] for h in x["owners_hits_heal"]})) or "-"
        print("  %-11s %-9s %s store=%-10s heal=%-10s docs=%d/txt%d  own(s)=%d[%s] own(h)=%d[%s]"
              " tot(s)=%d tot(h)=%d  %s"
              % (x["sym"], x["qe"], flag, x["store"], x["heal"], x["docs"], x["text_docs"],
                 len(x["owners_hits_store"]), tiers, len(x["owners_hits_heal"]), tierh,
                 len(x["total_hits_store"]), len(x["total_hits_heal"]), x["verdict"]))
        if verb and x["sym"] == verb:
            for nm in ("owners_hits_store", "owners_hits_heal", "total_hits_store", "total_hits_heal"):
                for h in x[nm]:
                    print("        %-18s %s" % (nm, json.dumps(h)))


if __name__ == "__main__":
    main()
