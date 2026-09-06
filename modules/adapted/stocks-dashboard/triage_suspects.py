# -*- coding: utf-8 -*-
"""Deterministic triage of the screener-audit suspects. Why does this cell disagree?

A disagreement with screener is NOT automatically our defect, and the difference between "our bug"
and "a restatement" is decidable by arithmetic in almost every case. So this is code, not judgement:
the same five tests applied to every suspect, in priority order, with the evidence recorded.

  SCALE            ours x 10^k == screener for a single k in {1,2,3}, AND the same quarter's OTHER
                   basis is clean. That pair -- one basis off by exactly a power of ten while its
                   twin filed minutes later is right -- is the signature of a filer whose XBRL is
                   scaled (runbook §11 / scale_fix.json). GAIL, RCF and TEAMLEASE came out this way.
  CUMULATIVE       ours == the earlier stored quarters of that FY + screener's quarter. The cell
                   holds a year-to-date figure. Proven WITHOUT screener when the sum is exact.
  FY-IN-QUARTER    ours == screener's FY total: the whole year parked in one quarter.
  RUN              the disagreement spans >=3 quarters with a CONSISTENT ratio -> the two sides are
                   measuring different things (restatement, demerger, entity, or a definitional gap
                   like screener's finance-layout `Revenue` = total income, or gross-vs-net of
                   excise for distillers). NOT a per-cell defect; never auto-corrected.
  ISOLATED-DIFF    a single odd quarter that none of the above explains. Genuinely suspect, but the
                   correct value is not derivable here -- needs the filing.

Read-only. Writes /tmp/triage_verdicts.json and prints the actionable list.

  python -X utf8 scripts/fill2020_tools/triage_suspects.py
"""
import collections
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, SCRIPTS)
import screener_fetch as SF                                       # noqa: E402

SLOT = {"revS": 0, "revC": 1}
OTHER = {"revS": 1, "revC": 0}


def fy_of(qe):
    y, m = qe // 10000, (qe // 100) % 100
    return y + 1 if m > 3 else y


def fy_quarters(fy):
    return [(fy - 1) * 10000 + 630, (fy - 1) * 10000 + 930,
            (fy - 1) * 10000 + 1231, fy * 10000 + 331]


def close(a, b, tol=0.015, floor=1.0):
    return a is not None and b is not None and abs(a - b) <= max(floor, abs(b) * tol)


def main():
    audit = json.load(open(os.path.join(SCRIPTS, "_screener_audit.json")))
    revop = json.load(open(os.path.join(ROOT, "docs", "sf_revop.json")))

    suspects = []
    for key, v in audit.items():
        if v.get("verdict") != "ISOLATED":
            continue
        sym, field = key.split("|")
        for d in v["disagree"]:
            suspects.append((sym, field, int(d["qe"]), d["ours"], d["screener"]))

    out, cache = [], {}
    for sym, field, qe, ours, scr in suspects:
        con = field.endswith("C")
        ck = (sym, con)
        if ck not in cache:
            try:
                cache[ck] = (SF.quarters(sym, con=con), SF.annuals(sym, con=con))
            except Exception:
                cache[ck] = ({}, {})
        sq, sa = cache[ck]
        lab = next((L for L in ("Sales", "Revenue") if any(L in r for r in sq.values())), None) if sq else None
        alab = next((L for L in ("Sales", "Revenue") if any(L in r for r in sa.values())), None) if sa else None
        mine = revop.get(sym) or {}
        slot = SLOT[field]
        rec = {"sym": sym, "field": field, "qe": qe, "ours": ours, "screener": scr}

        # --- SCALE
        twin = None
        row = mine.get(str(qe))
        if row and len(row) > OTHER[field]:
            twin = row[OTHER[field]]
        hit = None
        for k in (1, 2, 3):
            for f in (10.0 ** k, 1.0 / 10.0 ** k):
                if close(ours * f, scr, 0.02):
                    hit = f
                    break
            if hit:
                break
        if hit and twin is not None and twin > 0 and not close(twin * hit, twin, 0.02):
            # twin must itself look sane: within an order of magnitude of screener
            if 0.1 * scr <= twin <= 10 * scr:
                rec.update(bucket="SCALE", factor=round(hit, 6), suggested=round(ours * hit, 2),
                           reason="ours x%.6g == screener; same-quarter other basis (%s) is clean"
                                  % (hit, twin))
                out.append(rec)
                continue

        # --- CUMULATIVE
        fy = fy_of(qe)
        qs = fy_quarters(fy)
        if qe in qs and qs.index(qe) > 0:
            earlier = qs[:qs.index(qe)]
            vals = [(mine.get(str(q)) or [None] * 9)[slot] for q in earlier]
            if all(v is not None for v in vals) and close(ours, sum(vals) + scr, 0.02):
                rec.update(bucket="CUMULATIVE", suggested=round(ours - sum(vals), 2),
                           reason="ours == earlier quarters of FY%d (%.2f) + screener %.2f"
                                  % (fy, sum(vals), scr))
                out.append(rec)
                continue

        # --- FY-IN-QUARTER
        tot = (sa.get("%d-03-31" % fy) or {}).get(alab) if alab else None
        if tot is not None and close(ours, tot, 0.02, 2.0):
            sibs = [(mine.get(str(q)) or [None] * 9)[slot] for q in qs if q != qe]
            if all(s is not None for s in sibs):
                rec.update(bucket="FY-IN-QUARTER", suggested=round(tot - sum(sibs), 2),
                           reason="ours == screener FY%d total %.2f" % (fy, tot))
                out.append(rec)
                continue

        # --- RUN (restatement / definitional / entity)
        ratios = []
        for dk, r in (sq or {}).items():
            t = r.get(lab)
            v = (mine.get(dk.replace("-", "")) or [None] * 9)[slot]
            if v is None or not t:
                continue
            if not close(v, t):
                ratios.append(v / t)
        if len(ratios) >= 3:
            mid = sorted(ratios)[len(ratios) // 2]
            spread = max(abs(r / mid - 1) for r in ratios) if mid else 9
            if spread <= 0.15:
                rec.update(bucket="RUN", reason="%d quarters disagree with a consistent ratio "
                                                "~%.2f (restatement / definition / entity)"
                                                % (len(ratios), mid))
                out.append(rec)
                continue

        rec.update(bucket="ISOLATED-DIFF",
                   reason="no arithmetic explains it; needs the filing")
        out.append(rec)

    json.dump(out, open("/tmp/triage_verdicts.json", "w"), indent=1)
    c = collections.Counter(r["bucket"] for r in out)
    print("triaged %d suspects\n" % len(out))
    for k, n in c.most_common():
        print("   %-16s %d" % (k, n))
    act = [r for r in out if r["bucket"] in ("SCALE", "CUMULATIVE", "FY-IN-QUARTER")]
    print("\nACTIONABLE (arithmetic gives the correct value): %d\n" % len(act))
    print("   %-12s %-9s %-5s %14s %14s  %s" % ("sym", "quarter", "field", "ours", "->", "bucket"))
    for r in sorted(act, key=lambda x: (x["bucket"], x["sym"]))[:60]:
        print("   %-12s %-9d %-5s %14.2f %14.2f  %s"
              % (r["sym"], r["qe"], r["field"], r["ours"], r["suggested"], r["bucket"]))
    print("\n-> /tmp/triage_verdicts.json")


if __name__ == "__main__":
    main()
