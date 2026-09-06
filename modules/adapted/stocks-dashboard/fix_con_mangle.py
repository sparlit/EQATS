# -*- coding: utf-8 -*-
"""Propose (and, with apply=1, write) corrected npCon for confirmed consolidated-mangle quarters.
Correction = median(con/std over the stock's NORMAL quarters) * std_of_broken_quarter, i.e. restore
con using the stock's own typical con-vs-standalone relationship and the (correct) standalone value.
Run: python fix_con_mangle.py        -> propose only
     python fix_con_mangle.py apply  -> write docs/sf_fundamentals.json"""
import json,os,sys
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P=os.path.join(ROOT,'docs','sf_fundamentals.json'); F=json.load(open(P))
APPLY = (len(sys.argv)>1 and sys.argv[1]=='apply')
MANGLES=[('HEROMOTOCO',20190331),('SRF',20230331),('JINDALSAW',20240930),('PIDILITIND',20190930),
 ('RITES',20190930),('RITES',20210331),('UNITDSPR',20190331),('KPIL',20190331),
 ('ZENSARTECH',20200930),('PRAJIND',20230331),('PRAJIND',20240930),('PRAJIND',20251231)]
# EXCLUDED (not auto-fixed): TRENT 20220331 (genuine omicron-quarter sub losses), TATAINVEST 20210331
# (holding co, con/std ratio too volatile), ZYDUSLIFE 20190930 (annual reconciliation inconclusive).
OVERRIDE={('SRF',20230331):562.0}   # filed consolidated PAT (confirmed vs ratio estimate)
def med(xs):
    xs=sorted(xs); n=len(xs);
    return None if not n else (xs[n//2] if n%2 else (xs[n//2-1]+xs[n//2])/2)
print('%-12s %-9s %8s %8s %6s %6s %8s   neighbours(con)'%('SYM','quarter','oldCon','npStd','ratio','spread','NEWcon'))
nchg=0
for sym,qe in MANGLES:
    arr=F.get(sym,[]);
    ratios=[]
    for q in arr:
        if len(q)>3 and q[1] is not None and q[3] is not None and abs(q[1])>10 and abs(q[3])>0.2*abs(q[1]):
            ratios.append(q[3]/q[1])
    r=med(ratios); spread=(max(ratios)-min(ratios)) if ratios else None
    # locate quarter + neighbours
    cons=[(x[0],x[3]) for x in arr if len(x)>3 and x[3] is not None]; qes=[c[0] for c in cons]
    row=next((x for x in arr if x[0]==qe),None)
    if not row or r is None: print('%-12s %-9d  -- could not compute'%(sym,qe)); continue
    std=row[1]; old=row[3] if len(row)>3 else None
    new=OVERRIDE.get((sym,qe), round(r*std,2))
    try: i=qes.index(qe); prev=cons[i-1][1] if i>0 else None; nxt=cons[i+1][1] if i<len(cons)-1 else None
    except: prev=nxt=None
    print('%-12s %-9d %8s %8.1f %6.2f %6.2f %8.1f   %s / %s'%(sym,qe,str(old),std,r,spread,new,('%.1f'%prev if prev is not None else '-'),('%.1f'%nxt if nxt is not None else '-')))
    if APPLY:
        while len(row)<5: row.append(None)
        row[3]=new; nchg+=1
if APPLY:
    json.dump(F,open(P,'w'),separators=(',',':')); print('\nAPPLIED %d corrections to %s'%(nchg,P))
else:
    print('\n(proposal only — run with "apply" to write)')
