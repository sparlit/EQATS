# -*- coding: utf-8 -*-
import json, gzip, bisect
from datetime import datetime, timedelta
D=json.loads(gzip.decompress(open('docs/sf_stock_data.bin','rb').read()))
data=D['data']; FUND=json.load(open('docs/sf_fundamentals.json')); IDX=json.load(open('scripts/indices_history.json'))['Nifty 500']
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
def qualifies(s,ds):
    dint=int(ds.replace('-',''))
    if s not in members(ds):return (False,'not Nifty500 member')
    if not SER.get(s,{}).get('d') or len(SER[s]['d'])<15:return(False,'no price')
    p=price(s,dint)
    if p is None:return(False,'no price')
    h=hl(s,dint)
    if not h:return(False,'no 52w')
    hi,low=h
    d52=(hi-p)/hi*100; d52l=(p-low)/low*100
    if not(d52<10):return(False,'d52=%.1f (need <10)'%d52)
    if not(d52l>100):return(False,'d52low=%.0f (need >100)'%d52l)
    y=yoy(s,dint)
    if y is None:return(False,'no profit YoY (gap?)')
    if y<=0:return(False,'profitYoY=%.1f%% (<=0)'%y)
    return(True,'YoY=%.1f%%'%y)
# genuine Trendlyne-only misses from yesterday (TL had, we missed, after survivorship removal)
CHECK={
 '2024-07-31':['ZYDUSLIFE'], '2026-05-29':['ADANIENSOL'],
 '2022-10-31':['KARURVYSYA'],'2022-11-30':['KARURVYSYA'],'2023-01-31':['KARURVYSYA'],
 '2023-05-31':['KARURVYSYA'],'2023-06-30':['KARURVYSYA'],'2024-04-30':['KARURVYSYA'],
 '2023-02-28':['FINCABLES'],'2023-03-31':['FINCABLES'],'2023-04-28':['FINCABLES'],
 '2023-07-31':['INDIANB','MAHABANK'],'2023-08-31':['INDIANB','MAHABANK'],'2023-09-29':['INDIANB','MAHABANK'],
}
print('=== Does our UPDATED screen now qualify the genuine Trendlyne misses? ===')
for ds in sorted(CHECK):
    for s in CHECK[ds]:
        ok,why=qualifies(s,ds)
        print('  %s  %-11s -> %s  (%s)'%(ds,s,'QUALIFIES NOW' if ok else 'still excluded',why))
