# -*- coding: utf-8 -*-
"""Reproduce Trendlyne Rewind locally: Rewind = (CURRENT Nifty500 membership) ∩ (d52<=10 at past date).
Validate against actually-scraped TL counts. If it matches, the full 76-month comparison is computable
without scraping (ours=PIT membership; TL=current membership; gap=survivorship)."""
import json, gzip, bisect
from datetime import datetime, timedelta
D=json.loads(gzip.decompress(open('docs/sf_stock_data.bin','rb').read()))
data=D['data']; IDX=json.load(open('scripts/indices_history.json'))['Nifty 500']
SER={s:{'d':o['d'],'c':o['c'],'hb':o.get('hb'),'lb':o.get('lb')} for s,o in data.items()}
def di(s):return datetime(s//10000,(s//100)%100,s%100)
def toi(dt):return dt.year*10000+dt.month*100+dt.day
# CURRENT membership = latest snapshot
cur=max(IDX,key=lambda s:s['effectiveDate']); CURRENT=set(cur['symbols'])
print('CURRENT Nifty500 snapshot:',cur['effectiveDate'],'=',len(CURRENT),'members')
def members_pit(dn):
    b=None
    for s in IDX:
        ed=int(s['effectiveDate'].replace('-',''))
        if ed<=dn and(b is None or ed>b[0]):b=(ed,s['symbols'])
    return set(b[1]) if b else set()
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
def screen(dn,univ):
    out=[]
    for s in univ:
        if s not in SER or not SER[s]['d'] or len(SER[s]['d'])<15:continue
        v=d52(s,dn)
        if v is not None and v<=10:out.append(s)
    return set(out)
TESTS={'2020-03-31':5,'2020-04-30':29,'2020-05-29':31,'2020-06-30':43,'2020-07-31':74,
       '2020-08-31':60,'2021-06-30':135,'2026-06-12':123}
print('\n%-12s %6s %6s %6s   (model=current∩d52<=10)'%('date','TLact','MODEL','ours-PIT'))
for ds,tlact in TESTS.items():
    dn=int(ds.replace('-',''))
    model=screen(dn,CURRENT); pit=screen(dn,members_pit(dn))
    print('%-12s %6d %6d %6d'%(ds,tlact,len(model),len(pit)))
