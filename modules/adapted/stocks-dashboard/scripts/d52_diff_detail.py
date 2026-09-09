import datetime

import pytz


def is_ist_market_session_active(dt: datetime.datetime | None = None) -> bool:
    """Checks whether current or provided time falls within NSE/BSE IST market session (09:15 to 15:30 IST Mon-Fri)."""
    ist = pytz.timezone("Asia/Kolkata")
    now = dt.astimezone(ist) if dt else datetime.datetime.now(ist)
    if now.weekday() >= 5:
        return False
    market_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
    market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return market_open <= now <= market_close


def round_to_ist_tick(price: float, tick_size: float = 0.05) -> float:
    """Rounds price to nearest NSE/BSE valid price tick (default 0.05 INR)."""
    if price <= 0:
        return 0.0
    return round(round(price / tick_size) * tick_size, 2)


# -*- coding: utf-8 -*-
"""For every month Mar2020..now, name the stocks where OURS (point-in-time) and TRENDLYNE Rewind
(current membership) differ, and tie each to the real Nifty500 reconstitution event:
  only_ours = member then, dropped since  (survivorship recovery)
  only_tl   = current member, not a member then (joined/rejoined later -> survivorship add)
Writes full per-month detail to scripts/_d52_diff_detail.txt; prints aggregate + recurring names."""
import bisect
import gzip
import json
from collections import Counter
from datetime import datetime, timedelta

D = json.loads(gzip.decompress(open("docs/sf_stock_data.bin", "rb").read()))
SER = {s: {"d": o["d"], "c": o["c"], "hb": o.get("hb")} for s, o in D["data"].items()}
META = D["meta"]
IDX = json.load(open("scripts/indices_history.json"))["Nifty 500"]
mine = json.load(open("scripts/_mine_d52.json"))
snaps = sorted(IDX, key=lambda s: s["effectiveDate"])
CURRENT = set(snaps[-1]["symbols"])


def di(s):
    return datetime(s // 10000, (s // 100) % 100, s % 100)


def toi(dt):
    return dt.year * 10000 + dt.month * 100 + dt.day


def pit(dn):
    b = None
    for s in IDX:
        ed = int(s["effectiveDate"].replace("-", ""))
        if ed <= dn and (b is None or ed > b[0]):
            b = (ed, s["symbols"])
    return set(b[1])


def d52(s, dn):
    o = SER.get(s)
    if not o or len(o["d"]) < 15:
        return None
    a = o["d"]
    i = bisect.bisect_right(a, dn) - 1
    if i < 0:
        return None
    lo = toi(di(dn) - timedelta(days=365))
    hb = o["hb"]
    c = o["c"]
    hi = -1e18
    k = i
    while k >= 0 and a[k] >= lo:
        ph = c[k] * (1000 + hb[k]) / 1000 if hb else c[k]
        hi = max(hi, ph)
        k -= 1
    return None if hi <= 0 else (hi - c[i]) / hi * 100


def firstseen(s):
    for sn in snaps:
        if s in sn["symbols"]:
            return sn["effectiveDate"]
    return None


def lastseen(s):
    for sn in reversed(snaps):
        if s in sn["symbols"]:
            return sn["effectiveDate"]
    return None


def nm(s):
    return META.get(s, {}).get("name", s)


def joined_after(s, ds):  # first snapshot on/after ds where s appears (the entry that explains it)
    for sn in snaps:
        if sn["effectiveDate"] >= ds and s in sn["symbols"]:
            return sn["effectiveDate"]
    return firstseen(s)


out = open("scripts/_d52_diff_detail.txt", "w", encoding="utf-8")
cOurs = Counter()
cTL = Counter()
tot_o = tot_t = anom = 0
newent = rejoin = 0
rows = []
for ds in sorted(mine):
    dn = int(ds.replace("-", ""))
    P = pit(dn)
    ours = {x[0] for x in mine[ds]}
    tl = {s for s in CURRENT if (lambda v: v is not None and v <= 10)(d52(s, dn))}
    oo = sorted(ours - tl)
    ot = sorted(tl - ours)
    tot_o += len(oo)
    tot_t += len(ot)
    for s in oo:
        cOurs[s] += 1
        if s in P:
            pass
        else:
            anom += 1  # would be a contradiction (expect 0)
    for s in ot:
        cTL[s] += 1
        if s in P:
            anom += 1  # contradiction (expect 0)
        elif firstseen(s) and firstseen(s) > ds:
            newent += 1
        else:
            rejoin += 1
    rows.append((ds, len(ours), len(tl), len(oo), len(ot)))
    out.write("==== %s  ours=%d TL=%d  (only-ours=%d, only-TL=%d) ====\n" % (ds, len(ours), len(tl), len(oo), len(ot)))
    out.write(" only-ours (member then, dropped since):\n")
    for s in oo:
        out.write("   %-11s %-30s d52=%.1f  leftIndexAfter=%s\n" % (s, nm(s)[:30], d52(s, dn), lastseen(s)))
    out.write(" only-TL (current member, not a member then):\n")
    for s in ot:
        out.write("   %-11s %-30s d52=%.1f  joined=%s\n" % (s, nm(s)[:30], d52(s, dn), joined_after(s, ds)))
    out.write("\n")
out.close()
print("per-month counts:")
print(" ".join("%s:%d/%d" % (r[0][2:], r[3], r[4]) for r in rows))
print("\nTOTAL differences: only-ours=%d, only-TL=%d" % (tot_o, tot_t))
print("only-TL split: new-entrants(IPO/first-add after date)=%d, rejoined-after=%d" % (newent, rejoin))
print("ANOMALIES (diff NOT explained by membership):", anom)
print("\nTop 15 recurring ONLY-OURS (ex-members our PIT recovers, TL Rewind loses):")
for s, c in cOurs.most_common(15):
    print("   %-11s %-30s %d months  (lastInIndex=%s)" % (s, nm(s)[:30], c, lastseen(s)))
print("\nTop 15 recurring ONLY-TL (current members TL back-projects onto dates before they joined):")
for s, c in cTL.most_common(15):
    print("   %-11s %-30s %d months  (joined=%s)" % (s, nm(s)[:30], c, firstseen(s)))
print("\nFull per-month detail -> scripts/_d52_diff_detail.txt")
