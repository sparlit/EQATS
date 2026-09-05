# -*- coding: utf-8 -*-
"""Build the P5 CONTESTED-CELL worklist: cells where our own two stores disagree about PAT.

These are contested BY CONSTRUCTION and need no external site: sf_fundamentals (authoritative,
owners-attributable, CI-re-asserted) and sf_revop's PAT mirror hold different numbers for the same
(symbol, quarter, basis). Runbook 70b measured them, resynced only the safe family, and explicitly
left the rest as "the next audit's work".

Its worked example is the standing warning: SADBHAV Dec-2020 -- fundamentals held the TOTAL and
revop held the right magnitude with a FLIPPED SIGN. **Neither file was right.** So this list is an
ARBITRATION queue, never a "pick the other file" queue.

Priority is by what evidence is reachable, not by size of the gap:
  P1  in the point-in-time N500 AND in the site-verifiable window (>= 2024-03-31)
        -> filing + >=2 sites, full rule-6b quorum available
  P2  in the N500, older than the site window
        -> exchange filing only (which is the real check anyway)
  P3  outside the N500 denominator
  Every row also carries the sign-flip / power-of-ten / near-integer-ratio fingerprints, because
  those name the LIKELY mechanism and tell the arbitrator which document column to look at first.

  python3 -X utf8 build_contested.py --out contested.json --csv contested.csv
"""
import os, json, csv, argparse, collections

TREE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # repo root of THIS checkout
SITE_WINDOW = 20240331          # earliest quarter >=2 sites can speak to (P1 findings 1)


def jload(rel):
    with open(os.path.join(TREE, rel), encoding="utf-8") as fh:
        return json.load(fh)


def fingerprint(a, b):
    """Name the likely mechanism. a = revop mirror, b = fundamentals (authoritative)."""
    tags = []
    if a == 0.0 and b != 0.0:
        tags.append("revop_zero_sentinel")
    if b == 0.0 and a != 0.0:
        tags.append("fund_zero")
    if a and b and a * b < 0:
        tags.append("SIGN_FLIP")
        if abs(abs(a) - abs(b)) <= max(0.5, abs(b) * 0.01):
            tags.append("sign_flip_same_magnitude")
    if a and b:
        r = abs(a) / abs(b) if b else 0
        for p, nm in ((10, "x10"), (100, "x100"), (1000, "x1000"),
                      (0.1, "div10"), (0.01, "div100"), (0.001, "div1000")):
            if abs(r - p) <= p * 0.02:
                tags.append("POWER_OF_TEN_" + nm)
        # total-vs-owners fingerprint: fundamentals smaller than mirror by a steady slice
        if 0 < r and abs(r - 1) > 0.005:
            tags.append("ratio_%.3f" % r)
    return tags


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="contested.json")
    ap.add_argument("--csv", default="contested.csv")
    a = ap.parse_args()

    revop = jload("docs/sf_revop.json")
    fund = jload("docs/sf_fundamentals.json")
    IH = jload("scripts/indices_history.json")
    RMAP = jload("scripts/_rename_map.json")

    def norm(s):
        s = str(s).strip().upper()
        seen = set()
        while s in RMAP and s not in seen and RMAP[s] != s:
            seen.add(s); s = RMAP[s]
        return s

    snaps = sorted((s["effectiveDate"], set(norm(x) for x in s["symbols"]))
                   for s in IH["Nifty 500"])

    def in_n500(sym, q):
        iso = "%04d-%02d-%02d" % (q // 10000, (q // 100) % 100, q % 100)
        best = set()
        for ed, syms in snaps:
            if ed <= iso:
                best = syms
            else:
                break
        return norm(sym) in best

    patf = collections.defaultdict(dict)
    for s, rows in fund.items():
        for r in rows:
            if isinstance(r, list) and len(r) >= 5 and isinstance(r[0], int):
                patf[s][r[0]] = (r[1], r[3])

    rows_out = []
    for s, d in revop.items():
        for k, row in d.items():
            q = int(k)
            for idx, pi, basis in ((4, 0, "std"), (5, 1, "con")):
                mirror = row[idx]
                auth = (patf.get(s, {}).get(q) or (None, None))[pi]
                if mirror is None or auth is None:
                    continue
                if abs(mirror - auth) <= max(0.5, abs(auth) * 0.005):
                    continue
                n500 = in_n500(s, q)
                pri = 1 if (n500 and q >= SITE_WINDOW) else (2 if n500 else 3)
                rows_out.append({
                    "sym": s, "qe": q, "basis": basis,
                    "fundamentals_authoritative": auth, "revop_mirror": mirror,
                    "abs_delta": round(abs(mirror - auth), 3),
                    "rel_delta_pct": round(100 * (mirror - auth) / abs(auth), 2) if auth else None,
                    "in_n500_at_qe": n500, "site_window": q >= SITE_WINDOW,
                    "priority": pri, "fingerprints": fingerprint(mirror, auth),
                    "verdict": "OPEN", "evidence": None,
                })

    rows_out.sort(key=lambda r: (r["priority"], -r["abs_delta"]))
    byp = collections.Counter(r["priority"] for r in rows_out)
    byb = collections.Counter(r["basis"] for r in rows_out)
    fps = collections.Counter(t for r in rows_out for t in r["fingerprints"]
                              if not t.startswith("ratio_"))

    doc = {"_meta": {"tree_pin": "e8a491c6",
                     "authority": "sf_fundamentals npStd/npCon; sf_revop[4]/[5] is a MIRROR",
                     "warning": "runbook 70c SADBHAV: neither file was right. Arbitrate at the "
                                "filing; never 'pick the other file'.",
                     "site_window_from": SITE_WINDOW,
                     "total": len(rows_out), "by_priority": dict(byp), "by_basis": dict(byb)},
           "cells": rows_out}
    with open(a.out, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=1)
    with open(a.csv, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["priority", "sym", "qe", "basis", "fundamentals", "revop_mirror",
                    "abs_delta", "rel_delta_pct", "in_n500", "fingerprints"])
        for r in rows_out:
            w.writerow([r["priority"], r["sym"], r["qe"], r["basis"],
                        r["fundamentals_authoritative"], r["revop_mirror"], r["abs_delta"],
                        r["rel_delta_pct"], r["in_n500_at_qe"], "|".join(r["fingerprints"])])

    print("contested cells: %d   by basis %s" % (len(rows_out), dict(byb)))
    print("  P1 (N500 + site window, full 6b quorum possible): %d" % byp[1])
    print("  P2 (N500, exchange-only):                         %d" % byp[2])
    print("  P3 (outside N500 denominator):                    %d" % byp[3])
    print("  mechanism fingerprints: %s" % dict(fps))
    print("\ntop 15 by |delta| within P1:")
    for r in [x for x in rows_out if x["priority"] == 1][:15]:
        print("   %-12s %d %s  fund=%-12s mirror=%-12s d=%-10s %s"
              % (r["sym"], r["qe"], r["basis"], r["fundamentals_authoritative"],
                 r["revop_mirror"], r["abs_delta"], ",".join(r["fingerprints"])[:40]))
    print("\nwrote %s + %s" % (a.out, a.csv))


if __name__ == "__main__":
    main()
