# -*- coding: utf-8 -*-
"""Systematic scan of docs/sf_fundamentals.json for CONSOLIDATED-profit mangle errors:
a quarter whose npCon collapses to ~0 while npStd is materially non-zero AND the stock's
con NORMALLY tracks std (single-entity company) AND neighbouring con quarters are normal.
Excludes genuine NCI / overseas-loss names (con persistently != std) so they aren't false-flagged.
Output ranked by index relevance + severity."""
import json,os
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
F=json.load(open(os.path.join(ROOT,'docs','sf_fundamentals.json')))
IDX=json.load(open(os.path.join(ROOT,'scripts','indices_history.json')))['Nifty 500']
snaps=sorted(IDX,key=lambda s:s['effectiveDate']); CURRENT=set(snaps[-1]['symbols'])
ALLMEM=set(); [ALLMEM.update(s['symbols']) for s in IDX]
def med(xs):
    xs=sorted(xs); n=len(xs); return xs[n//2] if n else 0
flags=[]
for sym,arr in F.items():
    rows=[q for q in arr if len(q)>3 and q[1] is not None and q[3] is not None]  # both std & con
    if len(rows)<5: continue
    # does con normally track std? (single-entity: con ~ std)
    track=[1 if abs(q[3]-q[1])<=0.4*max(abs(q[1]),abs(q[3]),10) else 0 for q in rows if abs(q[1])>10]
    if len(track)<4 or sum(track)/len(track)<0.6: continue     # con persistently != std -> real NCI, skip
    medc=med([abs(q[3]) for q in rows if abs(q[3])>1])
    confull=[(q[0],q[3]) for q in arr if len(q)>3 and q[3] is not None]
    cmap={qe:c for qe,c in confull}; qes=[qe for qe,_ in confull]
    for q in arr:
        if len(q)<=3 or q[1] is None or q[3] is None: continue
        std,con=q[1],q[3]
        if abs(std)>15 and abs(con)<0.2*abs(std) and medc>15 and abs(con)<0.2*medc:
            i=qes.index(q[0]); prev=cmap[qes[i-1]] if i>0 else None; nxt=cmap[qes[i+1]] if i<len(qes)-1 else None
            sev=abs(std)  # bigger standalone => more material
            flags.append((sev, sym, q[0], std, con, round(medc,1), prev, nxt, sym in CURRENT, sym in ALLMEM))
# rank: current members first, then ever-members, then by severity
flags.sort(key=lambda f:(not f[8], not f[9], -f[0]))
incur=sum(1 for f in flags if f[8]); inmem=sum(1 for f in flags if f[9])
print('CON-MANGLE candidates: %d total | %d current Nifty500 | %d ever-Nifty500'%(len(flags),incur,inmem))
print('%-12s %-9s %9s %8s %8s %8s %8s  idx'%('SYM','quarter','npStd','npCon','typCon','prevCon','nextCon'))
for sev,sym,qe,std,con,medc,prev,nxt,cur,mem in flags:
    tag='CUR' if cur else ('MEM' if mem else '-')
    print('%-12s %-9d %9.1f %8.2f %8.1f %8s %8s  %s'%(sym,qe,std,con,medc,('%.1f'%prev if prev is not None else '-'),('%.1f'%nxt if nxt is not None else '-'),tag))
