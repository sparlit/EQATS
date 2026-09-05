# -*- coding: utf-8 -*-
"""Find corporate-action mis-adjustments: compare NSE's OFFICIAL split/bonus ratio to what our
build's ca_factor (which infers the factor from the price drop) actually applied. A mismatch =
the pre-event prices are mis-scaled (e.g. Adani Power's 1:5 split read as 1:4 because the stock
popped ~20% on the ex-date). Saves the official factor map to corp_actions.json for the fix.

Run: python -X utf8 find_split_bugs.py
"""
import json, os, re, glob, datetime
import build_sf_data as B
import build_fundamentals as F

CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_bhav_cache")

def ca_factor(r):                       # mirror of build_sf_data.ca_factor
    CA = [1/2, 1/3, 2/3, 1/4, 3/4, 1/5, 2/5, 3/5, 1/6, 5/6, 1/8, 1/10, 1/20, 1/50, 2., 3., 4., 5., 10.]
    if 0.75 <= r <= 1.30: return 1.0
    for f in CA:
        if abs(r / f - 1) <= 0.08: return f
    return 1.0

def official_factor(subj):
    s = subj.lower()
    m = re.search(r'from\s*(?:rs\.?\s*)?([\d.]+).*?to\s*(?:rs\.?\s*)?([\d.]+)', s)   # split: face X -> Y
    if m and ('split' in s or 'sub-division' in s or 'sub division' in s):
        x, y = float(m.group(1)), float(m.group(2))
        if x: return y / x, "split %s:%s" % (int(x/y) if y and x/y==int(x/y) else x, y)
    m = re.search(r'bonus[^0-9]*(\d+)\s*:\s*(\d+)', s)                                # bonus B:A
    if m:
        b, a = int(m.group(1)), int(m.group(2))
        if a + b: return a / (a + b), "bonus %d:%d" % (b, a)
    return None, None

def closes_around(sym, ex):             # raw close on prior trading day and on/after ex-date
    exd = datetime.date(ex//10000, (ex//100)%100, ex%100)
    before = after = None
    for off in range(-8, 6):
        d = exd + datetime.timedelta(days=off)
        cf = os.path.join(CACHE, d.strftime("%Y%m%d") + ".json")
        if not os.path.exists(cf): continue
        try: rows = json.load(open(cf))
        except Exception: continue
        for r in rows:
            if r and r[0] == sym:
                ymd = int(d.strftime("%Y%m%d"))
                if ymd < ex: before = r[1]
                elif after is None and ymd >= ex: after = r[1]
                break
    return before, after

def fetch_ca():
    jar = F.nse_jar(); h = {"User-Agent": F.UA, "Accept": "application/json", "Referer": "https://www.nseindia.com/"}
    out = []
    for yr in range(2018, 2027):
        url = ("https://www.nseindia.com/api/corporates-corporateActions?index=equities"
               "&from_date=01-01-%d&to_date=31-12-%d" % (yr, yr))
        try:
            d = json.loads(F._get(url, headers=h, jar=jar, timeout=40))
            rows = d if isinstance(d, list) else d.get("data", [])
        except Exception as e:
            print("  %d fetch failed: %s" % (yr, str(e)[:40])); continue
        for r in rows:
            subj = r.get("subject") or r.get("purpose") or ""
            f, label = official_factor(subj)
            if f and 0.05 < f < 0.95:
                ex = F.iso(r.get("exDate"))
                if ex: out.append((r.get("symbol"), int(ex), f, label))
    return out

def main():
    events = fetch_ca()
    print("official split/bonus events fetched:", len(events))
    cmap = {}; bugs = []
    for sym, ex, fac, label in events:
        cmap.setdefault(sym, []).append([ex, round(fac, 6)])
        b, a = closes_around(sym, ex)
        if not b or not a: continue
        obs = a / b
        inferred = ca_factor(obs)
        # bug if our inferred factor differs from official by >2%
        if abs(inferred / fac - 1) > 0.02:
            bugs.append((sym, ex, label, round(fac, 3), round(inferred, 3), round(obs, 3)))
    json.dump(cmap, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "corp_actions.json"), "w"))
    print("saved corp_actions.json (%d symbols)" % len(cmap))
    print("\nMIS-ADJUSTED stocks (official factor != our inferred):", len(bugs))
    print("%-12s %-9s %-12s %7s %7s %7s" % ("SYMBOL", "exDate", "action", "official", "ours", "obs-ratio"))
    for sym, ex, label, fac, inf, obs in sorted(bugs, key=lambda x: abs(x[4]/x[3]-1), reverse=True):
        print("%-12s %-9d %-12s %7.3f %7.3f %7.3f" % (sym, ex, label, fac, inf, obs))

if __name__ == "__main__":
    main()
