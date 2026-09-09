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
"""Reusable screen for the user's strategy (Nifty500, consolidated, d52<=10 & d52low>=100 &
profitYoY>0). Keeps the heavy logic in a file so lookups are one-line commands.

  python screen.py                 # full qualifying list as of latest data
  python screen.py 20260529        # full list as of a date (YYYYMMDD)
  python screen.py ADANIPOWER      # one stock's filter breakdown (latest)
  python screen.py ADANIPOWER 20260529
"""
import datetime
import gzip
import json
import os
import sys

H = os.path.dirname(os.path.abspath(__file__))
R = os.path.dirname(H)
D = json.loads(gzip.decompress(open(os.path.join(R, "docs", "sf_stock_data.bin"), "rb").read()))
DATA, META = D["data"], D["meta"]
FUND = json.load(open(os.path.join(R, "docs", "sf_fundamentals.json")))
HIST = json.load(open(os.path.join(H, "indices_history.json")))["Nifty 500"]  # authoritative (build_membership_v2)


def od(y):
    return datetime.date(y // 10000, (y // 100) % 100, y % 100).toordinal()


def le(o, t):
    lo, hi, a = 0, len(o) - 1, -1
    while lo <= hi:
        m = (lo + hi) // 2
        if o[m] <= t:
            a = m
            lo = m + 1
        else:
            hi = m - 1
    return a


def members(dstr):
    snap = max((h for h in HIST if h["effectiveDate"] <= dstr), key=lambda h: h["effectiveDate"], default=None)
    return set(snap["symbols"]) if snap else set()


def prof(s, di):
    arr = FUND.get(s)
    if not arr:
        return None, None
    for npi, ai in ((3, 4), (1, 2)):
        cur = next((q for q in reversed(arr) if q[npi] is not None and q[ai] is not None and q[ai] <= di), None)
        if not cur:
            continue
        be = cur[0] - 10000
        base = next((q for q in arr if q[0] == be and q[npi] is not None), None)
        if not base:
            continue  # no base on this basis -> try the next (con -> std), like the engine
        b, c = base[npi], cur[npi]
        return ((c - b) / abs(b) * 100 if b else None), (cur[0], c, be, b)
    return None, None


def factors(s, asof):
    o = DATA.get(s)
    if not o or len(o.get("d", [])) < 20:
        return None
    ords = [od(x) for x in o["d"]]
    c = o["c"]
    Hh = o.get("h")
    Ll = o.get("l")
    i = le(ords, asof)
    j = le(ords, asof - 30)
    if i < 15 or j < 0 or c[j] <= 0:
        return None
    p = c[i]
    lo = asof - 365
    if ords[i] < lo:
        return None  # latest data older than the 52w window (delisted/stale) -> skip
    if Hh and Ll:
        hi = max(Hh[k] for k in range(i, -1, -1) if ords[k] >= lo)
        low = min(Ll[k] for k in range(i, -1, -1) if ords[k] >= lo)
    else:
        hb = o.get("hb")
        lb = o.get("lb")
        hi = -1e18
        low = 1e18
        for k in range(i, -1, -1):
            if ords[k] < lo:
                break
            ph = c[k] * (1000 + hb[k]) / 1000 if hb else c[k]
            pl = c[k] * (1000 - lb[k]) / 1000 if lb else c[k]
            hi = max(hi, ph)
            low = min(low, pl)
    if hi <= 0 or low <= 0:
        return None
    return p, hi, low, (hi - p) / hi * 100, (p - low) / low * 100


def main():
    args = list(sys.argv[1:])
    date = next((a for a in args if a.isdigit() and len(a) == 8), None)
    sym = next((a for a in args if not (a.isdigit() and len(a) == 8)), None)
    endymd = int(date) if date else int(D["end"].replace("-", ""))
    asof = od(endymd)
    dstr = datetime.date.fromordinal(asof).isoformat()
    mem = members(dstr)
    if sym:
        sym = sym.upper()
        print("{}  ({})  as of {}".format(sym, META.get(sym, {}).get("name", "?"), dstr))
        print("  in Nifty500:", sym in mem)
        f = factors(sym, asof)
        if f:
            p, hi, low, d52, d52low = f
            print(f"  price={p:.2f}  52wHigh={hi:.2f}  52wLow={low:.2f}")
            print("  d52<=10:    {:.2f}  -> {}".format(d52, "PASS" if d52 <= 10 else "FAIL"))
            print("  d52low>=100: {:.2f} -> {}".format(d52low, "PASS" if d52low >= 100 else "FAIL"))
        py, det = prof(sym, endymd)
        print("  profitYoY>0:", (round(py, 1) if isinstance(py, (int, float)) else py), "| cur/base:", det)
        return
    q = []
    for s in mem:
        f = factors(s, asof)
        if not f:
            continue
        p, hi, low, d52, d52low = f
        if not (d52 <= 10 and d52low >= 100):
            continue
        py, _ = prof(s, endymd)
        if py is None or py <= 0:
            continue
        q.append((s, META.get(s, {}).get("name", s)[:24], py, d52, d52low))
    q.sort(key=lambda z: -z[2])
    print("QUALIFYING as of %s: %d" % (dstr, len(q)))
    print("%-3s %-11s %-24s %9s %6s %6s" % ("#", "SYMBOL", "NAME", "YoY%", "Hi%", "Lo%"))
    for i, (s, nm, p, a, b) in enumerate(q, 1):
        print("%-3d %-11s %-24s %+9.1f %6.1f %6.1f" % (i, s, nm, p, a, b))


if __name__ == "__main__":
    main()
