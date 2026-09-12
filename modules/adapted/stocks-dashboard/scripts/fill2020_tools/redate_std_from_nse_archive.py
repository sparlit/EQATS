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
"""Re-date PLACEHOLDER standalone announce dates (2008Q1-2014Q4) from NSE's own results-archive filing
timestamps -- the exchange record the CON-GAP PRE-2020 campaign already cached for every symbol.

THE CLASS. The pre-2015 standalone rows were extracted from sources that never carried a filing date, and
the old fill_ann_dates.py stamped the SEBI-deadline convention instead: quarter-end + 45 days (Q1-Q3) or
+ 60 days (Q4), runbook §104b / §125 ("273 of 311 band-2014 proposals sat EXACTLY on qe+45d / qe+60d").
Measured 2026-09-02 over the campaign's 725 symbols: 2,408 cells on +45d, 664 on +60d, 4 on the ann=0
sentinel, of 15,948 standalone quarters 2008-2014. A placeholder is wrong in BOTH directions: most filers
report earlier than the deadline (the stored date then hides a published quarter for weeks -- TV-18's
Dec-2008 result was filed 29-Jan-2009 20:35, stored 14-Feb-2009), late filers report after it (the stored
date is then a look-ahead). The BSE announcement stream starts Jan-2014, so §125 could not reach this era;
NSE's archive list can (rows back to 2005, `filingDate` with time, basis declared per row).

WHAT IS WRITTEN. `exact` entries in scripts/ann_date_fills.json (asserted in both directions by
backfill_ann_dates_bse.py --reapply, rebuild-proof), carrying the §12 PIT gate: a filing at or after
15:30 IST, or on a non-trading day, is dated the NEXT trading day (scripts/_trading_days.json from the sf
bin, same calendar gate_1530.py uses). Each entry records the raw NSE timestamp, the row's declared basis
and period, and the placeholder it replaces.

GUARDS (all mandatory, every refusal journalled with its reason):
  * only cells whose stored std ann is EXACTLY qe+45d, qe+60d or 0 -- an observed date is never touched;
  * key not already in the ledger (an earlier adjudication outranks a sweep);
  * the NSE row is Non-Consolidated, Quarterly, non-cumulative, toDate == qe, and the EARLIEST such row
    (first declaration; a revised/re-filed row comes later);
  * qe < gated date <= qe + 200 d (outliers are refused for review, not written);
  * gated date >= the symbol's first traded bar over ALL its era names (§99 pre-listing carry-ins) --
    AGCNET's 1996 bars count for BBOX's 2008 rows, because that is the name the company traded under;
  * BASIS SPLIT (§119c): when the quarter also holds a consolidated announce date, the consolidated row's
    own gated NSE date must equal the standalone one, else the cell is skipped -- an `exact` entry stamps
    BOTH slots and must never move a consolidated date onto a different filing day;
  * CON DATE OBSERVED ELSEWHERE: a stored consolidated date that is neither the archive's raw/gated
    timestamp nor a placeholder was written by another reader (BSE broadcast, a filed pack): the cell is
    skipped rather than overwritten (readers have precedence, not votes);
  * ARCHIVE-LAG ERA (calibrated in-run, runbook §123h): per quarter-end, the tool measures how often the
    archive's gated date sits >= 4 days AFTER an OBSERVED stored standalone date. Measured 2026-09-02 on
    ~13,900 observed cells: 1-7% for 2008Q2-2010Q4, 10-16% in 2011, 19-80% from the Mar-2012 quarter on --
    from 2012 the archive records a LATER submission than the first public declaration for most filers.
    Where that rate exceeds 10%, a LATER-moving proposal is a lag, not a correction, and is refused; an
    EARLIER-moving one still tightens the placeholder toward the truth (the archive was never observed
    EARLIER than a declaration: 0-4%).

  python3 scripts/fill2020_tools/redate_std_from_nse_archive.py            # dry run -> proposals + summary
  python3 scripts/fill2020_tools/redate_std_from_nse_archive.py --write    # append to ann_date_fills.json
"""
import bisect
import datetime as dt
import glob
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
LIST_CACHE = os.path.join(SCRIPTS, "_nsearch_cache")
LEDGER = os.path.join(SCRIPTS, "ann_date_fills.json")
FUND = os.path.join(ROOT, "docs", "sf_fundamentals.json")
TDAYS = os.path.join(SCRIPTS, "_trading_days.json")
OUT = os.path.join(HERE, "_redate_std_proposals.json")
QE_LO, QE_HI = 20080331, 20141231
MON = {
    "Jan": 1,
    "Feb": 2,
    "Mar": 3,
    "Apr": 4,
    "May": 5,
    "Jun": 6,
    "Jul": 7,
    "Aug": 8,
    "Sep": 9,
    "Oct": 10,
    "Nov": 11,
    "Dec": 12,
}
STAMP = dt.datetime.now().strftime("%Y-%m-%d %H:%M IST")


def to_qe(s):
    try:
        d, mo, y = (s or "").strip().split(" ")[0].split("-")
        return int(y) * 10000 + MON[mo.title()] * 100 + int(d)
    except Exception:
        return None


def to_min(s):
    m = re.search(r"\s(\d{1,2}):(\d{2})", s or "")
    return (int(m.group(1)) * 60 + int(m.group(2))) if m else None


def plus(qe, days):
    x = dt.date(qe // 10000, qe // 100 % 100, qe % 100) + dt.timedelta(days=days)
    return x.year * 10000 + x.month * 100 + x.day


def iso(d):
    return "%04d-%02d-%02d" % (d // 10000, d // 100 % 100, d % 100)


def main():
    write = "--write" in sys.argv
    fund = json.load(open(FUND))
    ledger = json.load(open(LEDGER))
    tdays = json.load(open(TDAYS))
    tdset = set(tdays)

    def gate(d, minutes):
        """§12: at/after 15:30 or a non-trading day -> next trading day."""
        if d in tdset and (minutes is None or minutes < 15 * 60 + 30):
            return d, "same-day(%s)" % ("%02d:%02d" % divmod(minutes, 60) if minutes is not None else "no-time")
        i = bisect.bisect_right(tdays, d)
        return (tdays[i] if i < len(tdays) else None), (
            "next-td(after 15:30 %02d:%02d)" % divmod(minutes, 60)
            if (minutes is not None and minutes >= 930 and d in tdset)
            else "next-td(non-trading day)"
        )

    # era names per fundamentals key: the discovery inventories carry them, FUND_ALIAS the rest
    names_of = {}
    for f in glob.glob(os.path.join(HERE, "_con_*_nse_inventory.json")):
        for s, v in json.load(open(f)).items():
            names_of.setdefault(s, set()).update(v.get("names") or [s])
    key_of = {}
    for f in glob.glob(os.path.join(HERE, "_con_targets_*.json")):
        for s, v in json.load(open(f)).items():
            key_of[s] = v["key"]
    src = open(os.path.join(ROOT, "docs", "backtest-engine.js")).read()
    alias = json.loads(re.search(r"const FUND_ALIAS = (\{.*?\});", src).group(1))
    era_of_key = {}
    for era, cur in alias.items():
        era_of_key.setdefault(cur, set()).add(era)
    # first traded bar per bin ticker (builder --facts dump) -- earliest over every era name
    fp = (
        sys.argv[sys.argv.index("--facts") + 1] if "--facts" in sys.argv else os.path.join(HERE, "_coverage_facts.json")
    )
    facts = json.load(open(fp))["series"]  # build_coverage_matrix.js --facts <path>: per-ticker first bar

    def first_bar(key, names):
        cands = []
        for n in set(names) | {key} | era_of_key.get(key, set()):
            fb = (facts.get(n) or {}).get("firstBar")
            if fb:
                cands.append(int(fb.replace("-", "")))
        return min(cands) if cands else None

    def rows_for(names):
        out = []
        for n in names:
            p = os.path.join(LIST_CACHE, "list_{}.json".format(re.sub(r"[^A-Z0-9]", "_", n.upper())))
            if os.path.exists(p):
                try:
                    got = json.load(open(p))
                    if isinstance(got, list):
                        out.extend(got)
                except Exception:
                    pass
        return out

    def nse_rows(sym, names, key):
        rows = rows_for(set(names) | {sym, key})
        std_rows = {}
        con_rows = {}
        for r in rows:
            if (r.get("period") or "Quarterly") != "Quarterly":
                continue
            if (r.get("cumulative") or "").strip().lower().startswith("cumulative"):
                continue
            qe = to_qe(r.get("toDate"))
            if not qe:
                continue
            fd = to_qe(r.get("filingDate") or r.get("broadCastDate"))
            if not fd:
                continue
            mins = to_min(r.get("filingDate") or r.get("broadCastDate") or "")
            tgt = con_rows if (r.get("consolidated") or "").strip().lower().startswith("consolidated") else std_rows
            cur = tgt.get(qe)
            if cur is None or (fd, mins or 0) < (cur[0], cur[1] or 0):
                tgt[qe] = (fd, mins, r.get("filingDate") or r.get("broadCastDate"), r.get("symbol"))
        return std_rows, con_rows

    NSE = {}
    for sym, names in sorted(names_of.items()):
        key = key_of.get(sym, sym)
        if fund.get(key):
            NSE[sym] = nse_rows(sym, names, key)

    # ---- CALIBRATION (runbook §123h): per quarter-end, how often the archive's gated filing date sits
    # >= 4 days AFTER an OBSERVED stored standalone date (neither a placeholder nor written by this tool).
    LAG_MAX = 0.10
    calib = {}
    for sym, names in sorted(names_of.items()):
        key = key_of.get(sym, sym)
        arr = fund.get(key)
        if not arr or sym not in NSE:
            continue
        std_rows = NSE[sym][0]
        for q in arr:
            qe = q[0]
            if not (QE_LO <= qe <= QE_HI) or q[1] is None:
                continue
            a = q[2] or 0
            if a == 0 or a in (plus(qe, 45), plus(qe, 60)):
                continue
            k = "%s|%d" % (key, qe)
            if k in ledger and "123h" in (ledger[k].get("src") or ""):
                continue  # written by this tool: not an observation
            sr = std_rows.get(qe)
            if not sr:
                continue
            gd = gate(sr[0], sr[1])[0]
            if not gd:
                continue
            c = calib.setdefault(qe, [0, 0])
            c[0] += 1
            if (
                dt.date(gd // 10000, gd // 100 % 100, gd % 100) - dt.date(a // 10000, a // 100 % 100, a % 100)
            ).days >= 4:
                c[1] += 1
    lag_rate = {qe: (c[1] / c[0] if c[0] else None) for qe, c in calib.items()}
    print(
        "calibration (archive gated date >= 4d AFTER an observed std date), per quarter-end:",
        " ".join("%d:%d/%d" % (qe, c[1], c[0]) for qe, c in sorted(calib.items())),
    )

    proposals, skips = {}, {}
    stats = {"cells": 0, "earlier": 0, "later": 0, "same": 0}
    by_year = {}
    for sym, names in sorted(names_of.items()):
        key = key_of.get(sym, sym)
        arr = fund.get(key)
        if not arr or sym not in NSE:
            continue
        std_rows, con_rows = NSE[sym]
        fb = first_bar(key, names)
        for q in arr:
            qe = q[0]
            if not (QE_LO <= qe <= QE_HI) or q[1] is None:
                continue
            a = q[2] or 0
            kind = "+45d" if a == plus(qe, 45) else "+60d" if a == plus(qe, 60) else "zero" if a == 0 else None
            if kind is None:
                continue  # an observed date: never touched
            stats["cells"] += 1
            k = "%s|%d" % (key, qe)
            if k in ledger:
                skips[k] = "already-in-ledger"
                continue
            sr = std_rows.get(qe)
            if not sr:
                skips[k] = "no-nse-standalone-row"
                continue
            gd, how = gate(sr[0], sr[1])
            if gd is None or gd <= qe:
                skips[k] = f"gated-date-invalid({gd})"
                continue
            if gd > plus(qe, 200):
                skips[k] = "late-outlier(%d, %s)" % (gd, sr[2])
                continue
            if fb and gd < fb:
                skips[k] = "pre-listing(first bar %d, gated %d)" % (fb, gd)
                continue
            if len(q) > 4 and q[3] is not None and q[4] and q[4] > 0:
                cr = con_rows.get(qe)
                cg = gate(cr[0], cr[1])[0] if cr else None
                if cg != gd:
                    skips[k] = f"basis-split(std gated {gd}, con gated {cg}, stored con ann {q[4]})"
                    continue
                if q[4] not in (gd, cr[0], plus(qe, 45), plus(qe, 60)):
                    skips[k] = (
                        "con-date-observed-elsewhere(stored con ann %d is neither the archive's raw %d / "
                        "gated %d nor a placeholder: another reader dated it)" % (q[4], cr[0], gd)
                    )
                    continue
            direction = "earlier" if gd < a else "later" if (a and gd > a) else "same"
            if a == 0:
                direction = "fill"
            if direction == "later" and ((lag_rate.get(qe) is None) or lag_rate[qe] > LAG_MAX):
                lr = lag_rate.get(qe)
                skips[k] = (
                    "nse-archive-lag-era(qe %d: archive later than observed std dates in %s of %d cells; "
                    "a later move is a lag, not a correction)"
                    % (qe, ("%.0f%%" % (100 * lr)) if lr is not None else "n/a", calib.get(qe, [0, 0])[0])
                )
                continue
            stats[direction if direction in stats else "same"] = stats.get(direction, 0) + 1
            y = qe // 10000
            by_year.setdefault(y, {"proposed": 0, "earlier": 0, "later": 0, "same": 0, "fill": 0})
            by_year[y]["proposed"] += 1
            by_year[y][direction] += 1
            if direction == "same":
                skips[k] = "same-as-stored"
                continue
            proposals[k] = {
                "ann": gd,
                "was": a,
                "exact": True,
                "src": (
                    "nse-archive:list %s: NSE results-archive list row for %s, Non-Consolidated, Quarterly, "
                    "Non-cumulative, toDate %s, filingDate '%s' (earliest such row = first declaration), "
                    "listed under symbol %s; PIT gate §12 -> %s = %s. Replaces the %s placeholder %d "
                    "(the old fill_ann_dates.py SEBI-deadline convention, §104b/§125; not an observed date). "
                    "Campaign CON-GAP PRE-2020 (runbook §123h)."
                    % (STAMP, key, iso(qe), sr[2], sr[3], how, iso(gd), kind, a)
                ),
            }
    json.dump(
        {"proposals": proposals, "skips": skips, "stats": stats, "by_year": by_year},
        open(OUT, "w"),
        indent=1,
        sort_keys=True,
    )
    from collections import Counter

    print(
        "placeholder cells in scope:",
        stats["cells"],
        "| proposals:",
        len(proposals),
        "| earlier:",
        stats.get("earlier", 0),
        "later:",
        stats.get("later", 0),
        "fill(ann=0):",
        stats.get("fill", 0),
        "same-as-stored:",
        stats.get("same", 0),
    )
    print("by qe-year:", json.dumps(by_year, sort_keys=True))
    print("skips:", dict(Counter(v.split("(")[0] for v in skips.values())))
    lags = sorted(p["ann"] - p["was"] for p in proposals.values() if p["was"])
    if lags:
        import statistics

        dd = [
            (
                dt.date(p["ann"] // 10000, p["ann"] // 100 % 100, p["ann"] % 100)
                - dt.date(p["was"] // 10000, p["was"] // 100 % 100, p["was"] % 100)
            ).days
            for p in proposals.values()
            if p["was"]
        ]
        dd.sort()
        print(
            "gated date minus placeholder, days: min %d median %d p90 %d max %d"
            % (dd[0], statistics.median(dd), dd[int(len(dd) * 0.9)], dd[-1])
        )
    if not write:
        print(f"dry run -> {OUT}")
        return
    n = 0
    for k, v in proposals.items():
        if k not in ledger:
            ledger[k] = v
            n += 1
    json.dump(ledger, open(LEDGER, "w"), separators=(",", ":"))
    print("ledger: %d entries added -> %s" % (n, LEDGER))


if __name__ == "__main__":
    main()
