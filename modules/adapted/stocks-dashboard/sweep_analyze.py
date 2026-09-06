# -*- coding: utf-8 -*-
"""P4 phase C — hunt the WRONG-ROW REVENUE defect across the whole store.

THE DEFECT, as confirmed twice from primary filings:
  HUDCO 2022-06-30  our stored standalone revenue was the filing's "Interest Income" SUB-LINE
                    (1736.42), not its Total revenue row (1749.27).
  AADHARHFC 2023-24 our standalone revenue runs 1.6-12.1% BELOW an independent source for seven
                    consecutive quarters, while PAT matches to 0.1% in every one of them.

THE SIGNATURE, and why it is narrow enough to be useful:
  * revenue is BELOW the independent source (we hold a component, not the total -- a sub-line can
    only ever be smaller),
  * over CONSECUTIVE quarters (a one-off gap is noise or a restatement, not a parse rule),
  * while PAT MATCHES (isolates a revenue-row selection problem from a whole-filing misread).
That third condition is what makes this cheap to trust: if PAT also disagreed we would be looking
at the wrong company, the wrong period, or the wrong scale instead.

WHAT THIS IS NOT. A flag is a place to look. This campaign has repeatedly shown a clean-looking
screen to be mostly false positives -- the con==std screen fires 6,470 times and HUDCO proved that
shape is usually LEGITIMATE. Only a filing read decides.

  python3 -X utf8 scripts/revpat_verify/sweep_analyze.py \
      --extract <dir>/screener_p4.jsonl [--extract more.jsonl] --out wrongrow_candidates.json
"""
import os, json, csv, argparse, collections, statistics

TREE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REV_LABELS = ("Revenue", "Sales")          # Screener's bank/NBFC and industrial revenue rows
MIN_RUN = 2                                # consecutive quarters below to call it a run
BELOW = -0.02                              # 2% -- below this a gap is not rounding
# ★ A SINGLE quarter can be a defect too, and a run-only rule goes BLIND exactly when you start
# fixing things: healing AADHARHFC 2023-06 and 2023-12 broke the run around 2023-09, which is still
# -8.7% wrong -- and it silently vanished from this report. Partially healing a run must not hide
# its remainder. So an isolated quarter this far below an independent source is flagged on its own.
LONE = -0.05
# ★ ABSOLUTE FLOOR — a relative threshold alone is MEANINGLESS on a small base. Screener prints
# whole crores, so its displayed figure carries +/-0.5cr of rounding; at a 25cr base a 2% "gap" IS
# that rounding. Batch-B proved it: SELMC 2024-12-31's correct row (4.5219) and the inflated
# Total-Income alternative (4.57) DISPLAY AS THE SAME INTEGER, so the flagged percentage could not
# even in principle indicate a row swap. Three of four companies in that batch were flagged purely
# by this artefact and all came back OURS_CONFIRMED. Require a real rupee gap as well.
ABS_FLOOR_CR = 2.0
PAT_OK = 0.01                              # PAT must agree within 1% for the signature to hold


def jload(rel):
    with open(os.path.join(TREE, rel), encoding="utf-8") as fh:
        return json.load(fh)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--extract", action="append", required=True)
    ap.add_argument("--out", default="wrongrow_candidates.json")
    ap.add_argument("--csv", default="")
    a = ap.parse_args()

    try:
        _adj = jload("scripts/revpat_verify/adjudicated_clean.json")
        clean = set(_adj.get("symbols", {}))
        # per-CELL suppression: a symbol can be genuinely wrong in one quarter and a false positive
        # in another (AADHARHFC is both), so whole-symbol suppression would hide the real defect.
        clean_cells = {(s_, int(q)) for s_, qd in (_adj.get("cells") or {}).items() for q in qd}
    except Exception:
        clean, clean_cells = set(), set()
    revop = jload("docs/sf_revop.json")
    fund = jload("docs/sf_fundamentals.json")
    patf = collections.defaultdict(dict)
    for s, rows in fund.items():
        for r in rows:
            if isinstance(r, list) and len(r) >= 5 and isinstance(r[0], int):
                patf[s][r[0]] = r[1]
    isfin = {s for s, d in revop.items() for r in d.values() if r[6] == 1}

    site = collections.defaultdict(dict)       # sym -> qe -> (rev, pat)
    seen = 0
    for path in a.extract:
        if not os.path.exists(path):
            print("  ! missing extract: %s" % path); continue
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except Exception:
                continue
            if e.get("basis") != "std":
                continue
            q = int(str(e["qe"]).replace("-", ""))
            rv = next((e["rows"][k] for k in REV_LABELS if k in e["rows"]), None)
            site[e["sym"].upper()][q] = (rv, e["rows"].get("Net Profit"))
            seen += 1
    print("site rows read: %d across %d symbols" % (seen, len(site)))

    cands, allrel = [], []
    for sym, qd in site.items():
        if sym in clean:                  # already taken to its filings and found correct
            continue
        ours = revop.get(sym) or {}
        rows = []
        for q in sorted(qd):
            sv, sp = qd[q]
            mine = (ours.get(str(q)) or [None])[0]
            if sv in (None, 0) or mine is None:
                continue
            rel = (mine - sv) / abs(sv)
            mypat, spat = patf.get(sym, {}).get(q), sp
            patok = (mypat is not None and spat not in (None, 0)
                     and abs((mypat - spat) / abs(spat)) <= PAT_OK)
            if (sym, q) in clean_cells:          # this exact cell was read and confirmed
                continue
            rows.append({"qe": q, "ours": mine, "site": sv, "rel": rel, "pat_agrees": patok})
            allrel.append(rel)
        if not rows:
            continue
        # longest run of consecutive quarters BELOW the site with PAT agreeing
        best, cur = [], []
        for r in rows:
            if r["rel"] <= BELOW and r["pat_agrees"] and abs(r["ours"] - r["site"]) >= ABS_FLOOR_CR:
                cur.append(r)
                if len(cur) > len(best):
                    best = list(cur)
            else:
                cur = []
        # UNION, not either/or: a symbol can carry BOTH a run and a separate isolated bad quarter,
        # and reporting only the run is how AADHARHFC 2023-09 (-8.7%) disappeared after its
        # neighbours were healed. Take run cells (when a real run exists) plus every isolated cell
        # at or below LONE, de-duplicated and back in quarter order.
        run_cells = best if len(best) >= MIN_RUN else []
        lone = [r for r in rows if r["rel"] <= LONE and r["pat_agrees"]
                and abs(r["ours"] - r["site"]) >= ABS_FLOOR_CR and r not in run_cells]
        best = sorted({r["qe"]: r for r in (run_cells + lone)}.values(), key=lambda r: r["qe"])
        if best:
            cands.append({
                "sym": sym, "is_financial": sym in isfin, "run_len": len(best),
                "from": best[0]["qe"], "to": best[-1]["qe"],
                "worst_pct": round(100 * min(r["rel"] for r in best), 1),
                "median_pct": round(100 * statistics.median(r["rel"] for r in best), 1),
                "pat_agrees_throughout": all(r["pat_agrees"] for r in best),
                "kind": ("run+isolated" if run_cells and lone else
                         ("run" if run_cells else "isolated_material")),
                "cells": [{"qe": r["qe"], "ours": r["ours"], "site": r["site"],
                           "pct": round(100 * r["rel"], 1)} for r in best],
            })
    cands.sort(key=lambda c: (c["worst_pct"], -c["run_len"]))

    fin = [c for c in cands if c["is_financial"]]
    doc = {"_meta": {
        "defect": "stored standalone revenue holds a COMPONENT row, not the total",
        "signature": "consecutive quarters BELOW an independent source while PAT AGREES",
        "thresholds": {"below": BELOW, "min_run": MIN_RUN, "pat_within": PAT_OK,
                       "lone": LONE, "abs_floor_cr": ABS_FLOOR_CR},
        "confirmed_instances": ["HUDCO 2022-06-30 (Interest Income sub-line)", "AADHARHFC 2023-24"],
        "warning": "a flag is a place to LOOK. Only a filing read decides.",
        "symbols_compared": len(site), "suppressed_adjudicated_clean": sorted(clean),
        "candidates": len(cands), "financial_candidates": len(fin),
        "median_rel_all_cells": round(statistics.median(allrel), 5) if allrel else None},
        "candidates": cands}
    with open(a.out, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=1)
    if a.csv:
        with open(a.csv, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["sym", "financial", "run_len", "from", "to", "worst_pct", "median_pct"])
            for c in cands:
                w.writerow([c["sym"], c["is_financial"], c["run_len"], c["from"], c["to"],
                            c["worst_pct"], c["median_pct"]])

    print("symbols compared: %d | median relative diff across ALL cells: %s"
          % (len(site), doc["_meta"]["median_rel_all_cells"]))
    print("candidates with a run of >=%d consecutive quarters below, PAT agreeing: %d (%d financial)"
          % (MIN_RUN, len(cands), len(fin)))
    print("\n  %-13s %3s %4s %-9s %-9s %7s %7s" % ("sym", "fin", "run", "from", "to", "worst", "median"))
    for c in cands[:30]:
        print("  %-13s %3s %4d %-9d %-9d %6.1f%% %6.1f%%"
              % (c["sym"], "Y" if c["is_financial"] else "", c["run_len"], c["from"], c["to"],
                 c["worst_pct"], c["median_pct"]))
    print("\nwrote %s" % a.out)


if __name__ == "__main__":
    main()
