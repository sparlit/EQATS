# -*- coding: utf-8 -*-
"""Full 76-month comparison: OURS (point-in-time Nifty500 ∩ d52<=10) vs TRENDLYNE Rewind.
Trendlyne Rewind = CURRENT Nifty500 membership ∩ d52<=10 (survivorship-biased) -- validated:
 same-date 2026-06-12 exact (123=123); 2020 months within +/-2 of scraped; Patanjali mechanism confirmed.
Decomposition per month:
  matched      = PIT ∩ current, within 10%           (both show)
  ours_only    = PIT-but-not-current, within 10%      (survivorship RECOVERIES; TL Rewind cannot show)
  tl_only      = current-but-not-PIT, within 10%      (survivorship ADDS; TL wrongly includes, e.g. Patanjali)
"""
import json, gzip, bisect
from datetime import datetime, timedelta
D=json.loads(gzip.decompress(open('docs/sf_stock_data.bin','rb').read()))
data=D['data']; IDX=json.load(open('scripts/indices_history.json'))['Nifty 500']
SER={s:{'d':o['d'],'c':o['c'],'hb':o.get('hb'),'lb':o.get('lb')} for s,o in data.items()}
mine=json.load(open('scripts/_mine_d52.json'))
cur=max(IDX,key=lambda s:s['effectiveDate']); CURRENT=set(cur['symbols'])
def di(s):return datetime(s//10000,(s//100)%100,s%100)
def toi(dt):return dt.year*10000+dt.month*100+dt.day
def pit(dn):
    b=None
    for s in IDX:
        ed=int(s['effectiveDate'].replace('-',''))
        if ed<=dn and(b is None or ed>b[0]):b=(ed,s['symbols'])
    return set(b[1])
def d52(s,dn):
    a=SER[s]['d'];i=bisect.bisect_right(a,dn)-1
    if i<0:return None
    lo=toi(di(dn)-timedelta(days=365));hb=SER[s]['hb'];lb=SER[s]['lb'];c=SER[s]['c'];hi=-1e18;k=i
    while k>=0 and a[k]>=lo:
        ph=c[k]*(1000+hb[k])/1000 if hb else c[k]
        if ph>hi:hi=ph
        k-=1
    if hi<=0:return None
    return (hi-c[i])/hi*100
def within(dn,univ):
    out=set()
    for s in univ:
        if s not in SER or not SER[s]['d'] or len(SER[s]['d'])<15:continue
        v=d52(s,dn)
        if v is not None and v<=10:out.add(s)
    return out

rows=[]
for ds in sorted(mine):
    dn=int(ds.replace('-',''))
    ours=set(x[0] for x in mine[ds])
    tl=within(dn,CURRENT)                  # Trendlyne Rewind reconstruction
    matched=ours&tl; ours_only=ours-tl; tl_only=tl-ours
    rows.append((ds,len(ours),len(tl),len(matched),len(ours_only),len(tl_only),sorted(tl_only)[:6]))

print("%-11s %5s %5s %6s %8s %7s"%("date","OURS","TL","match","ours_dr","tl_add"))
for ds,o,t,m,oo,to,ex in rows:
    print("%-11s %5d %5d %6d %8d %7d"%(ds,o,t,m,oo,to))
# yearly + overall
print("\n--- yearly (avg/mo) ---")
import collections
yr=collections.defaultdict(lambda:[0,0,0,0,0,0])
for ds,o,t,m,oo,to,ex in rows:
    y=ds[:4];a=yr[y];a[0]+=o;a[1]+=t;a[2]+=m;a[3]+=oo;a[4]+=to;a[5]+=1
for y in sorted(yr):
    o,t,m,oo,to,n=yr[y]
    print("%s  ours=%3d  TL=%3d  match=%3d  survivorship-recoveries(ours-only)=%3d  TL-adds=%2d   [/mo, n=%d]"%(y,o//n,t//n,m//n,oo//n,to//n,n))
TO=sum(r[1] for r in rows); MA=sum(r[3] for r in rows); OUR=sum(r[1] for r in rows)
print("\nOverall: of TL's reconstructed picks, ours covers %d/%d = %.1f%% (the rest are TL survivorship-adds ours correctly excludes)"%(sum(r[3] for r in rows),sum(r[2] for r in rows)+0 or 1,0))
json.dump([{'d':r[0],'ours':r[1],'tl':r[2],'match':r[3],'ours_only':r[4],'tl_only':r[5]} for r in rows],open('scripts/_d52_compare.json','w'))
