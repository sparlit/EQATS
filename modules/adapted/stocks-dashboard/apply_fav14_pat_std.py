# -*- coding: utf-8 -*-
"""Apply the FAV14 P4 standalone-PAT backfill (scripts/fav14_pat_std_fills.json) into the
sf_fundamentals twins, FILL-ONLY and idempotent. PLAN_FAV14_COVERAGE_2009.md P4.

Source: BSE detailed-results JSON (Corp_detailedResult_Transpose_ng), standalone (.00), value
÷10 = Rs cr, Date-End validated == quarter-end, EPS-consistent. annStd = SEBI deadline (QE+45d,
Q4 +60d) matching fill_ann_dates.py — conservative, never look-ahead.

Guard: writes patStd/annStd ONLY where the (sym,qe) row is absent or its patStd slot is null;
a cell already holding a DIFFERENT patStd (>max(0.5, 3%)) is left alone and reported. Re-runnable
after the nightly fundamentals refresh advances sf_fundamentals (fill-only never clobbers).
Run: python3 scripts/apply_fav14_pat_std.py [--apply]
"""
import json, os, sys
HERE=os.path.dirname(os.path.abspath(__file__)); ROOT=os.path.dirname(HERE)
TWINS=[os.path.join(ROOT,"docs","sf_fundamentals.json"), os.path.join(HERE,"fundamentals.json")]
LED=json.load(open(os.path.join(HERE,"fav14_pat_std_fills.json")))["fills"]
DRY = "--apply" not in sys.argv
def rm(rows): return {r[0]:r for r in rows}
conflicts=[]; would=0
base=json.load(open(TWINS[0]))
for sym,qs in LED.items():
    m=rm(base.get(sym,[]))
    for qe,cell in qs.items():
        pat,ann=cell[0],cell[1]
        qe=int(qe); r=m.get(qe)
        if r is None or (len(r)>1 and r[1] is None): would+=1
        elif len(r)>1 and r[1] is not None and abs(r[1]-pat)>max(0.5,abs(r[1])*0.03):
            conflicts.append((sym,qe,r[1],pat))
print(("DRY " if DRY else "")+f"fills to apply: {would} | conflicts (left alone): {len(conflicts)}")
for c in conflicts[:15]: print("  CONFLICT",c)
if DRY: sys.exit(0)
for tw in TWINS:
    d=json.load(open(tw)); ch=0
    for sym,qs in LED.items():
        rows=d.setdefault(sym,[]); m=rm(rows)
        for qe,cell in qs.items():
            pat,ann=cell[0],cell[1]
            qe=int(qe)
            if qe in m:
                r=m[qe]
                while len(r)<5: r.append(None)
                if r[1] is None: r[1]=pat; r[2]=ann; ch+=1
            else:
                rows.append([qe,pat,ann,None,None]); ch+=1
        rows.sort(key=lambda r:r[0])
    json.dump(d, open(tw,"w"), separators=(",",":"))
    print(f"wrote {os.path.relpath(tw,ROOT)}: +{ch}")
