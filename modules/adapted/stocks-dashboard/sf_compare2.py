# -*- coding: utf-8 -*-
"""Re-compare to StockView with the fixes applied:
  (1) 1-month lookback for Change%   (2) symbol-rename stitching (NSE symbolchange.csv)
  (3) delisting-to-zero loss capture (held stock that stops trading -> total loss)
"""
import json, gzip, bisect, datetime, csv, os
HERE = os.path.dirname(os.path.abspath(__file__))

# rename map old->new (resolve chains)
rename = {}
for r in csv.reader(open(os.path.join(os.path.dirname(HERE), "..", "symchg.csv"), encoding="utf-8", errors="replace")):
    if len(r) >= 3 and r[1].strip() and r[2].strip() and r[1].strip().upper() != "SYMBOL":
        rename[r[1].strip()] = r[2].strip()
def canon(s):
    seen = set()
    while s in rename and s not in seen: seen.add(s); s = rename[s]
    return s

DB = json.load(gzip.open(os.path.join(HERE, "sf_poc.json.gz"))); DATA = DB["data"]; END = DB["end"]
end_date = datetime.datetime.strptime(END, "%Y-%m-%d").date()
N500 = sorted(json.load(open(os.path.join(HERE, "n500_hist.json"))), key=lambda x: x["effectiveDate"])

# merge renamed series into a single canonical series (rescale to connect at the rename)
groups = {}
for sym in DATA: groups.setdefault(canon(sym), []).append(sym)
MD = {}; n_merged = 0
for c, syms in groups.items():
    if len(syms) == 1: MD[c] = DATA[syms[0]]; continue
    n_merged += 1
    syms.sort(key=lambda s: DATA[s]["d"][0]); d = []; cc = []; tt = []; lastv = None
    for s in syms:
        sd, sc, st = DATA[s]["d"], DATA[s]["c"], DATA[s]["t"]
        scale = (lastv / sc[0]) if (lastv is not None and sc and sc[0]) else 1.0
        for i in range(len(sd)):
            if d and sd[i] <= d[-1]: continue
            d.append(sd[i]); cc.append(round(sc[i] * scale, 2)); tt.append(st[i])
        if cc: lastv = cc[-1]
    MD[c] = {"d": d, "c": cc, "t": tt}

def ymd(s): return int(s.replace("-", ""))
def ymd_to_date(y): return datetime.date(y // 10000, y // 100 % 100, y % 100)
def lastDate(sym): s = MD.get(sym); return s["d"][-1] if s and s["d"] else 0
def price(sym, y):
    s = MD.get(sym)
    if not s: return None
    i = bisect.bisect_right(s["d"], y) - 1
    return s["c"][i] if i >= 0 else None
def priceMark(sym, y):                 # delisting-to-zero for HELD valuation
    ld = lastDate(sym)
    if y > ld:
        if (end_date - ymd_to_date(ld)).days > 90: return 0.0     # stopped >1 quarter before data end -> delisted
        return price(sym, ld)
    return price(sym, y)
def members(dstr):
    best = None
    for s in N500:
        if s["effectiveDate"] <= dstr: best = s
    return set(canon(x) for x in best["symbols"]) if best else set()
def month_ends(start, end):
    out = []; y, m = int(start[:4]), int(start[5:7]); ey, em = int(end[:4]), int(end[5:7])
    while y < ey or (y == ey and m <= em):
        out.append(datetime.date(y + (m == 12), (m % 12) + 1, 1) - datetime.timedelta(days=1)); m += 1
        if m > 12: m = 1; y += 1
    return out

def bt(start, end, lb=30, freq=3, topn=10):
    months = month_ends(start, end); cap = 1e5; units = {}; val = cap; eq = []
    for i, md in enumerate(months):
        y = ymd(md.isoformat())
        if units:
            v = sum(u * (priceMark(s, y) or 0) for s, u in units.items())
            val = max(0.0, v)
        eq.append(val)
        if i % freq: continue
        yl = ymd((md - datetime.timedelta(days=lb)).isoformat()); c = []
        for sym in members(md.isoformat()):
            p = price(sym, y); p0 = price(sym, yl)
            if p and p0 and p0 > 0: c.append((p / p0 - 1, sym, p))
        c.sort(reverse=True); picks = c[:topn]; units = {}; per = val / (len(picks) or 1)
        for _, sym, p in picks: units[sym] = per / p
    final = eq[-1]; yrs = (datetime.datetime.strptime(end, "%Y-%m-%d") - datetime.datetime.strptime(start, "%Y-%m-%d")).days / 365.25
    cagr = (final / cap) ** (1 / yrs) - 1 if final > 0 else -1
    peak = -1; mdd = 0
    for v in eq:
        peak = max(peak, v)
        if peak > 0: mdd = max(mdd, (peak - v) / peak)
    return final, cagr * 100, mdd * 100

print("Renamed tickers stitched:", n_merged, "| dataset end:", END, "\n")
ref = {("2021-01-01", "2024-01-01"): (312253, 46.2, 9.2), ("2019-01-01", "2024-01-01"): (216434, 16.7, 54.1)}
print("%-30s %14s %8s %8s" % ("", "Final Rs1L", "CAGR", "MaxDD"))
for (s, e), sv in ref.items():
    f, c, dd = bt(s, e, lb=30)
    print("-" * 64)
    print("%-30s %14s %7.1f%% %7.0f%%" % (s[:4]+"-"+e[:4]+" OUR (1mo+stitch+delist→0)", format(f, ",.0f"), c, dd))
    print("%-30s %14s %7.1f%% %7.0f%%" % ("   StockView", format(sv[0], ",.0f"), sv[1], sv[2]))
