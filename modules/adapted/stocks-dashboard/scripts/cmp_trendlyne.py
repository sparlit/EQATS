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
"""Replicate the backtest-engine screenAsOf() in Python and compute the user's tool's
top-5 (by Net Profit Qtr YoY %, con-preferred) at each Trendlyne rebalance date.
Screen = Nifty500 member + d52<10 + d52low>100 + profitYoY>0, sort profitYoY desc."""
import bisect
import gzip
import json
from datetime import datetime, timedelta

D = json.loads(gzip.decompress(open("docs/sf_stock_data.bin", "rb").read()))
data = D["data"]
META = D.get("meta", {})
FUND = json.load(open("docs/sf_fundamentals.json"))
IDX = json.load(open("scripts/indices_history.json"))["Nifty 500"]

# precompute per-symbol arrays
SER = {}
for s, o in data.items():
    d = o["d"]
    SER[s] = {"d": d, "c": o["c"], "h": o.get("h"), "l": o.get("l"), "t": o.get("t")}


def di(s):
    return datetime(s // 10000, (s // 100) % 100, s % 100)


def to_int(dt):
    return dt.year * 10000 + dt.month * 100 + dt.day


def members_asof(dstr):
    di_int = int(dstr.replace("-", ""))
    best = None
    for snap in IDX:
        ed = int(snap["effectiveDate"].replace("-", ""))
        if ed <= di_int and (best is None or ed > best[0]):
            best = (ed, snap["symbols"])
    return set(best[1]) if best else set()


def price_at(s, dint):
    a = SER[s]["d"]
    i = bisect.bisect_right(a, dint) - 1
    return (SER[s]["c"][i], i) if i >= 0 else (None, -1)


def hl52(s, dint):
    a = SER[s]["d"]
    i = bisect.bisect_right(a, dint) - 1
    if i < 0:
        return None
    lo_int = to_int(di(dint) - timedelta(days=365))
    h = SER[s]["h"]
    l = SER[s]["l"]
    c = SER[s]["c"]
    hi = -1e18
    low = 1e18
    k = i
    while k >= 0 and a[k] >= lo_int:
        ph = h[k] if h else c[k]
        pl = l[k] if l else c[k]
        hi = max(hi, ph)
        low = min(low, pl)
        k -= 1
    return hi, low


def profit_yoy(sym, dint):
    arr = FUND.get(sym)
    if not arr:
        return None
    for npi, ani in ((3, 4), (1, 2)):
        cur = None
        for q in reversed(arr):
            if len(q) > ani and q[npi] is not None and q[ani] is not None and q[ani] <= dint:
                cur = q
                break
        if not cur:
            continue
        baseqe = cur[0] - 10000
        base = None
        for q in arr:
            if q[0] == baseqe and len(q) > npi and q[npi] is not None:
                base = q
                break
        if not base:
            continue
        b = base[npi]
        c = cur[npi]
        if b == 0:
            continue
        return (c - b) / abs(b) * 100
    return None


def screen(dstr, topn=8):
    dint = int(dstr.replace("-", ""))
    mem = members_asof(dstr)
    rows = []
    for s in SER:
        if s not in mem:
            continue
        if not SER[s]["d"] or len(SER[s]["d"]) < 15:
            continue
        p, _i = price_at(s, dint)
        if p is None:
            continue
        hl = hl52(s, dint)
        if not hl:
            continue
        hi, low = hl
        if hi <= 0 or low <= 0:
            continue
        d52 = (hi - p) / hi * 100
        d52low = (p - low) / low * 100
        if not (d52 < 10 and d52low > 100):
            continue
        yoy = profit_yoy(s, dint)
        if yoy is None or yoy <= 0:
            continue
        rows.append((s, round(yoy, 1), round(p, 1), round(d52, 1), round(d52low)))
    rows.sort(key=lambda r: -r[1])
    return rows[:topn]


DATES = {  # Trendlyne label -> ISO month-end
    "Dec 29, 2023": "2023-12-29",
    "Jan 31, 2024": "2024-01-31",
    "Feb 29, 2024": "2024-02-29",
    "Mar 28, 2024": "2024-03-28",
    "Apr 30, 2024": "2024-04-30",
    "May 31, 2024": "2024-05-31",
    "Jun 28, 2024": "2024-06-28",
    "Jul 31, 2024": "2024-07-31",
    "Aug 30, 2024": "2024-08-30",
    "Sep 30, 2024": "2024-09-30",
    "Oct 31, 2024": "2024-10-31",
    "Nov 29, 2024": "2024-11-29",
    "Dec 31, 2024": "2024-12-31",
    "Jan 31, 2025": "2025-01-31",
    "Mar 28, 2025": "2025-03-28",
    "Apr 30, 2025": "2025-04-30",
    "May 30, 2025": "2025-05-30",
    "Jun 30, 2025": "2025-06-30",
    "Jul 31, 2025": "2025-07-31",
    "Aug 29, 2025": "2025-08-29",
    "Sep 30, 2025": "2025-09-30",
    "Oct 31, 2025": "2025-10-31",
    "Nov 28, 2025": "2025-11-28",
    "Dec 31, 2025": "2025-12-31",
    "Jan 30, 2026": "2026-01-30",
    "Feb 27, 2026": "2026-02-27",
    "Mar 30, 2026": "2026-03-30",
    "Apr 30, 2026": "2026-04-30",
    "May 29, 2026": "2026-05-29",
    "Jun 12, 2026": "2026-06-12",
}

out = {}
for label, iso in DATES.items():
    res = screen(iso)
    out[label] = res
    top5 = [r[0] for r in res[:5]]
    print("{} | {}".format(label, " | ".join(f"{r[0]}({r[1]}%)" for r in res[:5])))
json.dump(out, open("scripts/_cmp_user.json", "w"))


# ---- second pass: UNRESTRICTED universe (all stocks), to test the Nifty500 hypothesis ----
def screen_all(dstr, topn=8, floor=0):
    dint = int(dstr.replace("-", ""))
    rows = []
    for s in SER:
        if not SER[s]["d"] or len(SER[s]["d"]) < 15:
            continue
        p, _i = price_at(s, dint)
        if p is None:
            continue
        hl = hl52(s, dint)
        if not hl:
            continue
        hi, low = hl
        if hi <= 0 or low <= 0:
            continue
        d52 = (hi - p) / hi * 100
        d52low = (p - low) / low * 100
        if not (d52 < 10 and d52low > 100):
            continue
        yoy = profit_yoy(s, dint)
        if yoy is None or yoy <= 0:
            continue
        rows.append((s, round(yoy, 1)))
    rows.sort(key=lambda r: -r[1])
    return rows[:topn]


# Trendlyne holdings mapped to NSE symbols (scraped from entry-exit 547306)
TL = {
    "Dec 29, 2023": ["GVT&D", "JUBLPHARMA", "WELCORP", "CHENNPETRO", "GRAPHITE"],
    "Jan 31, 2024": ["ADANIPOWER", "GVT&D", "BSOFT", "JUBLPHARMA", "WELCORP"],
    "Feb 29, 2024": ["ADANIPOWER", "FORCEMOT", "GVT&D", "BSOFT", "SWANCORP"],
    "Mar 28, 2024": ["ADANIPOWER", "JUBLPHARMA", "FORCEMOT", "ABREL", "POWERINDIA"],
    "Apr 30, 2024": ["TRENT", "GVT&D", "WELCORP", "ADANIPOWER", "MCX"],
    "May 31, 2024": ["POLICYBZR", "TRENT", "COCHINSHIP", "GVT&D", "TRIL"],
    "Jun 28, 2024": ["MCX", "POLICYBZR", "TRENT", "COCHINSHIP", "TEJASNET"],
    "Jul 31, 2024": ["MCX", "JUBLPHARMA", "POLICYBZR", "TRENT", "SIGNATURE"],
    "Aug 30, 2024": ["MCX", "GLENMARK", "JUBLPHARMA", "AUTHUM", "POLICYBZR"],
    "Sep 30, 2024": ["MCX", "GLENMARK", "JUBLPHARMA", "AUTHUM", "ETERNAL"],
    "Oct 31, 2024": ["TRIL", "MCX", "GLENMARK", "DEEPAKFERT", "PPLPHARMA"],
    "Nov 29, 2024": ["TRIL", "ETERNAL", "PAYTM", "MCX", "NATIONALUM"],
    "Dec 31, 2024": ["TRIL", "POLICYBZR", "ETERNAL", "PAYTM", "AMBER"],
    "Jan 31, 2025": ["SARDAEN", "CARTRADE", "ACUTAAS", "BLUEJET"],
    "Mar 28, 2025": ["MAZDOCK", "SARDAEN", "ACUTAAS", "BLUEJET", "GALLANTT"],
    "Apr 30, 2025": ["BSE", "PARADEEP", "CARTRADE", "MAZDOCK", "GODFRYPHLP"],
    "May 30, 2025": ["FORCEMOT", "BSE", "WELCORP", "BLUEJET", "PARADEEP"],
    "Jun 30, 2025": ["FORCEMOT", "CARTRADE", "BSE", "REDINGTON", "RPOWER"],
    "Jul 31, 2025": ["ACUTAAS", "PARADEEP", "LAURUSLABS", "SYRMA", "POWERINDIA"],
    "Aug 29, 2025": ["GVT&D", "ACUTAAS", "PARADEEP", "LAURUSLABS", "SYRMA"],
    "Sep 30, 2025": ["GVT&D", "TATAINVEST", "NETWEB"],
    "Oct 31, 2025": ["LAURUSLABS", "GVT&D", "CHENNPETRO", "SYRMA", "ABDL"],
    "Nov 28, 2025": ["ANUPAMRAS", "LAURUSLABS", "IIFL", "POWERINDIA", "CARTRADE"],
    "Dec 31, 2025": ["ANUPAMRAS", "FORCEMOT", "LAURUSLABS", "IIFL", "GMDCLTD"],
    "Jan 30, 2026": ["MCX", "GVT&D", "ANUPAMRAS", "HINDCOPPER", "JKTYRE"],
    "Feb 27, 2026": ["FORCEMOT", "MCX", "LAURUSLABS", "RBLBANK", "CRAFTSMAN"],
    "Mar 30, 2026": ["ACUTAAS", "GVT&D", "POWERINDIA", "ATHERENERG", "BELRISE"],
    "Apr 30, 2026": ["CPPLUS", "MCX", "ACUTAAS", "SYRMA", "NETWEB"],
    "May 29, 2026": ["CPPLUS", "BHEL", "HFCL", "IDEA", "CEMPRO"],
    "Jun 12, 2026": ["GVT&D", "ACUTAAS", "EMMVEE", "CPPLUS", "IDEA"],
}
ALIAS = {"CPPLUS": "CPPLUS"}
n500_overlap = 0
all_overlap = 0
tot = 0
print("\n=== OVERLAP: Trendlyne(all-mkt) vs YOUR tool ===")
print("%-13s | n500∩ | all∩ | your-Nifty500-top5" % "date")
for label, iso in DATES.items():
    tl = set(TL.get(label, []))
    u5 = {r[0] for r in out[label][:5]}
    a5 = {r[0] for r in screen_all(iso)[:5]}
    n_i = len(tl & u5)
    a_i = len(tl & a5)
    n500_overlap += n_i
    all_overlap += a_i
    tot += len(tl)
    print("%-13s |  %d/%d  | %d/%d | %s" % (label, n_i, len(tl), a_i, len(tl), ",".join(sorted(u5)) or "(none)"))
print(
    "\nTOTAL overlap with Trendlyne: Nifty500-restricted=%d/%d (%.0f%%) | unrestricted=%d/%d (%.0f%%)"
    % (n500_overlap, tot, 100 * n500_overlap / tot, all_overlap, tot, 100 * all_overlap / tot)
)


# ---- final: markdown table + classify each Trendlyne name your tool missed ----
def in500(sym, iso):
    return sym in members_asof(iso)


print("\n\n### TABLE")
print("| Date | Trendlyne top-5 | Your tool (Nifty500) top-5 | Match |")
print("|---|---|---|---|")
for label, iso in DATES.items():
    tl = TL.get(label, [])
    u5 = [r[0] for r in out[label][:5]]
    us = set(u5)
    tl_fmt = ", ".join((f"**{t}**" if t in us else t) for t in tl)
    u_fmt = ", ".join((f"**{u}**" if u in set(tl) else u) for u in u5) or "—"
    print("| %s | %s | %s | %d/%d |" % (label.replace(", ", " "), tl_fmt, u_fmt, len(set(tl) & us), len(tl)))

print("\n### Trendlyne names your tool MISSED — why (non-Nifty500 member at that date?)")
miss_non500 = []
miss_other = []
for label, iso in DATES.items():
    tl = TL.get(label, [])
    u5 = {r[0] for r in out[label][:5]}
    for t in tl:
        if t not in u5:
            if not in500(t, iso):
                miss_non500.append((label, t))
            else:
                miss_other.append((label, t))
from collections import Counter

print("Missed & NOT in Nifty500 (universe diff): %d" % len(miss_non500))
print("  names:", ", ".join(sorted({t for _, t in miss_non500})))
print("Missed but WAS in Nifty500 (ranking/data diff): %d" % len(miss_other))
print("  cases:", ", ".join("{}@{}".format(t, l.split(",")[0]) for l, t in miss_other))

# ---- FULL qualifying lists (no top-5 cap) ----
print("\n\n### FULL QUALIFYING (your Nifty500 screen, sorted by profit YoY%) — Trendlyne-held in [brackets]")
print("| Date | # | All qualifying stocks (profit-growth order; [x]=Trendlyne held it) |")
print("|---|---|---|")
for label, iso in DATES.items():
    allq = screen(iso, topn=999)
    tl = set(TL.get(label, []))
    names = ", ".join((f"[{r[0]}]" if r[0] in tl else r[0]) for r in allq)
    print("| %s | %d | %s |" % (label.replace(", ", " "), len(allq), names or "—"))

# ---- FINAL side-by-side: Trendlyne held vs OUR full qualifying + match count ----
print("\n\n### SIDEBYSIDE")
print("| Date | Match | Trendlyne (held) | Ours — all qualifying (Nifty500, profit-growth order) |")
print("|---|---|---|---|")
for label, iso in DATES.items():
    tl = TL.get(label, [])
    allq = [r[0] for r in screen(iso, topn=999)]
    qs = set(allq)
    ts = set(tl)
    m = len(ts & qs)
    tl_fmt = ", ".join((f"**{t}**" if t in qs else t + "⁻") for t in tl)
    our = ", ".join((f"**{s}**" if s in ts else s) for s in allq) or "—"
    print("| %s | %d/%d | %s | %s |" % (label.replace(", ", " "), m, len(tl), tl_fmt, our))

# dump FULL qualifying keyed by ISO for browser comparison
import json as _j

_out = {iso: [r[0] for r in screen(iso, topn=999)] for label, iso in DATES.items()}
_j.dump(_out, open("_mine_iso_full.json", "w"), separators=(",", ":"))
print("wrote _mine_iso_full.json", sum(len(v) for v in _out.values()), "rows")
