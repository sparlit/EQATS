# -*- coding: utf-8 -*-
"""For each (sym,date) miss, report exactly which screen criterion fails and the values used:
price, 52w high/low, d52, d52low, current/base quarter + profit values + profitYoY (con & std)."""
import json, gzip, bisect
from datetime import datetime, timedelta
D=json.loads(gzip.decompress(open('docs/sf_stock_data.bin','rb').read()))
data=D['data']; FUND=json.load(open('docs/sf_fundamentals.json'))
IDX=json.load(open('scripts/indices_history.json'))['Nifty 500']
SER={s:{'d':o['d'],'c':o['c'],'h':o.get('h'),'l':o.get('l')} for s,o in data.items()}
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
    lo=toi(di(dint)-timedelta(days=365));h=SER[s]['h'];l=SER[s]['l'];c=SER[s]['c'];hi=-1e18;low=1e18;k=i
    while k>=0 and a[k]>=lo:
        ph=h[k] if h else c[k];pl=l[k] if l else c[k]
        if ph>hi:hi=ph
        if pl<low:low=pl
        k-=1
    return hi,low
def yoy_detail(sym,dint,npi,ani):
    arr=FUND.get(sym)
    if not arr:return None
    cur=None
    for q in reversed(arr):
        if len(q)>ani and q[npi] is not None and q[ani] is not None and q[ani]<=dint:cur=q;break
    if not cur:return ('no-cur',None,None,None,None)
    bq=cur[0]-10000;base=None
    for q in arr:
        if q[0]==bq and len(q)>npi and q[npi] is not None:base=q;break
    if not base:return ('no-base',cur[0],cur[npi],bq,None)
    b=base[npi];c=cur[npi]
    if b==0:return ('base0',cur[0],c,bq,b)
    return ((c-b)/abs(b)*100,cur[0],c,bq,b)

MISS=[('SWANCORP','2022-12-30'),('FINCABLES','2023-02-28'),('FINCABLES','2023-03-31'),
      ('FINCABLES','2023-04-28'),('JSL','2023-06-30'),('JSL','2023-08-31'),('JSL','2023-12-29'),
      ('SAMMAANCAP','2024-02-29'),('LINDEINDIA','2024-04-30'),('MCX','2024-04-30'),
      ('LLOYDSME','2024-04-30'),('LLOYDSME','2024-05-31')]
for sym,ds in MISS:
    dint=int(ds.replace('-',''))
    inmem=sym in members(ds)
    p=price(sym,dint); h=hl(sym,dint)
    line='%-11s %s  member=%s'%(sym,ds,inmem)
    if p is None or not h: print(line,' NO PRICE'); continue
    hi,low=h; d52=(hi-p)/hi*100; d52low=(p-low)/low*100
    con=yoy_detail(sym,dint,3,4); std=yoy_detail(sym,dint,1,2)
    print(line)
    print('     price=%.1f 52wHi=%.1f 52wLo=%.1f  d52=%.1f%% (<10? %s)  d52low=%.0f%% (>100? %s)'%(
        p,hi,low,d52,d52<10,d52low,d52low>100))
    print('     CON: yoy=%s cur=%s np=%s base=%s np=%s'%(round(con[0],1) if isinstance(con[0],float) else con[0],con[1],con[2],con[3],con[4]))
    print('     STD: yoy=%s cur=%s np=%s base=%s np=%s'%(round(std[0],1) if isinstance(std[0],float) else std[0],std[1],std[2],std[3],std[4]))
