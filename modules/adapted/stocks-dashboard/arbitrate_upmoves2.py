# -*- coding: utf-8 -*-
"""Up-move arbiter v2 (runbook §126) — decides each inferred factor>=1.8 adjustment from the RAW tape alone,
keyed on CALENDAR-adjacent actual traded closes (v1's bin-bar-adjacency misread muhurat glitches).

For each event pull the raw bhavcopy closes in [ex-20d, ex+12d]. Let
  pre      = last actual traded close strictly before ex        (skips the nominal Re-1 prevclose field)
  exclose  = raw close on ex
  post     = median of the 2nd..6th actual traded closes after ex
  raw_step = exclose / pre           (did the raw price actually change basis on ex?)
  persist  = post / exclose          (did the new level hold, or snap back?)

Verdict (factor F = the adjustment the bake applied):
  REAL-BASIS-CHANGE  raw_step within 12% of F, persist in [0.80,1.25]  -> the raw price genuinely and
                     permanently re-based (reverse split / consolidation / relisting). The bake correctly
                     divided it out. LEAVE.
  PHANTOM-UP         raw_step in [0.80,1.25] (raw barely moved) but F>=1.8 -> the bake applied an up-factor
                     the tape never had (muhurat/data glitch or a rebound the inference misread). The
                     pre-event history is mis-scaled by ~F. FIX = noadjust that ex-date (keep the raw move).
  GLITCH-REVERTS     raw_step ~ F but persist ~ 1/F (snaps back next days) -> one-day artifact. FIX = noadjust.
  MANUAL             anything else (partial re-basing, illiquid, no raw open) -> hand-read.

Usage: arbitrate_upmoves2.py <upmoves.json> <sf_stock_data.bin> <bhav_cache> <out.json>
Writes NOTHING. Prints the table + a proposed noadjust set.
"""
import os, sys, json, gzip, datetime
from bisect import bisect_left
from statistics import median

UP, BIN, CACHE, OUT = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
HERE = os.path.dirname(os.path.abspath(__file__)); SCR = os.path.dirname(HERE)
ups = json.load(open(UP))
D = json.loads(gzip.decompress(open(BIN, 'rb').read())); data = D.get('data', D); meta = D.get('meta', {})
rmap = json.load(open(os.path.join(SCR, '_rename_map.json')))

_cache = {}
def rawrow(sym, ymd):
    key = ymd
    if key not in _cache:
        p = os.path.join(CACHE, '%d.json' % ymd)
        try: _cache[key] = json.load(open(p)) if os.path.exists(p) else []
        except Exception: _cache[key] = []
    names = {sym} | {o for o, n in rmap.items() if n == sym}
    for r in _cache[key]:
        if r[0] in names: return r
    return None

def series(sym, ymd, lo=-20, hi=12):
    d0 = datetime.date(ymd // 10000, ymd // 100 % 100, ymd % 100)
    out = []
    for k in range(lo, hi + 1):
        dd = d0 + datetime.timedelta(days=k); y = int(dd.strftime('%Y%m%d'))
        r = rawrow(sym, y)
        if r and r[1]:  # traded close present
            out.append((y, r[1], r[6]))   # ymd, close, open
    return out

out = []
for u in ups:
    sym, ymd, f = u['sym'], u['ymd'], u['applied']
    s = series(sym, ymd)
    ex = next((c for (y, c, o) in s if y == ymd), None)
    pre_list = [c for (y, c, o) in s if y < ymd]
    post_list = [c for (y, c, o) in s if y > ymd]
    pre = pre_list[-1] if pre_list else None
    post = median(post_list[1:6]) if len(post_list) >= 6 else (median(post_list) if post_list else None)
    raw_step = (ex / pre) if (ex and pre) else None
    persist = (post / ex) if (ex and post) else None
    near_f = (0.88 <= (raw_step / f) <= 1.12) if raw_step else False
    near_1 = (0.80 <= raw_step <= 1.25) if raw_step else False
    reverts = (persist is not None and persist <= 1.0 / f * 1.3) if raw_step else False
    m = meta.get(sym, {}) or {}
    if raw_step is None:
        verdict, note = 'MANUAL', 'no adjacent raw closes'
    elif near_f and persist is not None and 0.80 <= persist <= 1.25:
        verdict, note = 'REAL-BASIS-CHANGE', 'raw re-based x%.2f and held (persist %.2f)' % (raw_step, persist)
    elif near_1 and f >= 1.8:
        verdict, note = 'PHANTOM-UP', 'raw barely moved (x%.3f) but bake applied x%.2f' % (raw_step, f)
    elif near_f and reverts:
        verdict, note = 'GLITCH-REVERTS', 'raw jumped x%.2f then snapped back (persist %.2f)' % (raw_step, persist)
    else:
        verdict, note = 'MANUAL', 'raw_step x%.2f vs factor %.2f, persist %s' % (raw_step, f, ('%.2f' % persist) if persist else 'NA')
    out.append({'sym': sym, 'ymd': ymd, 'factor': round(f, 4), 'verdict': verdict,
                'raw_step': round(raw_step, 4) if raw_step else None,
                'persist': round(persist, 3) if persist else None,
                'pre': pre, 'exclose': ex, 'post': round(post, 3) if post else None,
                'name': m.get('name', ''), 'turnover': u.get('turnover'), 'note': note,
                'bars_before': (data[sym]['d'].index(ymd) if ymd in data[sym]['d'] else bisect_left(data[sym]['d'], ymd))})

from collections import Counter
byv = Counter(r['verdict'] for r in out)
json.dump(out, open(OUT, 'w'), indent=1)
print('=== v2 VERDICTS ===', dict(byv))
for v in ('PHANTOM-UP', 'GLITCH-REVERTS', 'MANUAL', 'REAL-BASIS-CHANGE'):
    rows = sorted([r for r in out if r['verdict'] == v], key=lambda r: -(r['turnover'] or 0))
    print('\n--- %s (%d) ---' % (v, len(rows)))
    for r in rows:
        print('  %-11s %d f=%.3f raw_step=%s persist=%s pre=%s ex=%s post=%s  %s'
              % (r['sym'], r['ymd'], r['factor'], r['raw_step'], r['persist'], r['pre'], r['exclose'], r['post'], r['name'][:20]))
print('\nPROPOSED noadjust (PHANTOM-UP + GLITCH-REVERTS):', sum(1 for r in out if r['verdict'] in ('PHANTOM-UP', 'GLITCH-REVERTS')))
