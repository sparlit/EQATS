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
POINT-IN-TIME MARKET BREADTH 2002 -> date, for TWO universes (Nifty 500 and F&O), as a
backtest REGIME input. Derived entirely from our own survivorship-free daily bars.

Output: docs/market_breadth_pit.json -- minified JSON the backtest engine can lazy-load
(fetch('./market_breadth_pit.json'), same pattern as shp_engine.json). NOT wired into
simulate() by this builder -- the regime-gate decision is a separate measurement.

  { "updated":"YYYY-MM-DD", "dataEnd":"YYYY-MM-DD", "source":"...",
    "dmaWin":200, "hlWin":252, "axisFrom":20020102,
    "membership": { "n500": "...", "fno": "..." },       # provenance strings
    "conventions": { ... },                              # one line per rule, for readers
    "dates": [YYYYMMDD ints, one per trading day on the axis],
    "n500": { <arrays> }, "fno": { <arrays> } }

  Per-universe arrays (all integers, one per axis date; a reader derives the ratios):
    nMem  point-in-time roster size (latest snapshot effectiveDate <= day; DUMMY*/DVR dropped)
    nObs  members that traded that day with a positive close   <- the coverage denominator
    n200  members with >= 200 daily-era sessions (eligible for the 200-DMA test)
    a200  of those, members whose close is ABOVE their 200-session SMA  -> pct200 = 100*a200/n200
    nAD   members with a previous daily-era close (eligible for advance/decline)
    adv   of those, closed UP vs their own previous close;  dec = closed DOWN;  flat = nAD-adv-dec
    n52   members with >= 252 daily-era sessions (eligible for the 52-week test)
    hi    of those, close == max close of the trailing 252 sessions (new 52w high; ties count)
    lo    of those, close == min close of the trailing 252 sessions (new 52w low)
  pct200 is UNDEFINED (null) while n200 == 0 -- the engine e16 smaBarsAt rule ("null until 200
  exist") applied to the universe: the reader must divide, never assume.

METHOD / CONVENTIONS (each one measured against the engine or the sibling builder, 2026-09-05)
  - Prices: docs/sf_stock_data.bin -- the LIVE sf-data rebuild (scripts/fetch_live_sf.py) or the
    `data` release asset in CI; NEVER the frozen committed copy (runbook section 0). Closes are the
    bin's corp-action-adjusted `c`. Bars with a non-positive close are skipped (the zero-close
    penny-stock defect, 16 Nifty-500 member-days in 2015 -- the engine drops those rows too).
  - Membership: docs/dash_slim.bin indicesHistory["Nifty 500"] (329 event-driven snapshots
    1998-08-01..) and fnoHistory (188 snapshots 2001-11-29..), the SAME objects the engine's
    membersAsOf() reads (loadCore). Verified byte-identical to scripts/indices_history.json and
    scripts/fno_history.json on 2026-09-05. Latest effectiveDate <= day; NO floor to the first
    snapshot (a date before it has NO universe -- refuse, never fabricate; runbook section 48).
    DUMMY* placeholders and DVR lines (TATAMTRDVR, JISLDVREQS: a second security of a company
    already in the universe) are dropped, as the engine's rowsAt() drops them.
  - Rename fold (engine membersAsOf rule): a roster name that IS a bin key is used as-is (many old
    names still carry their own era tape); a roster name with NO series of its own is folded
    through scripts/_rename_map.json chained to its end (LTI->LTIM->LTM). Measured: Nifty 500
    rosters are current-keyed (0 folds, 5 unresolved names pre-2004: ADCINDIA ASIIL ITHL TCIIND
    ATVPR); F&O rosters carry traded-then names (95 distinct folds, 0 unresolved). Two roster
    names folding to one series count once.
  - Windows are OBSERVATION-based over DAILY-ERA bars only (bin `dailyFrom` = 2002-01-02): the
    200-DMA is the SMA of the member's last 200 trading sessions including today, null until 200
    exist (engine e16 smaBarsAt; pre-2002 bars are weekly samples and are not sessions -- so the
    first ~200 sessions of 2002 carry n200 = 0 and the 52w window fills through ~Jan 2003; the
    per-day coverage counts make that visible instead of hiding it behind a warm-up).
  - New 52w high/low and advance/decline follow build_market_breadth.py exactly (252-session
    close window incl. today, ties count; adv/dec vs the member's own previous observed close,
    flats neither) so the two files agree on their overlap. NOTE the engine's own d52 (hl52) is a
    365-calendar-day window over exact intraday highs/lows -- a different quantity, kept out of
    this file on purpose.
  - Axis = every date >= dailyFrom on which any member of either universe has a bar; a date with
    fewer than MIN_OBS_DATE Nifty-500 observations is a feed glitch and is dropped (0 such dates
    on the 2026-09-04 bin; the builder prints any it drops).

Run:  python3 -X utf8 scripts/build_market_breadth_pit.py
      SF_BIN=/path/to/fresh.bin DASH_SLIM=/path/to/dash_slim.bin python3 -X utf8 scripts/build_market_breadth_pit.py
"""
import gzip
import json
import os
import sys
from bisect import bisect_right
from collections import defaultdict, deque

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BIN = os.environ.get("SF_BIN") or os.path.join(ROOT, "docs", "sf_stock_data.bin")
SLIM = os.environ.get("DASH_SLIM") or os.path.join(ROOT, "docs", "dash_slim.bin")
RMAP = os.path.join(HERE, "_rename_map.json")
OUT = os.path.join(ROOT, "docs", "market_breadth_pit.json")

DMA_WIN = 200  # sessions in the moving average (includes today)
HL_WIN = 252  # sessions in the 52-week high/low window (includes today)
MIN_OBS_DATE = 50  # drop glitch dates with fewer Nifty-500 member observations than this
UNIVERSES = (("n500", "Nifty 500"), ("fno", "__FNO__"))
ARRAYS = ("nMem", "nObs", "n200", "a200", "nAD", "adv", "dec", "n52", "hi", "lo")


def resolve_chain(old, rmap):
    """Follow old -> new -> ... to the end of the rename chain (cycle-safe; same as check_fund_alias)."""
    seen, target = {old}, rmap[old]
    while target in rmap and rmap[target] not in seen:
        seen.add(target)
        target = rmap[target]
    return target


def roster_key(sym, data, rmap, skip_dvr=True):
    """Map a roster name to the bin series that carries it. Returns (key, how):
    how in {'skip','direct','fold','unresolved'}; key is None unless direct/fold."""
    s = str(sym)
    if s.upper().startswith("DUMMY") or (skip_dvr and "DVR" in s):
        return None, "skip"
    if s in data:
        return s, "direct"
    if s in rmap:
        t = resolve_chain(s, rmap)
        if t in data:
            return t, "fold"
    return None, "unresolved"


def load_snaps(slim, name):
    """Sorted (effectiveDate int, [roster symbols]) for an index name or '__FNO__'."""
    raw = slim.get("fnoHistory", []) if name == "__FNO__" else slim.get("indicesHistory", {}).get(name, [])
    if not raw:
        msg = f"no membership snapshots for {name!r} in {SLIM}"
        raise SystemExit(msg)
    snaps = sorted((int(s["effectiveDate"].replace("-", "")), list(s["symbols"])) for s in raw)
    return [s[0] for s in snaps], [s[1] for s in snaps]


def build(D, slim, rmap, skip_dvr=True, log=print):
    """Compute the series. Returns (out_dict, stats). Pure: writes nothing."""
    data, end_iso = D["data"], D["end"]
    daily_from = int(D["dailyFrom"].replace("-", ""))
    log("bin: %d symbols, dailyFrom=%d, end=%s" % (len(data), daily_from, end_iso))

    # --- per-universe snapshots, resolved to bin keys ---
    U = {}
    for key, name in UNIVERSES:
        sdates, rosters = load_snaps(slim, name)
        res_sets, mem_n, how_tot, unres = [], [], defaultdict(int), set()
        for roster in rosters:
            keys, n_mem = set(), 0
            for sym in roster:
                k, how = roster_key(sym, data, rmap, skip_dvr)
                how_tot[how] += 1
                if how == "skip":
                    continue
                if k is None:
                    unres.add(str(sym))
                    n_mem += 1  # unresolved still counts in the roster
                elif k not in keys:
                    keys.add(k)
                    n_mem += 1  # two names -> one series counts once
            res_sets.append(frozenset(keys))
            mem_n.append(n_mem)
        U[key] = {
            "name": name,
            "sdates": sdates,
            "sets": res_sets,
            "nMem": mem_n,
            "first": sdates[0],
            "last": sdates[-1],
            "n": len(sdates),
            "how": dict(how_tot),
            "unresolved": sorted(unres),
        }
        log(
            "membership %s: %d snapshots %d..%d, resolution %s, unresolved %s"
            % (key, len(sdates), sdates[0], sdates[-1], dict(how_tot), sorted(unres))
        )

    # --- global trading-day axis: union of member bar dates from dailyFrom on ---
    union = set()
    for u in U.values():
        for s in u["sets"]:
            union |= s
    all_dates = set()
    for sym in union:
        e = data.get(sym)
        if e:
            all_dates.update(d for d in e["d"] if d >= daily_from)
    dates = sorted(all_dates)
    didx = {d: i for i, d in enumerate(dates)}
    n = len(dates)
    log("axis: %d trading days %d..%d" % (n, dates[0], dates[-1]))

    # which snapshot applies on each axis date (latest effectiveDate <= day). NO floor: a date
    # before a universe's first snapshot has no roster -- refuse rather than fabricate one.
    for key, u in U.items():
        u["snap_of"] = [bisect_right(u["sdates"], d) - 1 for d in dates]
        if u["snap_of"][0] < 0:
            raise SystemExit(
                "axis starts %d, before the first %s snapshot %d -- refusing to "
                "fabricate a universe" % (dates[0], key, u["sdates"][0])
            )

    acc = {key: {a: [0] * n for a in ARRAYS} for key in U}
    for key, u in U.items():
        so, nm = u["snap_of"], u["nMem"]
        acc[key]["nMem"] = [nm[so[i]] for i in range(n)]
    zero_close = dict.fromkeys(U, 0)

    for sym in union:
        e = data.get(sym)
        if not e:
            continue
        ds, cs = e["d"], e["c"]
        s200 = 0.0
        win = deque()  # rolling 200-sum + the closes in the window
        mx = deque()
        mn = deque()  # monotonic deques of (obs#, close) for HL_WIN
        k = 0  # daily-era observation counter (positive closes only)
        prev = None
        for j in range(len(ds)):
            d = ds[j]
            if d < daily_from:
                continue
            c = cs[j]
            gi = didx.get(d)
            if not c or c <= 0:
                if gi is not None:
                    for key, u in U.items():
                        if sym in u["sets"][u["snap_of"][gi]]:
                            zero_close[key] += 1
                continue
            k += 1
            win.append(c)
            s200 += c
            if len(win) > DMA_WIN:
                s200 -= win.popleft()
            while mx and mx[-1][1] <= c:
                mx.pop()
            mx.append((k, c))
            while mn and mn[-1][1] >= c:
                mn.pop()
            mn.append((k, c))
            while mx[0][0] <= k - HL_WIN:
                mx.popleft()
            while mn[0][0] <= k - HL_WIN:
                mn.popleft()

            if gi is not None:
                above = (k >= DMA_WIN) and (c > s200 / DMA_WIN)
                for key, u in U.items():
                    if sym not in u["sets"][u["snap_of"][gi]]:
                        continue
                    A = acc[key]
                    A["nObs"][gi] += 1
                    if prev is not None:
                        A["nAD"][gi] += 1
                        if c > prev:
                            A["adv"][gi] += 1
                        elif c < prev:
                            A["dec"][gi] += 1
                    if k >= DMA_WIN:
                        A["n200"][gi] += 1
                        if above:
                            A["a200"][gi] += 1
                    if k >= HL_WIN:
                        A["n52"][gi] += 1
                        if c >= mx[0][1]:
                            A["hi"][gi] += 1
                        if c <= mn[0][1]:
                            A["lo"][gi] += 1
            prev = c

    # --- drop glitch dates (too few Nifty-500 observations) ---
    keep = [i for i in range(n) if acc["n500"]["nObs"][i] >= MIN_OBS_DATE]
    dropped = [dates[i] for i in range(n) if acc["n500"]["nObs"][i] < MIN_OBS_DATE]
    if dropped:
        log("dropped %d glitch dates (<%d N500 obs): %s" % (len(dropped), MIN_OBS_DATE, dropped[:20]))

    def pick(a):
        return [a[i] for i in keep]

    out = {
        "updated": end_iso,
        "dataEnd": end_iso,
        "source": "NSE bhavcopy closes (corp-action adjusted, survivorship-free sf bin), daily era %d+; "
        "point-in-time Nifty 500 and F&O rosters from dash_slim.bin" % daily_from,
        "dmaWin": DMA_WIN,
        "hlWin": HL_WIN,
        "axisFrom": daily_from,
        "membership": {
            "n500": "dash_slim.bin indicesHistory['Nifty 500']: %d snapshots %d..%d, latest effectiveDate<=day"
            % (U["n500"]["n"], U["n500"]["first"], U["n500"]["last"]),
            "fno": "dash_slim.bin fnoHistory: %d snapshots %d..%d, latest effectiveDate<=day"
            % (U["fno"]["n"], U["fno"]["first"], U["fno"]["last"]),
        },
        "conventions": {
            "pct200": "100*a200/n200; null while n200==0 (engine e16 smaBarsAt: SMA of the last 200 TRADING sessions incl. today, null until 200 exist; daily-era bars only)",
            "advDec": "adv/dec vs the member's own previous daily-era close; flat = nAD-adv-dec",
            "hiLo": "close == max/min close of the trailing 252 sessions incl. today (ties count); eligible when n52 sessions exist",
            "roster": "DUMMY* and DVR names dropped; roster name used as-is when it is a bin key, else folded via _rename_map chained; unresolved names stay in nMem",
            "coverage": "nMem = roster size, nObs = members with a positive close that day; nMem-nObs = unresolved + not traded + zero-close",
        },
        "dates": pick(dates),
    }
    for key in U:
        out[key] = {a: pick(acc[key][a]) for a in ARRAYS}
    stats = {
        "axis_n": n,
        "kept": len(keep),
        "dropped": dropped,
        "zero_close": zero_close,
        "universes": {
            k: {kk: u[kk] for kk in ("name", "n", "first", "last", "how", "unresolved")} for k, u in U.items()
        },
    }
    return out, stats


def coverage_report(out, log=print):
    """Per-year coverage per universe: days, mean roster / observed / eligible counts."""
    dates = out["dates"]
    years = sorted({d // 10000 for d in dates})
    for key, _ in UNIVERSES:
        A = out[key]
        log(
            f"coverage {key} (per year: days, mean nMem, mean nObs, obs%, mean n200, dma%, mean n52, 52w%, "
            "first day n200>0, first day n200>=90% of nObs)"
        )
        for y in years:
            idx = [i for i, d in enumerate(dates) if d // 10000 == y]

            def m(a):
                return sum(A[a][i] for i in idx) / len(idx)

            f200 = next((dates[i] for i in idx if A["n200"][i] > 0), None)
            f90 = next((dates[i] for i in idx if A["nObs"][i] and A["n200"][i] >= 0.9 * A["nObs"][i]), None)
            log(
                "  %d %4d %6.1f %6.1f %5.1f%% %6.1f %5.1f%% %6.1f %5.1f%%  %s  %s"
                % (
                    y,
                    len(idx),
                    m("nMem"),
                    m("nObs"),
                    100 * m("nObs") / max(m("nMem"), 1e-9),
                    m("n200"),
                    100 * m("n200") / max(m("nObs"), 1e-9),
                    m("n52"),
                    100 * m("n52") / max(m("nObs"), 1e-9),
                    f200,
                    f90,
                )
            )


def main():
    D = json.loads(gzip.decompress(open(BIN, "rb").read()))
    slim = json.loads(gzip.decompress(open(SLIM, "rb").read()))
    rmap = json.load(open(RMAP, encoding="utf-8"))
    out, stats = build(D, slim, rmap)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, separators=(",", ":"))
    kb = os.path.getsize(OUT) / 1024.0
    print(
        "Wrote %s (%.0f KB, %d days %d..%d; zero-close member-days skipped %s)"
        % (OUT, kb, len(out["dates"]), out["dates"][0], out["dates"][-1], stats["zero_close"]),
        flush=True,
    )
    # --- sanity anchors ---
    for key, _ in UNIVERSES:
        A, dts = out[key], out["dates"]
        pct = [100.0 * A["a200"][i] / A["n200"][i] if A["n200"][i] else None for i in range(len(dts))]
        valid = [i for i in range(len(dts)) if pct[i] is not None]
        imin = min(valid, key=lambda i: pct[i])
        imax = max(valid, key=lambda i: pct[i])
        ilo = max(range(len(dts)), key=lambda i: A["lo"][i])
        ihi = max(range(len(dts)), key=lambda i: A["hi"][i])
        print(
            "%s latest %d: pct200=%.1f%% (a200/n200=%d/%d, nObs=%d/nMem=%d) adv/dec=%d/%d hi/lo=%d/%d (n52=%d)"
            % (
                key,
                dts[-1],
                pct[-1] if pct[-1] is not None else float("nan"),
                A["a200"][-1],
                A["n200"][-1],
                A["nObs"][-1],
                A["nMem"][-1],
                A["adv"][-1],
                A["dec"][-1],
                A["hi"][-1],
                A["lo"][-1],
                A["n52"][-1],
            ),
            flush=True,
        )
        print(
            "%s pct200 defined from %d; min %.1f%% on %d | max %.1f%% on %d | most new lows %d on %d | most new highs %d on %d"
            % (
                key,
                dts[valid[0]],
                pct[imin],
                dts[imin],
                pct[imax],
                dts[imax],
                A["lo"][ilo],
                dts[ilo],
                A["hi"][ihi],
                dts[ihi],
            ),
            flush=True,
        )
    coverage_report(out)


if __name__ == "__main__":
    main()
