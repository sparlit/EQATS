# -*- coding: utf-8 -*-
"""Compare the monthly backtest qualifying lists BEFORE vs AFTER the attributable-to-owners
switch. BEFORE = revert npCon to total PAT (from _reattr_changes.json); AFTER = current
docs/sf_fundamentals.json (owners applied). Same screen as screen.py.
"""
import json, gzip, datetime, os, copy
H = os.path.dirname(os.path.abspath(__file__)); R = os.path.dirname(H)
D = json.loads(gzip.decompress(open(os.path.join(R, "docs", "sf_stock_data.bin"), "rb").read()))
DATA, META = D["data"], D["meta"]
AFTER = json.load(open(os.path.join(R, "docs", "sf_fundamentals.json")))
HIST = json.load(open(os.path.join(H, "indices_history.json")))["Nifty 500"]
CH = json.load(open(os.path.join(H, "_reattr_changes.json")))

# build BEFORE: revert npCon (row[3]) to total PAT for each changed (sym,qe)
BEFORE = copy.deepcopy(AFTER)
tot = {(c[0], c[1]): c[2] for c in CH}
reverted = 0
for sym, arr in BEFORE.items():
    for row in arr:
        t = tot.get((sym, row[0]))
        if t is not None:
            row[3] = t; reverted += 1

def od(y): return datetime.date(y // 10000, (y // 100) % 100, y % 100).toordinal()
def le(o, t):
    lo, hi, a = 0, len(o) - 1, -1
    while lo <= hi:
        m = (lo + hi) // 2
        if o[m] <= t: a = m; lo = m + 1
        else: hi = m - 1
    return a
def members(dstr):
    snap = max((h for h in HIST if h["effectiveDate"] <= dstr), key=lambda h: h["effectiveDate"], default=None)
    return set(snap["symbols"]) if snap else set()
def prof(FUND, s, di):
    arr = FUND.get(s)
    if not arr: return None
    for npi, ai in ((3, 4), (1, 2)):
        cur = next((q for q in reversed(arr) if q[npi] is not None and q[ai] is not None and q[ai] <= di), None)
        if not cur: continue
        be = cur[0] - 10000; base = next((q for q in arr if q[0] == be and q[npi] is not None), None)
        if not base: continue
        b, c = base[npi], cur[npi]
        return (c - b) / abs(b) * 100 if b else None
    return None
def factors(s, asof):
    o = DATA.get(s)
    if not o or len(o.get("d", [])) < 20: return None
    ords = [od(x) for x in o["d"]]; c = o["c"]; Hh = o.get("h"); Ll = o.get("l")
    i = le(ords, asof); j = le(ords, asof - 30)
    if i < 15 or j < 0 or c[j] <= 0: return None
    p = c[i]; lo = asof - 365
    if ords[i] < lo: return None
    if Hh and Ll:
        hi = max(Hh[k] for k in range(i, -1, -1) if ords[k] >= lo); low = min(Ll[k] for k in range(i, -1, -1) if ords[k] >= lo)
    else:
        return None
    if hi <= 0 or low <= 0: return None
    return p, (hi - p) / hi * 100, (p - low) / low * 100

def qualify(FUND, endymd):
    asof = od(endymd); dstr = datetime.date.fromordinal(asof).isoformat(); mem = members(dstr)
    out = {}
    for s in mem:
        f = factors(s, asof)
        if not f: continue
        p, d52, d52low = f
        if not (d52 <= 10 and d52low >= 100): continue
        py = prof(FUND, s, endymd)
        if py is None or py <= 0: continue
        out[s] = round(py, 1)
    return out

MONTHS = [(20260612, "Jun-2026 (latest)"), (20260531, "May-2026"), (20260430, "Apr-2026"),
          (20260331, "Mar-2026"), (20260228, "Feb-2026"), (20260131, "Jan-2026"),
          (20251231, "Dec-2025"), (20251130, "Nov-2025"), (20251031, "Oct-2025"),
          (20250930, "Sep-2025"), (20250831, "Aug-2025"), (20250731, "Jul-2025"),
          (20250630, "Jun-2025")]

print("reverted %d con quarters to total PAT for BEFORE\n" % reverted)
print("%-18s %5s %5s  %-7s  %s" % ("MONTH", "bef", "aft", "membship", "set changes (membership added/removed)"))
print("-" * 90)
anychange = False
detail = []
for ymd, lbl in MONTHS:
    b = qualify(BEFORE, ymd); a = qualify(AFTER, ymd)
    added = sorted(set(a) - set(b)); removed = sorted(set(b) - set(a))
    note = ""
    if added: note += "+[" + ",".join(added) + "] "
    if removed: note += "-[" + ",".join(removed) + "]"
    if not note: note = "(no membership change)"
    else: anychange = True
    print("%-18s %5d %5d  %-7s  %s" % (lbl, len(b), len(a), "same" if len(a)==len(b) else "DIFF", note))
    detail.append((lbl, b, a, added, removed))

print("\n=== ANY MEMBERSHIP CHANGE: %s ===" % ("YES" if anychange else "NO"))
