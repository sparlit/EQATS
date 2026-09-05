# -*- coding: utf-8 -*-
import json
IDX=json.load(open('scripts/indices_history.json'))['Nifty 500']
mine=json.load(open('scripts/_mine_all.json'))
def members(ds):
    dn=int(ds.replace('-',''));b=None
    for s in IDX:
        ed=int(s['effectiveDate'].replace('-',''))
        if ed<=dn and (b is None or ed>b[0]): b=(ed,s['symbols'])
    return set(b[1]) if b else set()
tT=tM=0; rows=[]
for ln in open('scripts/_tl_full.txt'):
    ln=ln.rstrip('\n')
    if '|' not in ln: continue
    d,s=ln.split('|',1)
    raw=[x for x in s.split(',') if x]; M=members(d)
    sf=[x for x in raw if x in M]; ours=set(mine.get(d,[]))
    match=[x for x in sf if x in ours]; miss=[x for x in sf if x not in ours]
    tT+=len(sf); tM+=len(match)
    rows.append((d,len(raw),len(sf),len(ours),len(match),miss))
print('%-10s | rawTL | TL-SF | ours | match | misses'%'month')
for d,r,sf,ou,m,miss in rows:
    mm=','.join(miss[:5])+((' +%d'%(len(miss)-5)) if len(miss)>5 else '')
    print('%-10s | %4d  | %4d  | %4d | %4d  | %s'%(d,r,sf,ou,m,mm or '-'))
print()
print('TOTAL Mar23-Jun26:  TL survivorship-free=%d   match=%d   rate=%.1f%%'%(tT,tM,100*tM/tT))
