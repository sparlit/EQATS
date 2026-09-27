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
"""FII/DII accumulation-streak event study (research, 2026-09-26).

Question (user): if FII (or DII) raises its stake for K consecutive quarters, does the stock run
more afterwards — and how much?  Also: do the BIGGEST single-quarter FII/DII jumps run?

Point-in-time rules (same as the site's engines / build_shp_backtest.py):
  * signal source = docs/shp_engine.json  {SYM:[[qeInt,fii,dii,subInt,prom,mf],...]}
    - quarter-end rows only (event rows have no calendar-previous quarter)
    - visible on subInt; undated rows (sub==99999999, pre-2014) visible at qe+28d (runbook §120)
    - a delta is only taken against the CALENDAR-previous quarter (a gap breaks the streak)
    - no delta across the SEBI format change Jun-2022 -> Sep-2022 (runbook §22b)
    - streak = consecutive quarters with dFII >= +0.05pp (shareholding.html definition)
  * entry = close of the FIRST trading day strictly AFTER the visibility date
  * forward return over 30/91/182/365 calendar days (close on/before target; a delisted name
    exits at its last close — survivorship-free bin)
  * excess = stock return minus the MEDIAN return of every filer in the same quarter cohort
    (removes the market); also minus the Nifty 500 index over the exact window (2012+)
  * universe tags: PIT Nifty 500 member at entry (scripts/_n500_member_bin) vs not
"""
import collections
import datetime
import gzip
import json
import math
import os
import random
import sys
from bisect import bisect_left, bisect_right

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import _n500_member_bin as N5  # §48: the point-in-time Nifty 500 source

# Prices: the LIVE bin (docs/sf_stock_data.bin is a stale committed snapshot — runbook §0/§7.0).
# Fetch it once into the cache folder:  python3 -c "import sys;sys.path.insert(0,'scripts');import fetch_live_sf as f;
#   f.DST='<home>/stocks-cache/sf-live/sf_stock_data.bin';f.main()"
_LIVE = os.path.expanduser("~/stocks-cache/sf-live/sf_stock_data.bin")
BIN = os.environ.get("SF_BIN") or (_LIVE if os.path.exists(_LIVE) else os.path.join(ROOT, "docs", "sf_stock_data.bin"))
ENGINE = os.path.join(ROOT, "docs", "shp_engine.json")
RENAME = os.path.join(HERE, "_rename_map.json")
BENCH = os.path.join(ROOT, "docs", "nifty500.json")
OUTDIR = os.environ.get("STUDY_OUT") or os.path.expanduser("~/stocks-cache/shp/streak_study")
os.makedirs(OUTDIR, exist_ok=True)

# Run:  python3 scripts/shp_streak_study.py            # build events.json + report.txt in OUTDIR (~20 s)
#       python3 scripts/shp_streak_study.py report     # re-print the report from the saved events.json
# Findings + verdict: DATA_RUNBOOK.md §177; full printout committed as scripts/SHP_STREAK_STUDY_REPORT.txt

MIN_STEP = 0.05
QE_MD = {331, 630, 930, 1231}
UNDATED = 99999999
CONV_DAYS = 28
HORIZONS = [30, 91, 182, 365]
FMT_BOUNDARY = (20220630, 20220930)


def iso(d):
    return "%04d-%02d-%02d" % (d // 10000, d // 100 % 100, d % 100)


def dt(d):
    return datetime.date(d // 10000, d // 100 % 100, d % 100)


def di(x):
    return x.year * 10000 + x.month * 100 + x.day


def add_days(d, n):
    return di(dt(d) + datetime.timedelta(days=n))


def prev_qe(q):
    y, m = q // 10000, q // 100 % 100
    m -= 3
    if m <= 0:
        y, m = y - 1, 12
    return y * 10000 + m * 100 + {3: 31, 6: 30, 9: 30, 12: 31}[m]


def main():
    D = json.loads(gzip.decompress(open(BIN, "rb").read()))
    data, bin_end = D["data"], D.get("end")
    print("bin", BIN, "symbols", len(data), "end", bin_end, "dailyFrom", D.get("dailyFrom"), flush=True)
    bin_end_i = int(str(bin_end).replace("-", ""))
    ren = json.load(open(RENAME))

    def res(sym):
        s, seen = sym, set()
        while s not in data and s in ren and s not in seen:
            seen.add(s)
            s = ren[s]
        return s if s in data else (sym if sym in data else None)

    # trading axis = union of dates of symbols with long daily histories (>= 2000 bars)
    ax = set()
    for o in data.values():
        if len(o["d"]) >= 2000:
            ax.update(o["d"])
    axis = sorted(x for x in ax if x >= 20010101)
    print("axis", len(axis), axis[0], axis[-1], flush=True)

    def next_after(d):
        i = bisect_right(axis, d)
        return axis[i] if i < len(axis) else None

    def at_or_after(d):
        i = bisect_left(axis, d)
        return axis[i] if i < len(axis) else None

    cache = {}

    def close_at(bk, d):
        e = cache.get(bk)
        if e is None:
            o = data[bk]
            e = (o["d"], o["c"])
            cache[bk] = e
        ds, cs = e
        i = bisect_right(ds, d) - 1
        while i >= 0 and not cs[i]:
            i -= 1
        return cs[i] if i >= 0 else None

    def close_on(bk, d):  # close exactly on d (entry must be a real bar)
        e = cache.get(bk)
        if e is None:
            o = data[bk]
            e = (o["d"], o["c"])
            cache[bk] = e
        ds, cs = e
        i = bisect_left(ds, d)
        return cs[i] if i < len(ds) and ds[i] == d and cs[i] else None

    bpx = {int(k.replace("-", "")): v for k, v in json.load(open(BENCH))["px"].items()}
    bkeys = sorted(bpx)

    def bench_at(d):
        i = bisect_right(bkeys, d) - 1
        return bpx[bkeys[i]] if i >= 0 else None

    E = json.load(open(ENGINE))
    print("engine symbols", len(E), flush=True)
    nrm = N5.norm
    mem_cache = {}

    def is_member(sym, d):
        m = mem_cache.get(d)
        if m is None:
            m = mem_cache[d] = N5.membership(d)
        return (nrm(sym) in m) or (sym in m)

    events = []
    n_rows = n_noprice = 0
    for sym, rows in E.items():
        bk = res(sym)
        rows = sorted([r for r in rows if r[0] % 10000 in QE_MD], key=lambda r: r[0])
        byqe = {r[0]: r for r in rows}
        fst = {}
        dst = {}
        cst = {}
        bst = {}
        for r in rows:
            q, fii, dii, sub, prom, _mf = r[0], r[1], r[2], r[3], r[4], r[5]
            n_rows += 1
            p = byqe.get(prev_qe(q))
            dfii = ddii = dprom = None
            if p is not None and (prev_qe(q), q) != FMT_BOUNDARY:
                if fii is not None and p[1] is not None:
                    dfii = fii - p[1]
                if dii is not None and p[2] is not None:
                    ddii = dii - p[2]
                if prom is not None and p[4] is not None:
                    dprom = prom - p[4]
            # streaks (calendar-consecutive; a gap or a None resets)
            pf = fst.get(prev_qe(q), 0)
            pd = dst.get(prev_qe(q), 0)
            pc = cst.get(prev_qe(q), 0)
            pb = bst.get(prev_qe(q), 0)
            sf = pf + 1 if (dfii is not None and dfii >= MIN_STEP) else 0
            sd = pd + 1 if (ddii is not None and ddii >= MIN_STEP) else 0
            sc = pc + 1 if (dfii is not None and dfii <= -MIN_STEP) else 0
            sb = pb + 1 if (dfii is not None and ddii is not None and dfii >= MIN_STEP and ddii >= MIN_STEP) else 0
            fst[q] = sf
            dst[q] = sd
            cst[q] = sc
            bst[q] = sb
            # next quarter's move (for continuation stats) — NOT used for returns
            nx = byqe.get(add_q(q))
            ndfii = None
            if nx is not None and (q, add_q(q)) != FMT_BOUNDARY and nx[1] is not None and fii is not None:
                ndfii = nx[1] - fii
            vis = sub if sub != UNDATED else add_days(q, CONV_DAYS)
            dated = sub != UNDATED
            if bk is None:
                n_noprice += 1
                continue
            entry = next_after(vis)
            if entry is None:
                continue
            c0 = close_on(bk, entry)
            if not c0:
                n_noprice += 1
                continue
            rets = {}
            for h in HORIZONS:
                tgt = add_days(entry, h)
                if tgt > bin_end_i:
                    rets[h] = None
                    continue
                c1 = close_at(bk, tgt)
                rets[h] = (c1 / c0 - 1) * 100 if c1 else None
            brets = {}
            b0 = bench_at(entry) if entry >= bkeys[0] else None
            for h in HORIZONS:
                tgt = add_days(entry, h)
                b1 = bench_at(tgt) if (b0 and tgt <= bin_end_i and tgt <= bkeys[-1]) else None
                brets[h] = (b1 / b0 - 1) * 100 if (b0 and b1) else None
            cm6 = close_at(bk, add_days(entry, -182))
            mom6 = (c0 / cm6 - 1) * 100 if cm6 else None
            events.append(
                {
                    "mom6": mom6,
                    "sym": sym,
                    "bk": bk,
                    "q": q,
                    "vis": vis,
                    "dated": dated,
                    "entry": entry,
                    "fii": fii,
                    "dii": dii,
                    "prom": prom,
                    "dfii": dfii,
                    "ddii": ddii,
                    "dprom": dprom,
                    "sf": sf,
                    "sd": sd,
                    "sc": sc,
                    "sb": sb,
                    "ndfii": ndfii,
                    "n500": is_member(sym, entry),
                    "r": rets,
                    "b": brets,
                }
            )
    print("rows", n_rows, "events", len(events), "no-price", n_noprice, flush=True)

    # cohort medians per (quarter, horizon)
    coh = collections.defaultdict(list)
    for ev in events:
        for h in HORIZONS:
            if ev["r"][h] is not None:
                coh[(ev["q"], h)].append(ev["r"][h])
    cmed = {k: median(v) for k, v in coh.items()}
    cmean = {k: sum(v) / len(v) for k, v in coh.items()}
    for ev in events:
        ev["ex"] = {h: (ev["r"][h] - cmed[(ev["q"], h)]) if ev["r"][h] is not None else None for h in HORIZONS}
        ev["exm"] = {h: (ev["r"][h] - cmean[(ev["q"], h)]) if ev["r"][h] is not None else None for h in HORIZONS}
        ev["exb"] = {
            h: (ev["r"][h] - ev["b"][h]) if (ev["r"][h] is not None and ev["b"][h] is not None) else None
            for h in HORIZONS
        }
    json.dump(events, open(os.path.join(OUTDIR, "events.json"), "w"), separators=(",", ":"))
    print("wrote events.json", flush=True)
    report(events, bin_end)


def add_q(q):
    y, m = q // 10000, q // 100 % 100
    m += 3
    if m > 12:
        y, m = y + 1, m - 12
    return y * 10000 + m * 100 + {3: 31, 6: 30, 9: 30, 12: 31}[m]


def median(v):
    s = sorted(v)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def stats(vals):
    n = len(vals)
    if n == 0:
        return {"n": 0}
    m = sum(vals) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in vals) / (n - 1)) if n > 1 else 0.0
    t = m / (sd / math.sqrt(n)) if sd > 0 else 0.0
    hit = sum(1 for x in vals if x > 0) / n * 100
    return {"n": n, "mean": round(m, 2), "med": round(median(vals), 2), "hit": round(hit, 1), "t": round(t, 2)}


def cluster_ci(evs, h, key="ex", B=400, seed=7):
    """95% CI of the mean excess, bootstrapping QUARTERS (events within a quarter are correlated)."""
    byq = collections.defaultdict(list)
    for e in evs:
        if e[key][h] is not None:
            byq[e["q"]].append(e[key][h])
    qs = list(byq)
    if len(qs) < 4:
        return None
    rnd = random.Random(seed)
    means = []
    for _ in range(B):
        pick = [byq[rnd.choice(qs)] for _ in qs]
        flat = [x for grp in pick for x in grp]
        means.append(sum(flat) / len(flat))
    means.sort()
    return (round(means[int(0.025 * B)], 2), round(means[int(0.975 * B) - 1], 2))


def era(q):
    y = q // 10000
    if y <= 2013:
        return "A 2001-13 (convention dates)"
    if q < 20190930:
        return "B 2014-Jun19 (dated, ~N500)"
    return "C Sep19-2026 (dated, all filers)"


def bucket_streak(k):
    return "6+" if k >= 6 else str(k)


def rebase(evs, h):
    """excess of each event vs the MEAN and MEDIAN of THIS subset's same-quarter cohort (pp)."""
    coh = collections.defaultdict(list)
    for e in evs:
        if e["r"][h] is not None:
            coh[e["q"]].append(e["r"][h])
    cm = {q: sum(v) / len(v) for q, v in coh.items()}
    cd = {q: median(v) for q, v in coh.items()}
    out = []
    for e in evs:
        if e["r"][h] is None:
            continue
        out.append((e, e["r"][h] - cm[e["q"]], e["r"][h] - cd[e["q"]]))
    return out


def qboot(trip, idx, B=400, seed=7, med=False):
    byq = collections.defaultdict(list)
    for t in trip:
        byq[t[0]["q"]].append(t[idx])
    qs = list(byq)
    if len(qs) < 4:
        return ""
    rnd = random.Random(seed)
    vals = []
    for _ in range(B):
        flat = [x for _ in qs for x in byq[rnd.choice(qs)]]
        vals.append(median(flat) if med else sum(flat) / len(flat))
    vals.sort()
    return f"({vals[int(0.025 * B)]:.2f}, {vals[int(0.975 * B) - 1]:.2f})"


def table(title, groups, evs, keyfn, h, exkey="ex", order=None, ci=False):
    if exkey == "exb":
        print("\n### %s — horizon %dd — excess vs NIFTY 500 index over the exact window (2012+)" % (title, h))
        print("%-34s %7s %8s %8s %6s %7s" % ("bucket", "n", "mean", "median", "hit%", "t"))
        rows = collections.defaultdict(list)
        for e in evs:
            k = keyfn(e)
            if k is None or e["exb"][h] is None:
                continue
            rows[k].append(e["exb"][h])
        for k in order or sorted(rows):
            if k in rows:
                st = stats(rows[k])
                print("%-34s %7d %8.2f %8.2f %6.1f %7.2f" % (k, st["n"], st["mean"], st["med"], st["hit"], st["t"]))
        return
    trip = rebase(evs, h)  # cohort = THIS table's population, same quarter
    print(
        "\n### %s — horizon %dd — excess vs same-quarter cohort of THIS table (pp): mean vs cohort mean · median/hit vs cohort median"
        % (title, h)
    )
    print(
        "%-34s %7s %8s %8s %6s %7s %-18s %s"
        % ("bucket", "n", "mean", "median", "hit%", "t", "CI95 mean" if ci else "", "CI95 median" if ci else "")
    )
    rows = collections.defaultdict(list)
    for t in trip:
        k = keyfn(t[0])
        if k is None:
            continue
        rows[k].append(t)
    for k in order or sorted(rows):
        if k not in rows:
            continue
        mv = [t[1] for t in rows[k]]
        xv = [t[2] for t in rows[k]]
        sm = stats(mv)
        sx = stats(xv)
        print(
            "%-34s %7d %8.2f %8.2f %6.1f %7.2f %-18s %s"
            % (
                k,
                sm["n"],
                sm["mean"],
                sx["med"],
                sx["hit"],
                sm["t"],
                qboot(rows[k], 1) if ci else "",
                qboot(rows[k], 2, med=True) if ci else "",
            )
        )


def report(events, bin_end):
    out = open(os.path.join(OUTDIR, "report.txt"), "w")

    class Tee:
        def write(self, s):
            sys.__stdout__.write(s)
            out.write(s)

        def flush(self):
            sys.__stdout__.flush()
            out.flush()

    sys.stdout = Tee()
    print("# FII/DII streak event study — bin end %s — %d events" % (bin_end, len(events)))
    dated = sum(1 for e in events if e["dated"])
    print("dated visibility %d, convention (qe+28d) %d" % (dated, len(events) - dated))
    print(
        "N500 member at entry %d, non-member %d"
        % (sum(1 for e in events if e["n500"]), sum(1 for e in events if not e["n500"]))
    )
    byera = collections.Counter(era(e["q"]) for e in events)
    print("eras", dict(byera))

    def S(e):
        return bucket_streak(e["sf"]) if e["dfii"] is not None else None

    order = ["0", "1", "2", "3", "4", "5", "6+"]
    for h in HORIZONS:
        table("FII raising streak (all eras, all filers)", None, events, S, h, order=order, ci=(h in (91, 182, 365)))
    for h in (91, 182, 365):
        table("FII streak — N500 members only", None, [e for e in events if e["n500"]], S, h, order=order, ci=True)
        table(
            "FII streak — NON-members (small/mid, Sep-2019+)",
            None,
            [e for e in events if not e["n500"]],
            S,
            h,
            order=order,
            ci=True,
        )
    for er in sorted(byera):
        for h in (182, 365):
            table(f"FII streak — era {er}", None, [e for e in events if era(e["q"]) == er], S, h, order=order)

    # collapsed: streak>=3 vs streak 0 vs cut streak
    def grp(e):
        if e["sf"] >= 3:
            return "FII up 3+ qtrs"
        if e["sf"] == 2:
            return "FII up 2 qtrs"
        if e["sf"] == 1:
            return "FII up 1 qtr"
        if e["sc"] >= 2:
            return "FII cut 2+ qtrs"
        if e["dfii"] is None:
            return "no comparable prior qtr"
        return "FII flat/cut 1"

    for h in HORIZONS:
        table("Collapsed groups", None, events, grp, h, ci=True)
    for h in (182, 365):
        table("Collapsed — excess vs NIFTY 500 index (2012+)", None, events, grp, h, exkey="exb", ci=True)

    # DII
    def SD(e):
        return bucket_streak(e["sd"]) if e["ddii"] is not None else None

    for h in (91, 182, 365):
        table("DII raising streak (all)", None, events, SD, h, order=order, ci=True)

    def SB(e):
        return bucket_streak(e["sb"]) if (e["dfii"] is not None and e["ddii"] is not None) else None

    for h in (182, 365):
        table("FII AND DII both raising streak", None, events, SB, h, order=order, ci=True)

    # size of the quarter's FII jump
    def jb(e):
        d = e["dfii"]
        if d is None:
            return None
        for lo, hi, lab in [
            (-999, -2, "a  <= -2pp"),
            (-2, -0.5, "b  -2..-0.5"),
            (-0.5, -0.05, "c  -0.5..-0.05"),
            (-0.05, 0.05, "d  flat"),
            (0.05, 0.5, "e  +0.05..0.5"),
            (0.5, 1, "f  +0.5..1"),
            (1, 2, "g  +1..2"),
            (2, 5, "h  +2..5"),
            (5, 999, "i  > +5pp"),
        ]:
            if lo <= d < hi:
                return lab
        return None

    for h in (91, 182, 365):
        table("Size of the quarter FII change (pp)", None, events, jb, h, ci=True)

    def jbd(e):
        d = e["ddii"]
        if d is None:
            return None
        for lo, hi, lab in [
            (-999, -2, "a  <= -2pp"),
            (-2, -0.5, "b  -2..-0.5"),
            (-0.5, -0.05, "c  -0.5..-0.05"),
            (-0.05, 0.05, "d  flat"),
            (0.05, 0.5, "e  +0.05..0.5"),
            (0.5, 1, "f  +0.5..1"),
            (1, 2, "g  +1..2"),
            (2, 5, "h  +2..5"),
            (5, 999, "i  > +5pp"),
        ]:
            if lo <= d < hi:
                return lab
        return None

    for h in (91, 182, 365):
        table("Size of the quarter DII change (pp)", None, events, jbd, h, ci=True)
    # top-20 biggest FII jumps per quarter
    byq = collections.defaultdict(list)
    for e in events:
        if e["dfii"] is not None:
            byq[e["q"]].append(e)
    top = set()
    for lst in byq.values():
        lst.sort(key=lambda e: -e["dfii"])
        for e in lst[:20]:
            top.add(id(e))
    for h in (91, 182, 365):
        table(
            "Top-20 FII jumps of each quarter vs rest",
            None,
            events,
            lambda e: ("top20 FII jump" if id(e) in top else "rest") if e["dfii"] is not None else None,
            h,
            ci=True,
        )

    # big jump with promoter unchanged (no capital event) vs with promoter change
    def jump_clean(e):
        if e["dfii"] is None or e["dfii"] < 2:
            return None
        if e["dprom"] is None:
            return "jump>=2pp, promoter delta unknown"
        return "jump>=2pp, promoter moved >=1pp" if abs(e["dprom"]) >= 1 else "jump>=2pp, promoter steady"

    for h in (182, 365):
        table("FII jump >= 2pp split by promoter movement", None, events, jump_clean, h, ci=True)

    # streak >= 3 conditioned on level
    def lvl(e):
        if e["sf"] < 3:
            return None
        f = e["fii"]
        return "streak3+, FII<2%" if f < 2 else "streak3+, FII 2-10%" if f < 10 else "streak3+, FII>=10%"

    for h in (182, 365):
        table("FII streak 3+ by FII level", None, events, lvl, h, ci=True)
    # continuation
    print("\n### Does the streak continue? P(FII raises again next quarter | streak k)")
    byk = collections.defaultdict(lambda: [0, 0])
    for e in events:
        if e["ndfii"] is None:
            continue
        k = bucket_streak(e["sf"])
        byk[k][1] += 1
        if e["ndfii"] >= MIN_STEP:
            byk[k][0] += 1
    for k in order:
        if k in byk:
            print("  streak %-3s n=%6d  raised again %.1f%%" % (k, byk[k][1], byk[k][0] / byk[k][1] * 100))
    # year-by-year consistency, streak>=3 vs all, 182d
    print("\n### Year by year: mean 182d excess of FII streak>=3 (n) — consistency check")
    base = [e for e in events if e["dfii"] is not None]
    trip = rebase(base, 182)
    yr = collections.defaultdict(list)
    yrx = collections.defaultdict(list)
    for e, xm, xd in trip:
        if e["sf"] >= 3:
            yr[e["q"] // 10000].append(xm)
            yrx[e["q"] // 10000].append(xd)
    pos = posm = 0
    for y in sorted(yr):
        m = sum(yr[y]) / len(yr[y])
        md = median(yrx[y])
        pos += m > 0
        posm += md > 0
        print("  %d  n=%4d  mean-excess %+6.2f  median-excess %+6.2f" % (y, len(yr[y]), m, md))
    print("  years positive: mean %d of %d · median %d of %d" % (pos, len(yr), posm, len(yr)))
    # ---- FII-OWNED stocks only (level >= 1%): does the streak add anything among institutionally held names?
    owned = [e for e in events if e["fii"] is not None and e["fii"] >= 1 and e["dfii"] is not None]
    for h in (91, 182, 365):
        table("FII streak — ONLY stocks with FII >= 1% (cohort = same)", None, owned, S, h, order=order, ci=True)
    ownedN = [e for e in owned if e["n500"]]
    for h in (182, 365):
        table("FII streak — N500 members with FII >= 1% (cohort = same)", None, ownedN, S, h, order=order, ci=True)
    for er in sorted(byera):
        table(f"FII streak — FII>=1%, era {er}", None, [e for e in owned if era(e["q"]) == er], S, 365, order=order)

    # ---- momentum control: is a streak just "the stock already went up"?
    def mom_tercile(evs, h):
        byq = collections.defaultdict(list)
        for e in evs:
            if e.get("mom6") is not None:
                byq[e["q"]].append(e["mom6"])
        cuts = {}
        for q, v in byq.items():
            v.sort()
            cuts[q] = (v[len(v) // 3], v[2 * len(v) // 3])

        def key(e):
            if e.get("mom6") is None or e["dfii"] is None:
                return None
            lo, hi = cuts[e["q"]]
            m = "mom LOW " if e["mom6"] < lo else "mom MID " if e["mom6"] < hi else "mom HIGH"
            return m + (" · FII streak>=3" if e["sf"] >= 3 else " · streak 0-2   ")

        return key

    for h in (182, 365):
        table(
            "Streak>=3 vs not, inside trailing-6m momentum terciles (all filers)",
            None,
            events,
            mom_tercile(events, h),
            h,
            ci=True,
        )

    # ---- relative jump (Sterlite-style: +59% of the prior stake) among stocks with prior FII >= 2%
    def rel(e):
        if e["dfii"] is None or e["fii"] is None:
            return None
        prev = e["fii"] - e["dfii"]
        if prev < 2:
            return None
        r = e["dfii"] / prev * 100
        for lo, hi, lab in [
            (-999, -25, "a  cut > 25%"),
            (-25, -5, "b  cut 5-25%"),
            (-5, 5, "c  within 5%"),
            (5, 25, "d  +5..25%"),
            (25, 50, "e  +25..50%"),
            (50, 100, "f  +50..100%"),
            (100, 9e9, "g  more than doubled"),
        ]:
            if lo <= r < hi:
                return lab
        return None

    for h in (91, 182, 365):
        table("Relative FII jump (% of prior stake), prior FII >= 2%", None, events, rel, h, ci=True)
    for er in sorted(byera):
        table(
            f"FII jump >= 2pp vs rest — era {er}",
            None,
            [e for e in events if era(e["q"]) == er and e["dfii"] is not None],
            lambda e: "FII jump >= 2pp" if e["dfii"] >= 2 else "rest",
            365,
        )
    # ---- anchors the user named
    print("\n### Anchors: STLTECH (Sterlite Tech) and PINELABS rows")
    for e in events:
        if e["sym"] in ("STLTECH", "PINELABS") and e["q"] >= 20250331:
            print(
                "  %-9s q=%d fii=%.2f dfii=%s streak=%d dii=%.2f ddii=%s vis=%d entry=%d r30=%s r91=%s r182=%s"
                % (
                    e["sym"],
                    e["q"],
                    e["fii"],
                    None if e["dfii"] is None else round(e["dfii"], 2),
                    e["sf"],
                    e["dii"],
                    None if e["ddii"] is None else round(e["ddii"], 2),
                    e["vis"],
                    e["entry"],
                    *[None if e["r"][h] is None else round(e["r"][h], 1) for h in (30, 91, 182)],
                )
            )

    # ---- raw 12m outcomes (not excess) — pooled across quarters, so TIMING confounds it (streaks pile up late in
    #      bull markets); the same-quarter tables above are the fair comparison. Kept because the odds are intuitive.
    def odds(title, sel, keyfn, keys):
        print(
            f"\n### {title} — RAW 12-month return, pooled (timing-confounded; see same-quarter tables for the fair test)"
        )
        print("%-18s %7s %9s %9s %10s %10s %10s" % ("bucket", "n", "median%", "mean%", "P(>+50%)", "P(2x)", "P(<-30%)"))
        rows = collections.defaultdict(list)
        for e in events:
            if not sel(e) or e["r"][365] is None:
                continue
            k = keyfn(e)
            if k is not None:
                rows[k].append(e["r"][365])
        for k in keys:
            v = rows.get(k)
            if not v:
                continue
            print(
                "%-18s %7d %9.1f %9.1f %10.1f %10.1f %10.1f"
                % (
                    k,
                    len(v),
                    median(v),
                    sum(v) / len(v),
                    100 * sum(1 for x in v if x > 50) / len(v),
                    100 * sum(1 for x in v if x > 100) / len(v),
                    100 * sum(1 for x in v if x < -30) / len(v),
                )
            )

    def own(e):
        return e["dfii"] is not None and e["fii"] is not None and e["fii"] >= 1

    odds("FII streak, stocks with FII >= 1%, all eras", own, lambda e: bucket_streak(e["sf"]), order)
    odds(
        "FII streak, stocks with FII >= 1%, era C Sep-2019+",
        lambda e: own(e) and e["q"] >= 20190930,
        lambda e: bucket_streak(e["sf"]),
        order,
    )

    def jk(e):
        d = e["dfii"]
        return (
            "jump >= +5pp"
            if d >= 5
            else "jump +2..5pp"
            if d >= 2
            else "rise +0.05..2pp"
            if d >= MIN_STEP
            else "flat"
            if d > -MIN_STEP
            else "cut"
        )

    odds(
        "FII change this quarter, stocks with FII >= 1%, all eras",
        own,
        jk,
        ["cut", "flat", "rise +0.05..2pp", "jump +2..5pp", "jump >= +5pp"],
    )
    # chained quarterly EW portfolios
    print(
        "\n### Chained quarterly equal-weight baskets (entry per-stock on visibility, held 91d; quarter cohorts averaged then chained)"
    )

    def chain(sel, label):
        byq = collections.defaultdict(list)
        for e in events:
            if sel(e) and e["r"][91] is not None:
                byq[e["q"]].append(e["r"][91])
        qs = sorted(byq)
        nav = 1.0
        navs = []
        for q in qs:
            if len(byq[q]) < 5:
                continue
            nav *= 1 + (sum(byq[q]) / len(byq[q])) / 100
            navs.append((q, nav))
        if len(navs) < 8:
            print("  %-34s too few quarters" % label)
            return
        yrs = (dt(navs[-1][0]) - dt(navs[0][0])).days / 365.25
        cagr = (navs[-1][1] ** (1 / yrs) - 1) * 100
        peak = 0
        mdd = 0
        for _, v in navs:
            peak = max(peak, v)
            mdd = min(mdd, v / peak - 1)
        print(
            "  %-34s quarters %3d  CAGR %6.1f%%  maxDD %6.1f%%  (%s→%s)"
            % (label, len(navs), cagr, mdd * 100, navs[0][0], navs[-1][0])
        )

    chain(lambda e: True, "ALL filers (baseline)")
    chain(lambda e: e["sf"] >= 1, "FII up this qtr (streak>=1)")
    chain(lambda e: e["sf"] >= 2, "FII streak>=2")
    chain(lambda e: e["sf"] >= 3, "FII streak>=3")
    chain(lambda e: e["sf"] >= 4, "FII streak>=4")
    chain(lambda e: e["sc"] >= 2, "FII CUT streak>=2 (control)")
    chain(lambda e: e["sd"] >= 3, "DII streak>=3")
    chain(lambda e: e["sb"] >= 2, "FII & DII both streak>=2")
    chain(lambda e: e["dfii"] is not None and e["dfii"] >= 2, "FII jump >= 2pp this qtr")
    chain(lambda e: e["ddii"] is not None and e["ddii"] >= 2, "DII jump >= 2pp this qtr")
    chain(lambda e: e["n500"], "ALL N500 members (baseline)")
    chain(lambda e: e["n500"] and e["sf"] >= 3, "N500 & FII streak>=3")
    chain(lambda e: e["n500"] and e["sf"] >= 4, "N500 & FII streak>=4")
    chain(lambda e: e["n500"] and e["sf"] >= 1 and e["fii"] >= 1, "N500 & FII>=1% & up this qtr")
    chain(lambda e: e["n500"] and e["fii"] is not None and e["fii"] >= 1, "N500 & FII>=1% (all)")
    chain(lambda e: e["n500"] and e["dfii"] is not None and e["dfii"] >= 2, "N500 & FII jump>=2pp")
    sys.stdout = sys.__stdout__
    out.close()
    print("wrote report.txt")


def load_events():
    evs = json.load(open(os.path.join(OUTDIR, "events.json")))
    for e in evs:
        for k in ("r", "b", "ex", "exm", "exb"):
            e[k] = {int(h): v for h, v in e[k].items()}
    return evs


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "report":
        import traceback

        try:
            report(load_events(), "from events.json")
        except Exception:
            sys.stdout = sys.__stdout__
            traceback.print_exc()
    else:
        main()
