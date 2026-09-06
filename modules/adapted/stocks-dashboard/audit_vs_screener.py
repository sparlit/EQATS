# -*- coding: utf-8 -*-
"""FULL AUDIT: every stored rev/PAT cell against screener.in, for every company screener covers.

User, 2026-08-06: *"i seriously have a doubt now. many of my data u must have filled wrong. i want
a full screener test to check if all our data matches them"*. Fair, and prompted by a mistake of
mine: I called two TATACAP standalone cells suspect because their neighbours "matched screener
exactly" — when those neighbours had been WRITTEN FROM screener by an earlier session
(scripts/screener_rev_fills.json). They agreed with screener because they came from it.

THE CIRCULARITY IS THE POINT OF THIS TOOL. 234 cells across 70 companies in this repo are
screener-sourced. Comparing those to screener is self-confirmation, and any gate that corroborates
a new read against stored neighbours (screener_gate, apply_sweep G3) is exposed wherever the
neighbours are screener-derived. So every comparison here is tagged `independent` (our value came
from a filing/XBRL) or `circular` (our value came from screener), and only INDEPENDENT agreements
count as corroboration.

CLASSIFICATION, per company+basis — a difference is not automatically our defect:

  OK          >=3 independent comparisons, zero disagreements.
  ISOLATED    Most agree, 1-3 disagree. THIS is the interesting class: a genuine per-cell suspect,
              the SWANCORP Mar-2024 shape (7.91 vs 1398 with every neighbour exact to the paisa).
  SYSTEMATIC  Most or all disagree. NOT a per-cell defect — it means the two sides are measuring
              different things: a different entity (TMPV = demerged PV company vs our legacy Tata
              Motors incl. JLR), a different basis, or a definitional gap (screener's finance-layout
              `Revenue` row is total income, ours is revenue from operations). Reported separately
              and never counted as bad data.
  RESTATED    Disagreements cluster in whole financial years — screener carries the restated total
              while our quarters are as-reported (ACC FY2023, AARTIIND FY2022 = Pharmalabs demerger,
              ADANIENT FY2024). Also not a defect.
  THIN        Fewer than 3 comparable quarters; no verdict claimed.

Writes /tmp/screener_audit.json and prints the ISOLATED cells, which is the actionable list.

  python -X utf8 scripts/fill2020_tools/audit_vs_screener.py [--limit N] [--resume]
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, SCRIPTS)
import screener_fetch as SF                                       # noqa: E402

OUT = "/tmp/screener_audit.json"
TOL = 0.01                      # 1% — screener rounds to whole crore
MIN_CMP = 3


def screener_sourced():
    """{(sym, qe, field)} for cells whose stored value CAME from screener — circular to compare."""
    out = set()
    p = os.path.join(SCRIPTS, "screener_rev_fills.json")
    if os.path.exists(p):
        for k, v in json.load(open(p)).items():
            if "|" not in k or not isinstance(v, dict):
                continue
            sym, qe = k.split("|", 1)
            if "std" in v:
                out.add((sym, qe, "revS"))
            if "con" in v:
                out.add((sym, qe, "revC"))
    for name in ("named_rev_cell_fills.json", "screener_rev_fills.json", "sweep_rev_fills.json"):
        p = os.path.join(SCRIPTS, name)
        if not os.path.exists(p):
            continue
        for k, v in json.load(open(p)).items():
            if not isinstance(v, dict) or k.count("|") < 1:
                continue
            if v.get("precision") == "crore-rounded" or "screener" in str(v.get("src", "")).lower():
                parts = k.split("|")
                if len(parts) == 3:
                    out.add((parts[0], parts[1], parts[2]))
                elif len(parts) == 2:
                    for f in ("revS", "revC"):
                        if f in v:
                            out.add((parts[0], parts[1], f))
    return out


def main():
    limit = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else 10 ** 9
    revop = json.load(open(os.path.join(ROOT, "docs", "sf_revop.json")))
    circ = screener_sourced()
    done = {}
    if "--resume" in sys.argv and os.path.exists(OUT):
        done = json.load(open(OUT))

    syms = sorted(revop)
    n = 0
    for sym in syms:
        if n >= limit:
            break
        if all("%s|%s" % (sym, b) in done for b in ("revS", "revC")):
            continue
        n += 1
        for field, con, slot in (("revS", False, 0), ("revC", True, 1)):
            key = "%s|%s" % (sym, field)
            if key in done:
                continue
            try:
                sq = SF.quarters(sym, con=con)
            except Exception as e:
                done[key] = {"verdict": "FETCH-FAIL", "err": repr(e)[:60]}
                continue
            if not sq:
                done[key] = {"verdict": "NO-SCREENER"}
                continue
            label = next((L for L in ("Sales", "Revenue")
                          if any(L in r for r in sq.values())), None)
            if not label:
                done[key] = {"verdict": "NO-ROW"}
                continue
            agree, disagree, circular = [], [], 0
            for dk, row in sq.items():
                qe = dk.replace("-", "")
                mine = (revop.get(sym) or {}).get(qe)
                v = mine[slot] if mine and len(mine) > slot else None
                t = row.get(label)
                if v is None or t is None:
                    continue
                if (sym, qe, field) in circ:
                    circular += 1
                    continue                       # our value came FROM screener: proves nothing
                if abs(v - t) <= max(1.0, abs(t) * TOL):
                    agree.append(qe)
                else:
                    disagree.append({"qe": qe, "ours": v, "screener": t,
                                     "diff_pct": round(100.0 * (v - t) / t, 2) if t else None})
            # ---- ANNUAL ARM: screener's quarterly table only reaches ~13 quarters back, so every
            # cell before ~2023 is invisible to the comparison above. Its ANNUAL P&L goes back 12
            # years, and our four stored quarters must sum to it. A mismatched FY localises at
            # least one bad cell to that year even though screener cannot show the quarter itself.
            # User asked for full coverage from 2020-01-01, and this is the only route that has it.
            annual = []
            try:
                sa = SF.annuals(sym, con=con)
            except Exception:
                sa = {}
            alab = next((L for L in ("Sales", "Revenue") if any(L in r for r in sa.values())),
                        None) if sa else None
            if alab:
                for dk, arow in sa.items():
                    fy = int(dk.replace("-", ""))
                    if fy % 10000 != 331 or fy < 20200331:
                        continue
                    y = fy // 10000
                    qs = [(y - 1) * 10000 + 630, (y - 1) * 10000 + 930,
                          (y - 1) * 10000 + 1231, y * 10000 + 331]
                    vals, circ_fy = [], False
                    for q in qs:
                        r = (revop.get(sym) or {}).get(str(q))
                        v = r[slot] if r and len(r) > slot else None
                        if v is None:
                            vals = None
                            break
                        if (sym, str(q), field) in circ:
                            circ_fy = True
                        vals.append(v)
                    tot = arow.get(alab)
                    if not vals or tot is None:
                        continue
                    s = sum(vals)
                    ok = abs(s - tot) <= max(2.0, abs(tot) * TOL)
                    annual.append({"fy": y, "ours_sum": round(s, 2), "screener": tot,
                                   "diff_pct": round(100.0 * (s - tot) / tot, 2) if tot else None,
                                   "ok": ok, "circular": circ_fy})
            cmp_n = len(agree) + len(disagree)
            if cmp_n < MIN_CMP:
                verdict = "THIN"
            elif not disagree:
                verdict = "OK"
            elif len(disagree) <= 3 and len(agree) >= 2 * len(disagree):
                verdict = "ISOLATED"
            else:
                yrs = {d["qe"][:4] for d in disagree}
                verdict = "RESTATED" if len(yrs) <= 2 and len(disagree) >= 3 else "SYSTEMATIC"
            bad_fy = [a for a in annual if not a["ok"] and not a["circular"]]
            done[key] = {"verdict": verdict, "row": label, "agree": len(agree),
                         "circular": circular, "disagree": disagree,
                         "annual": annual, "bad_fy": bad_fy}
        json.dump(done, open(OUT, "w"), indent=1)

    import collections
    c = collections.Counter(v["verdict"] for v in done.values())
    print("audited %d company/basis pairs" % len(done))
    for k, v in c.most_common():
        print("   %-12s %d" % (k, v))
    nfy = sum(len(v.get("bad_fy") or []) for v in done.values())
    okfy = sum(1 for v in done.values() for a in (v.get("annual") or []) if a["ok"])
    print("\nANNUAL ARM (FY2020+, reaches the pre-2023 cells the quarterly table cannot see):")
    print("   FY totals reproduced   : %d" % okfy)
    print("   FY totals MISMATCHED   : %d  (each localises >=1 bad cell to that year)" % nfy)
    worst = sorted(((abs(a["diff_pct"] or 0), k, a) for k, v in done.items()
                    for a in (v.get("bad_fy") or [])), reverse=True)[:20]
    for _d, k, a in worst:
        print("   %-22s FY%d  ours=%-13s screener=%-12s %+.1f%%"
              % (k, a["fy"], a["ours_sum"], a["screener"], a["diff_pct"] or 0))

    iso = [(k, v) for k, v in done.items() if v["verdict"] == "ISOLATED"]
    print("\nISOLATED suspect cells (%d pairs):" % len(iso))
    for k, v in sorted(iso)[:40]:
        for d in v["disagree"]:
            print("   %-22s %s  ours=%-12s screener=%-10s  %+.1f%%  (%d other quarters agree)"
                  % (k, d["qe"], d["ours"], d["screener"], d["diff_pct"] or 0, v["agree"]))
    print("\n-> %s" % OUT)


if __name__ == "__main__":
    main()
