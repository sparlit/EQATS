# -*- coding: utf-8 -*-
"""Live-faithful backward-window screen: MERGED release asset (intraday h/l 52w) + PCBL manual-merge
+ backfilled fundamentals + Nifty500 membership. Mirrors backtest-engine.js hl52 (intraday)."""
import json, gzip, bisect, calendar
from datetime import datetime, timedelta
D=json.loads(gzip.decompress(open('_live_release.bin','rb').read()))
data=D['data']; meta=D.get('meta',{})
# PCBL manual merge (same as committed update_sf_data fix)
for new,old in {'PCBL':'PHILIPCARB'}.items():
    on=data.get(new); oo=data.get(old)
    if on and oo and on['d'] and oo['d'] and oo['d'][0]<on['d'][0]:
        idx=[i for i,dd in enumerate(oo['d']) if dd<on['d'][0]]
        for f in ('d','c','t','h','l','op','v','dv','vw'):
            if f in oo and f in on: on[f]=[oo[f][i] for i in idx]+on[f]
        data.pop(old,None)
FUND=json.load(open('docs/sf_fundamentals.json'))
IDX=json.load(open('scripts/indices_history.json'))['Nifty 500']
SER={s:{'d':o['d'],'c':o['c'],'h':o.get('h'),'l':o.get('l')} for s,o in data.items()}
def di(s):return datetime(s//10000,(s//100)%100,s%100)
def toi(dt):return dt.year*10000+dt.month*100+dt.day
def members(ds):
    dn=int(ds.replace('-',''));b=None
    for s in IDX:
        ed=int(s['effectiveDate'].replace('-',''))
        if ed<=dn and(b is None or ed>b[0]):b=(ed,s['symbols'])
    return b[1] if b else []
def price(s,dint):
    a=SER[s]['d'];i=bisect.bisect_right(a,dint)-1;return SER[s]['c'][i] if i>=0 else None
def hl(s,dint):
    a=SER[s]['d'];i=bisect.bisect_right(a,dint)-1
    if i<0:return None
    lo=toi(di(dint)-timedelta(days=365));h=SER[s]['h'];l=SER[s]['l'];c=SER[s]['c'];hi=-1e18;low=1e18;k=i
    while k>=0 and a[k]>=lo:
        ph=h[k] if h else c[k];pl=l[k] if l else c[k]   # intraday when present (merged asset has h/l)
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
            if q[0]==bq and len(q)>npi and q[npi] is not None:base=q;break
        if not base:continue
        b=base[npi];c=cur[npi]
        if b==0:continue
        return (c-b)/abs(b)*100
    return None
def screen(ds):
    dint=int(ds.replace('-',''));M=set(members(ds));rows=[]
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
DATES=[]
for y in range(2020,2023):
    for m in range(1,13):
        if y==2020 and m<3: continue
        if y==2022 and m>11: continue
        DATES.append("%04d-%02d-%02d"%(y,m,calendar.monthrange(y,m)[1]))
mine={d:screen(d) for d in DATES}
json.dump(mine,open('scripts/_mineB_live.json','w'),separators=(',',':'))
print('regenerated _mineB_live.json (merged asset, intraday 52w, PCBL merged)')
