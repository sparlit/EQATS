# -*- coding: utf-8 -*-
"""TRIPWIRE: consolidated slot holding a COPY of the standalone figure.

Why this exists, stated plainly. The user found TIMKEN 2025-09-30 storing con PAT 89.47 when the
real consolidated figure is 94 -- 89.47 is the STANDALONE value sitting in the con slot. Their
response was *"u must hv made such wrong entries for many stocks i feel"* and *"whenever i just find
a mistake of urs, u say ohh this is wrong"*. Both fair. The defect was found by a person spot-checking
one cell, not by any check of ours, and that is the failure this file fixes.

It is the SAME disease as the is_con_basis bug (§56) whose 1,656 fabricated cells were purged -- but
that purge only reached companies already listed in the hand-verified no_con_filing ledger. The
general case was never swept. On its first run this tripwire found 19 cells across 12 companies,
including three TIMKEN quarters where the user had spotted one.

THE TEST is decisive and needs no PDF:
    our stored conC == stdC (exact copy)  AND  screener's con differs from its std
    -> our con slot is a copy of standalone, and the real consolidated figure exists.

Run on BOTH columns -- consolidated PAT and consolidated REVENUE. The first version tested PAT only
and therefore missed TIMKEN 2024-12-31, which stored revC 671.40 against a standalone 671.43 while
the company's own filing says 683.35. A copy is a copy in either column.

A legitimate identity (no subsidiary, or an equity-method associate) shows con == std on SCREENER
TOO, so it is never flagged. The flag fires only when an independent source says the two differ.

LIMITS, stated so nobody mistakes a clean run for a clean dataset:
  * screener's quarterly table reaches ~13 quarters, so this covers roughly 2023+ only;
  * it catches EXACT copies -- a con value that is wrong but not equal to std slips through;
  * it only sees companies screener covers with both bases.
A zero here means "none of the copies this test can see", never "no copies".

★ THE FALSE POSITIVE THIS TEST CANNOT RULE OUT -- BASIS MISMATCH (found 2026-08-09).
We store consolidated PAT OWNERS-ATTRIBUTABLE; screener quotes TOTAL consolidated PAT. Where NCI is
material those are different numbers, so a company can satisfy both halves of the test without
having any defect at all:

    TATACOFFEE 2022-12-31 -- filing: owners 26.63 + NCI 11.77 = total 38.40, standalone 26.61.
    Our con 26.63 (owners, CORRECT) sits 0.02 from our std 26.61 by coincidence -> "ours con == std".
    screener shows con 38 vs std 27                                            -> "they differ".
    Flagged. Read against screener's 38, healed, and the correct value was destroyed.

So a flag means "this cell needs adjudicating", never "this cell is a copy". Before believing one,
check whether screener's con minus our con is simply the NCI: if the filing reconciles
owners + NCI == total and our value equals OWNERS, there is no defect. read_con_copies.py now uses
screener only to locate the COLUMN and reads the value off the OWNERS row (§58).
Cells whose |value| is a few crore are also below this test's resolution -- screener displays them
rounded to integers, against a 0.6 tolerance floor (MMTC, MODIRUBBER).

  python -X utf8 scripts/detect_con_copy.py [--json OUT] [--limit N]
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import screener_fetch as SF                                       # noqa: E402

TOL_SAME = 0.0005          # ours con vs std: an exact copy
TOL_DIFF = 0.02            # screener con vs std: a MATERIAL difference


def main():
    limit = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else 10 ** 9
    out_p = sys.argv[sys.argv.index("--json") + 1] if "--json" in sys.argv else None
    fund = json.load(open(os.path.join(ROOT, "docs", "sf_fundamentals.json")))
    revop = json.load(open(os.path.join(ROOT, "docs", "sf_revop.json")))
    try:
        ev = json.load(open(os.path.join(HERE, "con_filer_evidence.json")))
        syms = [s for s, v in ev.items() if v.get("files_con")]
    except Exception:
        syms = sorted(fund)

    # Cells already adjudicated and REVERTED stay flagged forever by this test -- TATACOFFEE
    # 2022-12-31 satisfies it permanently, because its correct owners-basis con genuinely equals
    # its standalone while screener quotes total PAT. Without this, the next sweep re-"heals" it
    # straight back to the wrong number. Surface them separately, never in the actionable list.
    # `reverted` = a heal undone; `readjudicated` = re-read from the primary record and settled.
    # Both mean a document has already answered this cell, so neither may re-enter the actionable
    # list. ACUTAAS 2023-06 is why the second key is needed: its con genuinely EQUALS its
    # standalone (Tanfac was not consolidated yet), so this test fires on it forever.
    try:
        known = {k: v for k, v in json.load(open(os.path.join(HERE, "con_copy_heals.json"))).items()
                 if v.get("reverted") or v.get("readjudicated")}
    except Exception:
        known = {}

    bad, checked, n = [], 0, 0
    for sym in syms:
        if n >= limit:
            break
        rows = fund.get(sym) or []
        same = [r for r in rows if len(r) > 3 and r[1] is not None and r[3] is not None
                and abs(r[3] - r[1]) <= max(0.02, abs(r[1]) * TOL_SAME)]
        if not same:
            continue
        n += 1
        try:
            qc, qs = SF.quarters(sym, con=True), SF.quarters(sym, con=False)
        except Exception:
            continue
        if not qc or not qs:
            continue
        for r in same:
            dk = "%d-%02d-%02d" % (r[0] // 10000, (r[0] // 100) % 100, r[0] % 100)
            c = (qc.get(dk) or {}).get("Net Profit")
            s = (qs.get(dk) or {}).get("Net Profit")
            if c is None or s is None:
                continue
            checked += 1
            if abs(c - s) > max(1.0, abs(s) * TOL_DIFF):
                bad.append({"sym": sym, "qe": r[0], "field": "patC", "our": r[3], "our_std": r[1],
                            "screener_con": c, "screener_std": s,
                            "why": "our con slot equals std, but screener reports con %s vs std %s"
                                   % (c, s)})

        # ---- REVENUE side of the SAME defect. TIMKEN 2024-12-31 stored revC 671.40 against a
        # standalone 671.43 while its own filing says the consolidated figure is 683.35 -- caught
        # only because I happened to look, since the first version of this tripwire tested PAT
        # alone. A copy is a copy in either column.
        for q, row in (revop.get(sym) or {}).items():
            if not row or len(row) < 2 or row[0] is None or row[1] is None:
                continue
            if abs(row[1] - row[0]) > max(0.05, abs(row[0]) * TOL_SAME):
                continue
            dk = "%s-%s-%s" % (q[:4], q[4:6], q[6:])
            lc = next((L for L in ("Sales", "Revenue") if L in (qc.get(dk) or {})), None)
            ls = next((L for L in ("Sales", "Revenue") if L in (qs.get(dk) or {})), None)
            if not lc or not ls:
                continue
            c2, s2 = qc[dk][lc], qs[dk][ls]
            checked += 1
            if abs(c2 - s2) > max(1.0, abs(s2) * TOL_DIFF):
                bad.append({"sym": sym, "qe": int(q), "field": "revC", "our": row[1],
                            "our_std": row[0], "screener_con": c2, "screener_std": s2,
                            "why": "con REVENUE slot equals std, screener reports con %s vs std %s"
                                   % (c2, s2)})

    supp = [b for b in bad if "%s|%d|%s" % (b["sym"], b["qe"], b["field"]) in known]
    bad = [b for b in bad if "%s|%d|%s" % (b["sym"], b["qe"], b["field"]) not in known]

    print("companies scanned: %d | cells testable (ours con==std, screener has both): %d"
          % (n, checked))
    if supp:
        print("suppressed %d cell(s) already adjudicated and REVERTED (see con_copy_heals.json) -- "
              "these satisfy the test permanently and are NOT defects:" % len(supp))
        for b in supp:
            print("   %s %d %s" % (b["sym"], b["qe"], b["field"]))
    print("CON SLOT HOLDS STD: %d cells across %d companies\n"
          % (len(bad), len({b["sym"] for b in bad})))
    print("%-12s %-10s %-6s %11s %11s %11s"
          % ("sym", "quarter", "field", "ours", "scr con", "scr std"))
    for b in sorted(bad, key=lambda z: -abs(z["screener_con"] - z["screener_std"])):
        print("%-12s %-10d %-6s %11.2f %11.1f %11.1f"
              % (b["sym"], b["qe"], b["field"], b["our"], b["screener_con"], b["screener_std"]))
    print("\nLIMITS: screener's ~13-quarter window (roughly 2023+), EXACT copies only, and only "
          "companies screener covers on both bases. Zero here is not proof of a clean dataset.")
    if out_p:
        json.dump(bad, open(out_p, "w"), indent=1)
        print("-> %s" % out_p)


if __name__ == "__main__":
    main()
