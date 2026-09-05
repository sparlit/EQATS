# -*- coding: utf-8 -*-
import json, gzip, bisect
from datetime import datetime, timedelta
D=json.loads(gzip.decompress(open('docs/sf_stock_data.bin','rb').read()))
data=D['data']; FUND=json.load(open('docs/sf_fundamentals.json'))
IDX=json.load(open('scripts/indices_history.json'))['Nifty 500']
SER={s:{'d':o['d'],'c':o['c'],'h':o.get('h'),'l':o.get('l')} for s,o in data.items()}
def di(s):return datetime(s//10000,(s//100)%100,s%100)
def to_int(dt):return dt.year*10000+dt.month*100+dt.day
def members(dstr):
    dn=int(dstr.replace('-',''));best=None
    for s in IDX:
        ed=int(s['effectiveDate'].replace('-',''))
        if ed<=dn and(best is None or ed>best[0]):best=(ed,s['symbols'])
    return set(best[1]) if best else set()
def price_at(s,dint):
    a=SER[s]['d'];i=bisect.bisect_right(a,dint)-1;return SER[s]['c'][i] if i>=0 else None
def hl52(s,dint):
    a=SER[s]['d'];i=bisect.bisect_right(a,dint)-1
    if i<0:return None
    lo=to_int(di(dint)-timedelta(days=365));h=SER[s]['h'];l=SER[s]['l'];c=SER[s]['c']
    hi=-1e18;low=1e18;k=i
    while k>=0 and a[k]>=lo:
        ph=h[k] if h else c[k];pl=l[k] if l else c[k]
        if ph>hi:hi=ph
        if pl<low:low=pl
        k-=1
    return hi,low
def profit_yoy(sym,dint):
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
def screen(dstr):
    dint=int(dstr.replace('-',''));mem=members(dstr);rows=[]
    for s in SER:
        if s not in mem:continue
        if not SER[s]['d'] or len(SER[s]['d'])<15:continue
        p=price_at(s,dint)
        if p is None:continue
        hl=hl52(s,dint)
        if not hl:continue
        hi,low=hl
        if hi<=0 or low<=0:continue
        if not((hi-p)/hi*100<10 and (p-low)/low*100>100):continue
        y=profit_yoy(s,dint)
        if y is None or y<=0:continue
        rows.append((s,y))
    rows.sort(key=lambda r:-r[1])
    return [r[0] for r in rows]
dates=['2022-09-30','2022-10-31','2022-11-30','2022-12-30','2023-01-31','2023-02-28','2023-03-31','2023-04-28','2023-05-31','2023-06-30','2023-07-31','2023-08-31','2023-09-29','2023-10-31','2023-11-30','2024-01-31','2024-02-29','2024-03-28','2024-04-30','2024-05-31','2024-06-28','2024-07-31','2024-08-30']
print('Nifty500 membership earliest snapshot:', min(s['effectiveDate'] for s in IDX))
out={d:screen(d) for d in dates}
json.dump(out, open('scripts/_mine_earlier.json','w'), separators=(',',':'))
for d in dates: print('%s : %d'%(d,len(out[d])))
