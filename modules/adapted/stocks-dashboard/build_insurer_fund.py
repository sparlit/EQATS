# -*- coding: utf-8 -*-
"""Build insurer quarterly net-profit series (Cr) from the cropped P&L rows.
Base = manifest text-layer preview (exact digits); OVERRIDES = values I vision-read from the crop where
the preview was row-merge garbage or unit-ambiguous. Unit for non-overridden previews chosen by the
plausible-magnitude rule. Prints the series for sanity; with 'apply' merges into docs/sf_fundamentals.json
(rebuilt from origin/main so concurrent backfills aren't clobbered).
"""
import json, os, sys, subprocess
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
M = json.load(open(os.path.join(HERE, "_vins", "manifest.json")))
RANGE = {"GICRE": (15, 4000), "ICICIGI": (40, 1500), "LICI": (300, 20000), "SBILIFE": (40, 1500), "STARHEALTH": (15, 800)}
# vision-read corrections (Cr), where the text preview was garbage/ambiguous:
OVR = {
  ("GICRE", 20191231): -1496.08, ("GICRE", 20210630): 1260.44, ("GICRE", 20211231): -28.48,
  ("GICRE", 20221231): 1198.99, ("GICRE", 20230630): 731.79, ("GICRE", 20241231): 1623.43,
  ("ICICIGI", 20230930): 577.27, ("LICI", 20220630): 602.79, ("LICI", 20230930): 8030.28,
  ("LICI", 20250930): 10098.48, ("SBILIFE", 20230331): 776.85, ("SBILIFE", 20190930): 129.84,
}
APPLY = len(sys.argv) > 1 and sys.argv[1] == "apply"

# dedupe crops by (sym,qe)
crop = {}
for x in M: crop[(x["sym"], x["qe"])] = x

def resolve(sym, qe, p):
    if (sym, qe) in OVR: return OVR[(sym, qe)], "ovr"
    if p is None: return None, "none"
    lo, hi = RANGE[sym]
    cands = []
    for u, v in (("Lk", p / 100), ("Cr", p), ("Mn", p / 10)):
        if lo <= abs(v) <= hi: cands.append((u, round(v, 2)))
    if len(cands) == 1: return cands[0][1], cands[0][0]
    return None, ("ambig" if cands else "garbage")   # unresolved -> needs a crop read

# multi-column reads (Cr, ann) for quarters captured from a crop's prev/year-ago/annual columns
# (cross-validated where a quarter appears in two filings). Mainly STARHEALTH, whose col1-only yield was thin.
EXTRA = {
  ("STARHEALTH", 20220331): (-82.04, 20220520), ("STARHEALTH", 20221231): (210.47, 20230210),
  ("STARHEALTH", 20230331): (101.78, 20230522), ("STARHEALTH", 20230930): (125.30, 20231110),
  ("STARHEALTH", 20240630): (318.93, 20240810), ("STARHEALTH", 20240930): (111.29, 20241029),
  ("STARHEALTH", 20250331): (0.51, 20250520),   ("STARHEALTH", 20250630): (262.52, 20250729),
  ("STARHEALTH", 20251231): (128.22, 20260210), ("STARHEALTH", 20260331): (111.34, 20260428),
}
vals = {}   # (sym,qe) -> (val_cr, ann)
for (sym, qe) in sorted(crop):
    x = crop[(sym, qe)]
    val, how = resolve(sym, qe, x.get("preview"))
    if val is not None: vals[(sym, qe)] = (val, x.get("ann") or qe)
vals.update(EXTRA)   # multi-column reads extend/override

series = {}
for (sym, qe), (v, a) in vals.items(): series.setdefault(sym, []).append((qe, v, a))
for sym in ["GICRE", "ICICIGI", "LICI", "SBILIFE", "STARHEALTH"]:
    rows = sorted(series.get(sym, []))
    print("\n=== %s : %d quarters  (%d..%d) ===" % (sym, len(rows), rows[0][0] if rows else 0, rows[-1][0] if rows else 0))
    print("   " + "  ".join("%d=%s" % (qe, v) for qe, v, a in rows))

if APPLY:
    P = os.path.join(ROOT, "docs", "sf_fundamentals.json")
    F = json.loads(subprocess.check_output(["git", "-C", ROOT, "show", "origin/main:docs/sf_fundamentals.json"]))
    n = 0
    for sym in series:
        arr = [[qe, v, a, v, a] for qe, v, a in sorted(series[sym])]   # insurers: standalone == consolidated
        if arr: F[sym] = arr; n += 1; print("%s -> %d quarters" % (sym, len(arr)))
    json.dump(F, open(P, "w"), separators=(",", ":"))
    print("\nAPPLIED %d insurers to %s (rebuilt from origin/main)" % (n, P))
else:
    print("\n(inspect only — run with 'apply')")
