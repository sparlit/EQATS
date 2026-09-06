# -*- coding: utf-8 -*-
"""Replica of the live backtest engine for the user's exact strategy, to explain holdings count.
Strategy: Nifty500, monthly, sort profitYoyPct(con) high, top5, filters d52<=10 & d52low>=100 &
profitYoy>0, method 'hold winners / replace only exits'. From 2020-03-31 to data end."""
import json, gzip, datetime
D = json.loads(gzip.decompress(open('../docs/sf_stock_data.bin', 'rb').read()))
data = D['data']; END = D['end']
FUND = json.load(open('../docs/sf_fundamentals.json'))
HIST = json.load(open('n500_hist.json'))

def od(ymd): return datetime.date(ymd // 10000, (ymd // 100) % 100, ymd % 100).toordinal()
def ymd_of(ordn): d = datetime.date.fromordinal(ordn); return d.year * 10000 + d.month * 100 + d.day
SER = {}
for s, o in data.items():
    if o.get('d'): SER[s] = {'o': [od(x) for x in o['d']], 'c': o['c'], 'hb': o.get('hb'), 'lb': o.get('lb')}

def le(ords, t):
    lo, hi, a = 0, len(ords) - 1, -1
    while lo <= hi:
        m = (lo + hi) // 2
        if ords[m] <= t: a = m; lo = m + 1
        else: hi = m - 1
    return a
def priceAt(s, t):
    x = SER.get(s);
    if not x: return None
    i = le(x['o'], t); return x['c'][i] if i >= 0 else None
def hl52(s, t):
    x = SER.get(s);
    if not x: return None
    i = le(x['o'], t)
    if i < 0: return None
    hi, low, lo = -1e18, 1e18, t - 365
    for k in range(i, -1, -1):
        if x['o'][k] < lo: break
        c = x['c'][k]; ph = c * (1000 + x['hb'][k]) / 1000 if x['hb'] else c; pl = c * (1000 - x['lb'][k]) / 1000 if x['lb'] else c
        if ph > hi: hi = ph
        if pl < low: low = pl
    return (hi, low) if hi > 0 else None
def rsi_ok(s, t):
    x = SER.get(s);
    if not x: return False
    i = le(x['o'], t); return i >= 15
def profitAt(s, di):
    arr = FUND.get(s)
    if not arr: return None
    for npi, ai in [(3, 4), (1, 2)]:
        cur = None
        for q in reversed(arr):
            if q[npi] is not None and q[ai] is not None and q[ai] <= di: cur = q; break
        if cur is None: continue
        be = cur[0] - 10000; base = next((q for q in arr if q[0] == be and q[npi] is not None), None)
        if base is None: continue
        b, c = base[npi], cur[npi]
        return (c - b) / b * 100 if b >= 5 else None
    return None
def membersAsOf(dstr):
    best = max((h for h in HIST if h['effectiveDate'] <= dstr), key=lambda h: h['effectiveDate'], default=None)
    return set(best['symbols']) if best else set()
def factors(t):
    dstr = datetime.date.fromordinal(t).isoformat(); mem = membersAsOf(dstr); di = ymd_of(t)
    rows = []
    for s in mem:
        p = priceAt(s, t); p0 = priceAt(s, t - 30)
        if p is None or p0 is None or p0 <= 0: continue
        if not rsi_ok(s, t): continue
        hl = hl52(s, t)
        if not hl or hl[0] <= 0 or hl[1] <= 0: continue
        d52 = (hl[0] - p) / hl[0] * 100; d52low = (p - hl[1]) / hl[1] * 100
        py = profitAt(s, di)
        rows.append({'s': s, 'p': p, 'd52': d52, 'd52low': d52low, 'py': py})
    return rows

# months: month-ends from 2020-03 to END, last replaced by END
months = []; y, m = 2020, 3; ey, em = int(END[:4]), int(END[5:7])
while (y < ey) or (y == ey and m <= em):
    last = (datetime.date(y + (m == 12), (m % 12) + 1, 1) - datetime.timedelta(days=1))
    months.append(last.isoformat()); m += 1
    if m > 12: m = 1; y += 1
months[-1] = END
N = 5; pos = {}; cash = 0.0; started = False; cap = 100000.0; traj = []
for md in months:
    t = od(int(md.replace('-', '')))
    rows = [r for r in factors(t) if r['d52'] <= 10 and r['d52low'] >= 100 and (r['py'] is not None and r['py'] > 0)]
    rows.sort(key=lambda r: -r['py'])
    target = rows[:N]; tset = {r['s'] for r in target}; tmap = {r['s']: r for r in target}
    if not started:
        per = cap / N; pos = {r['s']: per / r['p'] for r in target}; cash = cap - per * len(target); started = True
    else:
        def val(s): p = priceAt(s, t); return pos[s] * p if p else 0
        exits = [s for s in pos if s not in tset]; proceeds = sum(val(s) for s in exits)
        for s in exits: del pos[s]
        entries = [r for r in target if r['s'] not in pos]
        openSlots = max(1, N - len(pos))                  # empty slots = N - winners kept
        avail = proceeds + cash; perSlot = avail / openSlots
        for e in entries:
            if perSlot <= 1: break
            pos[e['s']] = perSlot / e['p']; avail -= perSlot
        cash = max(0, avail)                              # unfilled slots stay in cash
    nav = sum((priceAt(s, t) or 0) * q for s, q in pos.items()) + cash
    traj.append((md, len(pos), round(cash / nav * 100, 1) if nav else 0, list(pos.keys())))

print('rebalances:', len(traj))
print('--- last 8 rebalances: date | #holdings | cash%% | stocks ---')
for md, n, cw, hold in traj[-8:]:
    print('  %s  held=%d  cash=%4.1f%%  %s' % (md, n, cw, hold))
print()
print('LATEST holdings:', traj[-1][3], '| cash%%:', traj[-1][2])
import collections
print('holding-count distribution across all rebalances:', dict(collections.Counter(n for _, n, _, _ in traj)))
