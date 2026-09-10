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
import json

IDX = json.load(open("scripts/indices_history.json"))["Nifty 500"]
mine = json.load(open("scripts/_mine_all.json"))


def members(ds):
    dn = int(ds.replace("-", ""))
    b = None
    for s in IDX:
        ed = int(s["effectiveDate"].replace("-", ""))
        if ed <= dn and (b is None or ed > b[0]):
            b = (ed, s["symbols"])
    return set(b[1]) if b else set()


tT = tM = 0
rows = []
for ln in open("scripts/_tl_full.txt"):
    ln = ln.rstrip("\n")
    if "|" not in ln:
        continue
    d, s = ln.split("|", 1)
    raw = [x for x in s.split(",") if x]
    M = members(d)
    sf = [x for x in raw if x in M]
    ours = set(mine.get(d, []))
    match = [x for x in sf if x in ours]
    miss = [x for x in sf if x not in ours]
    tT += len(sf)
    tM += len(match)
    rows.append((d, len(raw), len(sf), len(ours), len(match), miss))
print("%-10s | rawTL | TL-SF | ours | match | misses" % "month")
for d, r, sf, ou, m, miss in rows:
    mm = ",".join(miss[:5]) + ((" +%d" % (len(miss) - 5)) if len(miss) > 5 else "")
    print("%-10s | %4d  | %4d  | %4d | %4d  | %s" % (d, r, sf, ou, m, mm or "-"))
print()
print("TOTAL Mar23-Jun26:  TL survivorship-free=%d   match=%d   rate=%.1f%%" % (tT, tM, 100 * tM / tT))
