# -*- coding: utf-8 -*-
"""
Validate the survivorship-free POC: run the SAME momentum backtest two ways over
the COVID period and compare —
  (A) SURVIVORSHIP-FREE : all stocks that traded then (incl. delisted)
  (B) SURVIVORS-ONLY    : only stocks still listed today (what our biased engine sees)

Same logic as the dashboard's "reset equal-weight": each month-end, rank the
liquid universe by trailing 6-month return, hold top-N equal-weight, rebalance.
Universe = liquidity floor on turnover (point-in-time, survivorship-free).

Run:  python -X utf8 sf_poc_compare.py
"""
import os, gzip, json, bisect, datetime, math

HERE = os.path.dirname(os.path.abspath(__file__))
DB = json.load(gzip.open(os.path.join(HERE, "sf_poc.json.gz")))
DATA, META = DB["data"], DB["meta"]

START = "2019-07-01"; END = "2020-12-31"      # 6-mo lookback available from Jan-2019
TOPN = 15; TURN_FLOOR = 500.0                  # >= Rs 500 lacs (~Rs 5 Cr) daily turnover
LOOKBACK_D = 182

def ymd(dstr): return int(dstr.replace("-", ""))
def price(sym, y):
    s = DATA.get(sym);
    if not s: return None
    i = bisect.bisect_right(s["d"], y) - 1
    return s["c"][i] if i >= 0 else None
def turn(sym, y):
    s = DATA.get(sym);
    if not s: return 0.0
    i = bisect.bisect_right(s["d"], y) - 1
    return s["t"][i] if i >= 0 else 0.0

def month_ends(start, end):
    out = []; y, m = int(start[:4]), int(start[5:7]); ey, em = int(end[:4]), int(end[5:7])
    while y < ey or (y == ey and m <= em):
        last = (datetime.date(y + (m == 12), (m % 12) + 1, 1) - datetime.timedelta(days=1))
        out.append(last); m += 1
        if m > 12: m = 1; y += 1
    out[-1] = datetime.datetime.strptime(end, "%Y-%m-%d").date()
    return out

def shift(d, days): return d - datetime.timedelta(days=days)

def backtest(survivors_only):
    months = month_ends(START, END); cap = 100000.0
    units = {}; val = cap; eq = []
    for i, md in enumerate(months):
        y = ymd(md.isoformat())
        if units:
            v = sum(u * (price(s, y) or 0) for s, u in units.items())
            if v > 0: val = v
        eq.append(val)
        # monthly rebalance
        yl = ymd(shift(md, LOOKBACK_D).isoformat())
        cands = []
        for sym, s in DATA.items():
            if survivors_only and not META[sym]["alive"]:
                continue
            p = price(sym, y); p0 = price(sym, yl)
            if p is None or p0 is None or p0 <= 0: continue
            if turn(sym, y) < TURN_FLOOR: continue
            cands.append((p / p0 - 1.0, sym, p))
        cands.sort(reverse=True)
        picks = cands[:TOPN]
        units = {}; per = val / (len(picks) or 1)
        for _, sym, p in picks: units[sym] = per / p
    final = eq[-1]
    yrs = (datetime.datetime.strptime(END, "%Y-%m-%d") - datetime.datetime.strptime(START, "%Y-%m-%d")).days / 365.25
    cagr = (final / cap) ** (1 / yrs) - 1
    peak = -1; mdd = 0
    for v in eq:
        peak = max(peak, v)
        if peak > 0: mdd = max(mdd, (peak - v) / peak)
    return final, cagr * 100, mdd * 100, eq

print("Universe each month: liquidity >= Rs %.0f lacs turnover, top %d by 6-mo momentum, monthly rebal" % (TURN_FLOOR, TOPN))
print("Period %s -> %s   (%d delisted stocks available in the survivorship-free set)" %
      (START, END, sum(1 for m in META.values() if not m["alive"])))
print()
fA, cA, dA, eqA = backtest(False)
fB, cB, dB, eqB = backtest(True)
print("%-28s %14s %9s %9s" % ("", "Final (Rs1L)", "CAGR", "Max DD"))
print("%-28s %14s %8.1f%% %8.1f%%" % ("(A) SURVIVORSHIP-FREE", format(fA, ',.0f'), cA, dA))
print("%-28s %14s %8.1f%% %8.1f%%" % ("(B) survivors-only (biased)", format(fB, ',.0f'), cB, dB))
print()
print("Bias inflation in CAGR (B - A): %+.1f pp   |   DD understated by: %+.1f pp" % (cB - cA, dA - dB))
