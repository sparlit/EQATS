# -*- coding: utf-8 -*-
"""Restrict the screener audit to the POINT-IN-TIME Nifty 500 — survivorship-free.

The full audit covers all 3,588 companies in sf_revop, most of which are small BSE-only names that
were never in the index. This view answers the question that actually matters for the dashboards:
how good is the data for companies WHILE THEY WERE Nifty 500 members?

Survivorship-free means membership is read per quarter-end from the nearest-prior snapshot in
scripts/indices_history.json, exactly as audit_coverage.py does it:
  * a company counts ONLY for the quarters it actually was a member -- a 2024 joiner is not judged
    on its 2020 cells;
  * companies that later left the index, were delisted or merged still count for the quarters they
    were in, so the view is not biased toward today's survivors.

Symbols are chased through scripts/_rename_map.json, because the index snapshot holds the ticker
that traded THEN while sf_revop is keyed by the current one.

  python -X utf8 scripts/fill2020_tools/audit_n500_view.py [--from 20200101]
"""
import collections
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
AUDIT = os.path.join(SCRIPTS, "_screener_audit.json")
LAST_DAY = {3: 31, 6: 30, 9: 30, 12: 31}


def load(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return json.load(f)


def main():
    first = int(sys.argv[sys.argv.index("--from") + 1]) if "--from" in sys.argv else 20200101
    audit = json.load(open(AUDIT))
    idx = load("scripts/indices_history.json")
    rmap = load("scripts/_rename_map.json")
    revop = load("docs/sf_revop.json")

    def resolve(sym):
        cur, seen = sym, set()
        while cur not in revop:
            if cur in seen or cur not in rmap:
                return None
            seen.add(cur)
            cur = rmap[cur]
        return cur

    snaps = sorted(idx["Nifty 500"], key=lambda s: s["effectiveDate"])

    def members_at(qe):
        ds = "%04d-%02d-%02d" % (qe // 10000, (qe // 100) % 100, qe % 100)
        best = None
        for s in snaps:
            if s["effectiveDate"] <= ds:
                best = s
            else:
                break
        out = set()
        for x in (best or snaps[0])["symbols"]:
            if x.upper().startswith("DUMMY"):
                continue
            k = resolve(x)
            if k:
                out.add(k)
        return out

    # membership by quarter, from `first` to the newest snapshot
    quarters = []
    for y in range(first // 10000, 2027):
        for m in (3, 6, 9, 12):
            qe = y * 10000 + m * 100 + LAST_DAY[m]
            if qe >= first and qe <= 20260630:
                quarters.append(qe)
    mem = {qe: members_at(qe) for qe in quarters}
    ever = set().union(*mem.values()) if mem else set()

    # ---- cell-level: keep a disagreement only if the company WAS a member that quarter
    cells, iso_pairs = [], set()
    for key, v in audit.items():
        sym, field = key.split("|")
        if v.get("verdict") != "ISOLATED":
            continue
        for d in v["disagree"]:
            qe = int(d["qe"])
            if qe in mem and sym in mem[qe]:
                cells.append({"sym": sym, "field": field, "qe": qe, "ours": d["ours"],
                              "screener": d["screener"], "diff_pct": d["diff_pct"]})
                iso_pairs.add(key)

    # ---- pair-level verdicts, restricted to companies that were EVER members in the window
    ver = collections.Counter()
    for key, v in audit.items():
        sym = key.split("|")[0]
        if sym in ever:
            ver[v.get("verdict", "?")] += 1

    # ---- FY totals, counted only for FYs in which the company was a member
    ok_fy = bad_fy = 0
    bad_list = []
    for key, v in audit.items():
        sym = key.split("|")[0]
        if sym not in ever:
            continue
        for a in (v.get("annual") or []):
            fy = a["fy"]
            q4 = fy * 10000 + 331
            if q4 not in mem or sym not in mem[q4]:
                continue
            if a["ok"]:
                ok_fy += 1
            elif not a.get("circular"):
                bad_fy += 1
                bad_list.append((key, fy, a["ours_sum"], a["screener"], a["diff_pct"]))

    comparable = ver["OK"] + ver["ISOLATED"] + ver["RESTATED"] + ver["SYSTEMATIC"]
    print("NIFTY 500, POINT-IN-TIME (survivorship-free), quarters from %d" % first)
    print("companies that were members at any point in the window: %d" % len(ever))
    print("\ncompany/basis pairs (members only): %d" % sum(ver.values()))
    for k in ("OK", "ISOLATED", "RESTATED", "SYSTEMATIC", "NO-SCREENER", "THIN", "NO-ROW"):
        if ver.get(k):
            print("   %-12s %5d" % (k, ver[k]))
    if comparable:
        print("   -> of %d comparable pairs, %.1f%% fully clean" % (comparable,
                                                                    100.0 * ver["OK"] / comparable))
    print("\nSUSPECT CELLS while the company WAS a member: %d (across %d pairs)"
          % (len(cells), len(iso_pairs)))
    by_year = collections.Counter(str(c["qe"])[:4] for c in cells)
    print("   by year:", dict(sorted(by_year.items())))
    print("   by field:", dict(collections.Counter(c["field"] for c in cells)))
    print("\nFY totals while a member: %d reproduced, %d mismatched%s"
          % (ok_fy, bad_fy, " (%.1f%% clean)" % (100.0 * ok_fy / (ok_fy + bad_fy))
             if ok_fy + bad_fy else ""))

    cells.sort(key=lambda c: -abs(c["diff_pct"] or 0))
    print("\nWorst 30 suspect cells (member at the time):")
    print("   %-12s %-9s %-5s %14s %14s %9s" % ("sym", "quarter", "field", "ours", "screener", "diff%"))
    for c in cells[:30]:
        print("   %-12s %-9d %-5s %14.2f %14.2f %8.1f%%"
              % (c["sym"], c["qe"], c["field"], c["ours"], c["screener"], c["diff_pct"] or 0))
    json.dump({"cells": cells, "verdicts": dict(ver), "fy_ok": ok_fy, "fy_bad": bad_fy,
               "members_ever": sorted(ever)}, open("/tmp/audit_n500.json", "w"), indent=1)
    print("\n-> /tmp/audit_n500.json")


if __name__ == "__main__":
    main()
