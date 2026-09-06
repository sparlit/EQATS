# -*- coding: utf-8 -*-
"""Re-apply official split/bonus adjustments (corp_actions.json 'factors') to docs/sf_stock_data.bin
where today's refresh left them UNADJUSTED. For each (sym, exdate, factor): if the raw close ratio
across the ex-date is still ~factor (unadjusted), multiply all pre-exdate prices by factor (and raw
volume by 1/factor). Skip events already adjusted (ratio ~1) and 'noadjust' entries. Idempotent.
Run: python -X utf8 fix_corp_actions.py"""
import json, gzip, os, bisect
HERE=os.path.dirname(os.path.abspath(__file__)); ROOT=os.path.dirname(HERE)
path=os.path.join(ROOT,'docs','sf_stock_data.bin')
D=json.loads(gzip.decompress(open(path,'rb').read())); data=D['data']
CA=json.load(open(os.path.join(HERE,'corp_actions.json')))
FAC=CA['factors']; NOADJ=CA.get('noadjust',{})
PRICE=['c','hb','lb','ob','vw']
fixed=[]; skipped=0
for sym, events in FAC.items():
    o=data.get(sym)
    if not o or not o.get('d'): continue
    a=o['d']
    noset=set(NOADJ.get(sym,[]))
    todo=[]
    for ex,fac in sorted(events,key=lambda e:e[0]):
        if ex in noset: continue
        i=bisect.bisect_left(a,ex)            # first index on/after ex-date
        if i<=0 or i>=len(a): continue
        ratio=o['c'][i]/o['c'][i-1] if o['c'][i-1] else 1
        # unadjusted iff the raw drop (~fac) is still present; adjusted -> ratio ~1.
        # discriminator works for ALL factors incl. small bonuses (0.8/0.833/0.909):
        # raw ratio must be closer to `fac` than to 1, and within 12% of `fac`.
        if ratio < (fac+1)/2 and abs(ratio/fac - 1) <= 0.12:
            todo.append((ex,fac,i,round(ratio,3)))
    if not todo: continue
    # apply latest-first so earlier segments accumulate factors of all later events
    for ex,fac,i,ratio in sorted(todo,key=lambda e:-e[0]):
        cut=bisect.bisect_left(a,ex)
        for f in PRICE:
            if f in o and o[f]:
                for k in range(cut):
                    if o[f][k] is not None: o[f][k]=round(o[f][k]*fac,4)
        if 'v' in o and o['v']:
            for k in range(cut):
                if o['v'][k] is not None: o['v'][k]=int(o['v'][k]/fac)
    fixed.append((sym,[(e[0],e[1],e[3]) for e in todo]))
print('fixed %d symbols'%len(fixed))
for s,evs in fixed[:40]: print('  %-12s %s'%(s,evs))
# sanity
for s in ['MOTILALOFS','INOXWIND','ADANIPOWER']:
    if s in data:
        a=data[s]['d']; c=data[s]['c']
        import bisect as b
        def cl(dt):
            i=b.bisect_right(a,dt)-1; return round(c[i],1) if i>=0 else None
        print('  %-11s Apr2024=%s Jul2024=%s now=%s'%(s,cl(20240401),cl(20240731),round(c[-1],1)))
buf=gzip.compress(json.dumps(D,separators=(',',':')).encode())
open(path,'wb').write(buf); print('SAVED %d bytes'%len(buf))
