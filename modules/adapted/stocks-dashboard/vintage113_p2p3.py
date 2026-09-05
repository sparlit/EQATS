# -*- coding: utf-8 -*-
"""§113f — run §113a's comparative-column route over §112b's P2/P3 residue.

WHY. §112d queued 69 consolidated cells (P2 "identity reconciles to neither" 34, P3 "identity cannot
separate" 35) for the vision rung. §113a showed the text route was closed too early. 16 of the 69
were already read in §113; this walks the other 53.

WHAT IS DIFFERENT FROM §113. In the §111i population every disputed cell was live on the HEAL, so
"the filing backs the store" and "the live value is wrong" were the same statement. Here they are
not: 30 of the 53 are live on the heal and 23 on the pre-heal value, so the read has to be compared
against WHAT IS LIVE, per cell. Verdicts:

    CONFIRMS-LIVE   the filing's owners figure is what the payload serves -> nothing to do
    CONTRADICTS     the filing says the OTHER candidate -> the live value is wrong
    THIRD-VALUE     the filing says neither -> the live value is wrong and so is the ledger's target
    NO-DOCUMENT     no readable owners row -> stays in the queue, vision rung

RUN: python3 -X utf8 vintage113_p2p3.py
"""
import json
import os
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
W = os.environ["V111_WORK"]
sys.path.insert(0, HERE)
import vintage111_adjudicate as A  # noqa: E402

SCALEF = {"crore": 1.0, "lakh": 0.01, "million": 0.1, "thousand": 1e-5}


def main():
    reads = json.load(open(os.path.join(W, "_vintage111_reads.json"), encoding="utf-8"))
    sel = json.load(open(os.path.join(W, "declined67.json"), encoding="utf-8"))
    fund = json.load(open(os.path.join(ROOT, "docs", "sf_fundamentals.json"), encoding="utf-8"))
    own = json.load(open(os.path.join(HERE, "_reattr_owners.json"), encoding="utf-8"))

    out, c = {}, Counter()
    for k, v in sorted(sel.items()):
        f = v["fix"]
        sym, qe = f["sym"], int(f["qe"])
        ck = "%s|%d" % (sym, qe)
        row = next((r for r in fund.get(sym, []) if r[0] == qe), None)
        live = row[3] if row and len(row) > 3 else None
        # vintage111_read.py names the two candidates "store"/"heal"; this population has no
        # single "store" side (30 of 53 are live on the heal), so they are renamed to the ledger's
        # own field names and the comparison is against the LIVE value instead.
        cands = {"was": f["was"], "fixed": f["fixed"]}
        NAME = {"store": "was", "heal": "fixed"}
        hits = {"was": [], "fixed": []}
        for fn, d in sorted(reads.get(ck, {}).items()):
            for h in d.get("hits", []):
                if (h["kind"] not in ("owners", "owners~ocr", "owners=tot-nci")
                        or h["block"] not in ("profit", "?")):
                    continue
                anc = A.anchor_cols(h["row"], SCALEF[h["scale"]], qe, d.get("ann"), fund, sym)
                if any(a[2] == h["ix"] for a in anc):
                    continue                      # the hit sits in a column we already know
                hits[NAME[h["cand"]]].append({"doc": fn, "win": d.get("win"), "page": h["page"],
                                        "page_value": h["as_cr"],
                                        "kind": h["kind"], "label": h["label"], "row": h["row"],
                                        "scale": h["scale"], "ix": h["ix"],
                                        "anchors": [a[0] for a in anc],
                                        "tier": "A" if len(anc) >= 2 else
                                                ("B" if len(anc) == 1 else "C")})
        txt = sum(1 for d in reads.get(ck, {}).values() if d.get("text_pages", 0) >= 2)
        side = None
        if hits["was"] and not hits["fixed"]:
            side = "was"
        elif hits["fixed"] and not hits["was"]:
            side = "fixed"
        # ★ REPORT WHAT THE PAGE SAYS, NOT WHICH CANDIDATE IT RESEMBLES. The locator matches within
        # 0.35 cr (deliberately generous, to absorb 2dp feed rounding), so "the filing says X" was
        # really "the page carries something within 0.35 of X" — on a 7 cr cell that is 5%.
        # CLEDUCATE's page reads 7.28 against a live 7.03 and was reported as CONFIRMS-LIVE.
        page_vals = sorted({h["page_value"] for h in hits.get(side or "was", [])}) if side else []
        if side is None:
            verdict = "BOTH-SIDES-HIT" if (hits["was"] and hits["fixed"]) else (
                "NO-DOCUMENT" if txt == 0 else "NO-OWNERS-ROW")
        else:
            reads_val = page_vals[0] if len(page_vals) == 1 else None
            if reads_val is None:
                verdict = "PAGE-VALUES-DISAGREE"
            elif live is not None and abs(live - reads_val) < 0.02:
                verdict = "CONFIRMS-LIVE"
            elif abs(reads_val - cands[side]) < 0.02:
                verdict = "CONTRADICTS"
            else:
                verdict = "THIRD-VALUE"
        best = max((h["tier"] for h in hits.get(side or "was", [])), default="-")
        out[k] = {"sym": sym, "qe": qe, "pri": f.get("_pri"), "live": live,
                  "live_side": f.get("_live"), "was": f["was"], "fixed": f["fixed"],
                  "filing_says": (page_vals[0] if len(page_vals) == 1 else page_vals) if side else None,
                  "near_candidate": cands[side] if side else None, "side": side,
                  "verdict": verdict, "tier": best, "xbrl_own": own.get(ck),
                  "docs": len(reads.get(ck, {})), "text_docs": txt,
                  "hits_was": hits["was"], "hits_fixed": hits["fixed"]}
        c[verdict] += 1
    json.dump(out, open(os.path.join(W, "_vintage113_p2p3_verdicts.json"), "w"), indent=1)
    print("cells %d   %s\n" % (len(out), dict(c)))
    print("%-11s %-9s %-3s %-6s %-10s %-10s %-10s %-4s %s"
          % ("SYM", "QE", "P", "live@", "live", "was", "fixed", "tier", "verdict"))
    for k, x in sorted(out.items(), key=lambda t: (t[1]["verdict"], t[0])):
        print("%-11s %-9s %-3s %-6s %-10s %-10s %-10s %-4s %s"
              % (x["sym"], x["qe"], x["pri"], x["live_side"], x["live"], x["was"], x["fixed"],
                 x["tier"], x["verdict"]))


if __name__ == "__main__":
    main()
