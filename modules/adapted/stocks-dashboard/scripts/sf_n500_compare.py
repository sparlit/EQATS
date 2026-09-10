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
"""
Re-run the two StockView-matched backtests, but on our OWN survivorship-free data
(NSE bhavcopy, incl. delisted stocks) with the TRUE point-in-time Nifty 500 universe
(from indicesHistory, which includes dead constituents).

Config matches StockView runs 639 / 640:
  Nifty 500 universe, quarterly rebalance, top-10 by ~quarterly momentum, equal-weight.

Compares: our survivorship-FREE result vs StockView vs our earlier survivorship-BIASED dashboard.
Run:  python -X utf8 sf_n500_compare.py
"""
import bisect
import datetime
import gzip
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
DB = json.load(gzip.open(os.path.join(HERE, "sf_poc.json.gz")))
DATA, META = DB["data"], DB["meta"]
N500 = sorted(json.load(open(os.path.join(HERE, "n500_hist.json"))), key=lambda s: s["effectiveDate"])

TOPN = 10
LOOKBACK_D = 91
FREQ = 3  # quarterly


def ymd(d):
    return int(d.strftime("%Y%m%d"))


def price(sym, y):
    s = DATA.get(sym)
    if not s:
        return None
    i = bisect.bisect_right(s["d"], y) - 1
    return s["c"][i] if i >= 0 else None


def members_asof(dstr):
    best = None
    for s in N500:
        if s["effectiveDate"] <= dstr:
            best = s
    return set(best["symbols"]) if best else set()


def month_ends(start, end):
    out = []
    y, m = int(start[:4]), int(start[5:7])
    ey, em = int(end[:4]), int(end[5:7])
    while y < ey or (y == ey and m <= em):
        out.append(datetime.date(y + (m == 12), (m % 12) + 1, 1) - datetime.timedelta(days=1))
        m += 1
        if m > 12:
            m = 1
            y += 1
    return out


def run(start, end):
    months = month_ends(start, end)
    cap = 100000.0
    units = {}
    val = cap
    eq = []
    nreb = 0
    for i, md in enumerate(months):
        y = ymd(md)
        if units:
            v = sum(u * (price(s, y) or 0) for s, u in units.items())
            if v > 0:
                val = v
        eq.append(val)
        if i % FREQ != 0:
            continue
        nreb += 1
        mem = members_asof(md.isoformat())
        yl = ymd(md - datetime.timedelta(days=LOOKBACK_D))
        cands = []
        for sym in mem:
            p = price(sym, y)
            p0 = price(sym, yl)
            if p is None or p0 is None or p0 <= 0:
                continue
            cands.append((p / p0 - 1.0, sym, p))
        cands.sort(reverse=True)
        picks = cands[:TOPN]
        units = {}
        per = val / (len(picks) or 1)
        for _, sym, p in picks:
            units[sym] = per / p
    final = eq[-1]
    yrs = (datetime.datetime.strptime(end, "%Y-%m-%d") - datetime.datetime.strptime(start, "%Y-%m-%d")).days / 365.25
    cagr = (final / cap) ** (1 / yrs) - 1
    peak = -1
    mdd = 0
    for v in eq:
        peak = max(peak, v)
        if peak > 0:
            mdd = max(mdd, (peak - v) / peak)
    return final, cagr * 100, mdd * 100, nreb


print("Nifty 500 (point-in-time, incl. delisted), quarterly, top-10 momentum, equal-weight\n")
ref = {
    ("2021-01-01", "2024-01-01"): {"sv": (312253, 46.2, 9.2), "biased": (301617, 44.5, None)},
    ("2019-01-01", "2024-01-01"): {"sv": (216434, 16.7, 54.1), "biased": (465930, 36.0, None)},
}
hdr = "%-12s %-26s %14s %9s %9s"
print(hdr % ("Period", "Engine", "Final (Rs1L)", "CAGR", "MaxDD"))
print("-" * 76)
for (s, e), r in ref.items():
    f, c, dd, nb = run(s, e)
    label = s[:4] + "-" + e[:4]
    print(hdr % (label, "OUR survivorship-FREE", format(f, ",.0f"), f"{c:.1f}%", f"{dd:.0f}%"))
    print(
        hdr
        % (
            "",
            "StockView (their data)",
            format(r["sv"][0], ",.0f"),
            "{:.1f}%".format(r["sv"][1]),
            "{:.0f}%".format(r["sv"][2]),
        )
    )
    bd = r["biased"]
    print(hdr % ("", "OUR survivorship-BIASED", format(bd[0], ",.0f"), f"{bd[1]:.1f}%", "—"))
    print("-" * 76)
