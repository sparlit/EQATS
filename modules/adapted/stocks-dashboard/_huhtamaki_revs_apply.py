# -*- coding: utf-8 -*-
"""HEAL HUHTAMAKI's three STANDALONE revenue cells that hold the sale-of-products SUB-LINE (§100f).

§100 retracted the fabricated CONSOLIDATED cells (20201231+, revC = the standalone sub-line). While
verifying that, a SECOND defect was measured in the STANDALONE slot and left unactioned: at
20200331/0630/0930 `revS` holds the same sub-line — "a) Sale of Products & Services" — instead of
"Total Revenue from Operations". The two defects are the SAME upstream serving the SAME wrong row;
what changes at 20201231 is only which slot it lands in (before: std, con a byte-copy of it — which
is why `copied_con_purge.json` retracted those three revC cells on the equality signature; after:
std correct, con fabricated).

EVIDENCE, all re-read this session (§0 no assumptions):
  * The company's OWN NSE XBRL for each quarter, PAT-anchored to the paisa before the value was
    taken (the anchor proves the instance is that quarter's filing, §61):
        20200331  INDAS_55157_259010_16052020010848_WEB   RevenueFromOperations 574.56  PAT 27.31 == stored
        20200630  INDAS_60360_307539_14082020081531_WEB   RevenueFromOperations 635.67  PAT 26.72 == stored
        20200930  INDAS_62373_350259_23102020095256_WEB   RevenueFromOperations 685.90  PAT 36.88 == stored
  * The Jun-2020 BSE PDF (att c7191c19-2774-411c-8a08-dc8bed01b261, "Rs. in Lakhs") prints the
    split that names the defect: a) Sale of Products & Services 63,060 = 630.60 == our stored revS;
    b) Other Operating Revenue 507; Total Revenue from Operations 63,567 = 635.67. The same PDF's
    Mar-2020 column prints 56,749 = 567.49 == our stored revS for that quarter.
  * `op` CORROBORATES the diagnosis rather than merely not contradicting it: stored opS 67.49
    (Jun-20) and 77.43 (Sep-20) equal `metrics_for`'s value from those same instances EXACTLY. One
    upstream took the operating-profit line from the filing correctly and the revenue line from the
    row above the total — so only slot 0 is wrong, and the rest of the row must not be touched.
  * The window is walled on BOTH sides: HUHTAMAKI's revS reproduces the filed total to the paisa in
    all 31 other cached quarters, 20180331..20260630. The defect is exactly these three cells.

This heal moves ONLY slot 0 (revS) for those three quarters, in both revop twins, and journals to
`rev_defects.json` — where `verify_fills_live.py`'s NESTED registration (rev_defects -> revop ->
correct_rev, basis-keyed) already turns each entry into a standing tripwire, so a future writer that
restores the sub-line is caught instead of landing silently (§85b).

Dry-run by default; --apply to write. Safety mirrors the §73 applier:
  * guard: each cell's CURRENT value must equal the recorded `was`, or the run aborts;
  * idempotent: a cell already at `now` is reported and skipped;
  * blast radius: both twins are diffed against their originals and the run aborts unless the ONLY
    changes are the three intended (symbol, quarter) pairs.
"""
import json, os, sys, copy

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SYM = "HUHTAMAKI"
TOL = 0.011
REVOP_TWINS = ("docs/sf_revop.json", "scripts/revop_fundamentals.json")
DEFECT = ("stored value is the standalone filing's revenue SUB-LINE 'a) Sale of Products & "
          "Services', not 'Total Revenue from Operations' (the row above the total). Same upstream "
          "and same wrong row as the §100 con-slot fabrication; before 20201231 it landed in the "
          "STD slot (con was then a byte-copy, retracted by copied_con_purge.json on the equality "
          "signature), from 20201231 in the con slot. opS from the same filing is EXACT, so only "
          "slot 0 was affected.")

# qe -> was (the sub-line), now (the filed total), and the instance each was read from
HEAL = {
    "20200331": {"was": 567.49, "now": 574.56,
                 "src": "own std XBRL INDAS_55157_259010_16052020010848_WEB (Symbol=PAPERPROD, OneD "
                        "2020-01-01..2020-03-31, NatureOfReport=Standalone): RevenueFromOperations "
                        "5,745,600,000 = 574.56, PAT 27.31 == stored patS (anchor). The Jun-2020 "
                        "PDF's Mar-2020 column prints the sub-line 56,749 lakh = 567.49 = the "
                        "stored value being replaced."},
    "20200630": {"was": 630.60, "now": 635.67,
                 "src": "own std XBRL INDAS_60360_307539_14082020081531_WEB (Symbol=PAPERPROD, OneD "
                        "2020-04-01..2020-06-30, NatureOfReport=Standalone): RevenueFromOperations "
                        "6,356,700,000 = 635.67, PAT 26.72 == stored patS (anchor). BSE PDF att "
                        "c7191c19-2774-411c-8a08-dc8bed01b261 prints a) Sale of Products & Services "
                        "63,060 + b) Other Operating Revenue 507 = Total 63,567 lakh; 630.60 + "
                        "5.07 == 635.67 EXACTLY."},
    "20200930": {"was": 673.30, "now": 685.90,
                 "src": "own std XBRL INDAS_62373_350259_23102020095256_WEB (Symbol=PAPERPROD, OneD "
                        "2020-07-01..2020-09-30, NatureOfReport=Standalone): RevenueFromOperations "
                        "6,859,000,000 = 685.90, PAT 36.88 == stored patS (anchor). Stored 673.30 "
                        "is 12.60 short — the other-operating-revenue line for the quarter."},
}


def load(rel):
    return json.load(open(os.path.join(ROOT, rel), encoding="utf-8"))


def dump_min(rel, obj):
    """Both revop twins are MINIFIED on disk; writing them pretty would rewrite all 5.9MB."""
    p = os.path.join(ROOT, rel)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, separators=(",", ":"))
    os.replace(tmp, p)


def close(a, b):
    return a is not None and b is not None and abs(a - b) <= TOL


problems, skipped, plan = [], [], []
orig = {rel: load(rel) for rel in REVOP_TWINS}
work = {rel: copy.deepcopy(orig[rel]) for rel in orig}
expect = {rel: set() for rel in orig}

for rel in REVOP_TWINS:
    d = work[rel]
    rows = d.get(SYM)
    if not rows:
        problems.append("%s: no %s rows at all" % (rel, SYM))
        continue
    for qe, e in sorted(HEAL.items()):
        c = rows.get(qe)
        if c is None:
            problems.append("%s %s: quarter absent" % (rel, qe))
            continue
        if close(c[0], e["now"]):
            skipped.append("%s %s revS already %s" % (rel, qe, e["now"]))
            continue
        if not close(c[0], e["was"]):
            problems.append("%s %s: REV GUARD FAILED revS=%s expected the sub-line %s"
                            % (rel, qe, c[0], e["was"]))
            continue
        c[0] = e["now"]
        plan.append((rel, qe, "revS", e["was"], e["now"]))
        expect[rel].add(qe)

# ---- blast radius -----------------------------------------------------------
for rel in orig:
    b, a = orig[rel], work[rel]
    diffs = set()
    for sym in set(b) | set(a):
        x, y = b.get(sym), a.get(sym)
        if x == y:
            continue
        if sym != SYM:
            diffs.add((sym, "OTHER-SYMBOL"))
            continue
        for q in set(x) | set(y):
            if x.get(q) != y.get(q):
                diffs.add((sym, q))
    stray = {t for t in diffs if t[1] not in expect[rel]}
    if stray:
        problems.append("%s: BLAST RADIUS stray diffs %s" % (rel, sorted(stray)[:8]))

print("planned edits: %d   skipped(already-correct): %d   problems: %d"
      % (len(plan), len(skipped), len(problems)))
for p in plan:
    print("  EDIT", p)
for s in skipped:
    print("  SKIP", s)
for p in problems:
    print("  PROBLEM", p)
if problems:
    sys.exit(1)
if "--apply" not in sys.argv:
    print("DRY RUN - nothing written")
    sys.exit(0)

for rel in orig:
    dump_min(rel, work[rel])

# ---- journal ----------------------------------------------------------------
# rev_defects.json is pretty-printed at indent=1 (unlike the minified twins above).
rd = load("scripts/rev_defects.json")
for qe, e in HEAL.items():
    ent = rd.setdefault(SYM, {}).setdefault(qe, {})
    ent.update({"bad_rev": e["was"], "basis": "std", "correct_rev": e["now"],
                "defect": DEFECT, "source": e["src"]})
# indent=1, ensure_ascii default (existing entries escape as §), and NO trailing newline —
# the three conventions the file is already written in, so the diff shows only the new entries.
p = os.path.join(ROOT, "scripts/rev_defects.json")
tmp = p + ".tmp"
with open(tmp, "w", encoding="utf-8") as fh:
    json.dump(rd, fh, indent=1)
os.replace(tmp, p)
print("APPLIED %d cells + journalled %d entries to rev_defects.json" % (len(plan), len(HEAL)))
