# -*- coding: utf-8 -*-
import json, gzip, bisect
from datetime import datetime, timedelta
D=json.loads(gzip.decompress(open('docs/sf_stock_data.bin','rb').read()))
data=D['data']; FUND=json.load(open('docs/sf_fundamentals.json')); IDX=json.load(open('scripts/indices_history.json'))['Nifty 500']
SER={s:{'d':o['d'],'c':o['c'],'hb':o.get('hb'),'lb':o.get('lb')} for s,o in data.items()}
def di(s):return datetime(s//10000,(s//100)%100,s%100)
def toi(dt):return dt.year*10000+dt.month*100+dt.day
def members(ds):
    dn=int(ds.replace('-',''));b=None
    for s in IDX:
        ed=int(s['effectiveDate'].replace('-',''))
        if ed<=dn and(b is None or ed>b[0]):b=(ed,s['symbols'])
    return set(b[1]) if b else set()
def price(s,dint):
    a=SER[s]['d'];i=bisect.bisect_right(a,dint)-1;return SER[s]['c'][i] if i>=0 else None
def hl(s,dint):
    a=SER[s]['d'];i=bisect.bisect_right(a,dint)-1
    if i<0:return None
    lo=toi(di(dint)-timedelta(days=365));hb=SER[s]['hb'];lb=SER[s]['lb'];c=SER[s]['c'];hi=-1e18;low=1e18;k=i
    while k>=0 and a[k]>=lo:
        ph=c[k]*(1000+hb[k])/1000 if hb else c[k]      # decode per-mil intraday high (engine hl52)
        pl=c[k]*(1000-lb[k])/1000 if lb else c[k]      # decode per-mil intraday low
        if ph>hi:hi=ph
        if pl<low:low=pl
        k-=1
    return hi,low
def yoy(sym,dint):
    arr=FUND.get(sym)
    if not arr:return None
    for npi,ani in((3,4),(1,2)):
        cur=None
        for q in reversed(arr):
            if len(q)>ani and q[npi] is not None and q[ani] is not None and q[ani]<=dint:cur=q;break
        if not cur:continue
        bq=cur[0]-10000;base=None
        for q in arr:
            if q[0]==bq and q[npi] is not None:base=q;break
        if not base:continue
        b=base[npi];c=cur[npi]
        if b==0:continue
        return (c-b)/abs(b)*100
    return None
def screen(ds):
    dint=int(ds.replace('-',''));M=members(ds);rows=[]
    for s in SER:
        if s not in M or not SER[s]['d'] or len(SER[s]['d'])<15:continue
        p=price(s,dint)
        if p is None:continue
        h=hl(s,dint)
        if not h:continue
        hi,low=h
        if hi<=0 or low<=0 or not((hi-p)/hi*100<10 and (p-low)/low*100>100):continue
        y=yoy(s,dint)
        if y is None or y<=0:continue
        rows.append((s,round(y,1)))
    rows.sort(key=lambda r:-r[1]); return [r[0] for r in rows]
DATES=['2022-12-30','2023-01-31','2023-02-28','2023-03-31','2023-04-28','2023-05-31','2023-06-30','2023-07-31','2023-08-31','2023-09-29','2023-10-31','2023-11-30','2023-12-29','2024-01-31','2024-02-29','2024-03-28','2024-04-30','2024-05-31','2024-06-28','2024-07-31','2024-08-30','2024-09-30','2024-10-31','2024-11-29','2024-12-31','2025-01-31','2025-02-28','2025-03-28','2025-04-30','2025-05-30','2025-06-30','2025-07-31','2025-08-29','2025-09-30','2025-10-31','2025-11-28','2025-12-31','2026-01-30','2026-02-27','2026-03-30','2026-04-30','2026-05-29','2026-06-12']
out={d:screen(d) for d in DATES}
json.dump(out,open('scripts/_mine_all.json','w'),separators=(',',':'))
for d in DATES: print('%s : %d'%(d,len(out[d])))
