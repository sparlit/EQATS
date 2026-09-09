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
"""CON-GAP PRE-2020 campaign (scripts/PLAN_CON_GAP_PRE2020.md) -- REACH MEASUREMENT for 2008Q1..2014Q4.

Job 1 of the plan: before filling anything, MEASURE how many of the pre-2015 consolidated-PAT gap
cells ever had a consolidated QUARTERLY document. Runbook §53 measured 2015Q1-2019Q4 (2.7%); this
sweep does the same for the older window, symbol by symbol, on two independent readers:

  --route nse   NSE results-archive list API (corporates-financial-results?symbol=X&period=Quarterly
                and =Annual). Serves back to ~2005 and declares basis per row ("Consolidated" /
                "Non-Consolidated"), cumulative flag, filing date and the detail-page link. Era
                symbols (renames) are queried too -- NSE keys its archive by the symbol that traded
                THEN (runbook feedback-nse-archive-first trap 1). Each raw list is cached under
                scripts/_nsearch_cache/list_<SYM>.json in the exact shape _nse_archive_revop.list_rows
                uses, so the gated reader later finds its GATE S' std pages without refetching.
  --route mc    Moneycontrol cons_quarterly + quarterly feeds via agg_sources.mc_quarters. For each
                gap cell, records MC's con PAT (owners row when present) AND MC's own std PAT for the
                same quarter. §85: a con row IDENTICAL to MC's own std row is UNRESOLVED (MC repeats
                standalone where no consolidated result was filed); only a DIFFERING row is evidence
                that a consolidated table exists for that quarter -- and even that is a candidate for
                a filing read, never a value to write (§100: differs != a consolidated table exists).

Outputs (resumable; symbols already present are skipped):
  scripts/fill2020_tools/_con_pre2015_nse_inventory.json
  scripts/fill2020_tools/_con_pre2015_mc_inventory.json

Run:  python3 scripts/fill2020_tools/con_discover_pre2015.py --route nse [--limit N] [--only SYM,SYM]
      python3 scripts/fill2020_tools/con_discover_pre2015.py --route mc  [--limit N] [--only SYM,SYM]
"""
import contextlib
import csv
import json
import os
import re
import sys
import time
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
TARGETS = os.path.join(HERE, "_con_targets_pre2015.json")
OUT_NSE = os.path.join(HERE, "_con_pre2015_nse_inventory.json")
OUT_MC = os.path.join(HERE, "_con_pre2015_mc_inventory.json")
LIST_CACHE = os.path.join(SCRIPTS, "_nsearch_cache")

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


def to_qe(s):
    """'30-Sep-2010' -> 20100930."""
    try:
        d, mo, y = (s or "").strip().split("-")
        return int(y) * 10000 + MON[mo.title()] * 100 + int(d)
    except Exception:
        return None


def aliases(sym):
    """Era symbols for sym (transitive, oldest last) -- same sources as _nse_archive_revop.aliases:
    scripts/_rename_map.json (era->current) + scripts/symchg.csv (old,new)."""
    edges = {}
    try:
        for old, new in json.load(open(os.path.join(SCRIPTS, "_rename_map.json"))).items():
            edges.setdefault(new.upper(), set()).add(old.upper())
    except Exception:
        pass
    try:
        for row in csv.reader(open(os.path.join(SCRIPTS, "symchg.csv"), encoding="utf8", errors="replace")):
            if len(row) >= 3 and row[1].strip() and row[2].strip():
                edges.setdefault(row[2].strip().upper(), set()).add(row[1].strip().upper())
    except Exception:
        pass
    out, queue, seen = [], [sym.upper()], {sym.upper()}
    while queue:
        for old in sorted(edges.get(queue.pop(0), ())):
            if old not in seen:
                seen.add(old)
                out.append(old)
                queue.append(old)
    return out


# ------------------------------------------------------------------ NSE route
def fresh_session():
    from curl_cffi import requests as cr

    s = cr.Session(impersonate="chrome")
    s.get("https://www.nseindia.com/", timeout=45)
    time.sleep(1)
    return s


def fetch_list(sess, sym, period):
    u = "https://www.nseindia.com/api/corporates-financial-results?index=equities&symbol={}&period={}".format(
        urllib.parse.quote(sym, safe=""), period
    )
    r = sess.get(
        u,
        headers={"Referer": "https://www.nseindia.com/companies-listing/corporate-filings-financial-results"},
        timeout=45,
    )
    if r.status_code != 200:
        raise RuntimeError("http%d" % r.status_code)
    d = r.json()
    return d if isinstance(d, list) else d.get("data", [])


def list_cached(sess, s, period):
    """Quarterly lists are cached in _nse_archive_revop's own format/path so GATE S' reads are free."""
    if period == "Quarterly":
        lp = os.path.join(LIST_CACHE, "list_{}.json".format(re.sub(r"[^A-Z0-9]", "_", s.upper())))
        if os.path.exists(lp):
            try:
                got = json.load(open(lp))
                if isinstance(got, list) and got:
                    return got, True
            except Exception:
                pass
        rows = fetch_list(sess, s, period)
        os.makedirs(LIST_CACHE, exist_ok=True)
        json.dump(rows, open(lp, "w"))
        return rows, False
    return fetch_list(sess, s, period), False


def is_con(row):
    return (row.get("consolidated") or "").strip().lower().startswith("consolidated")


def run_nse(targets, todo):
    inv = json.load(open(OUT_NSE)) if os.path.exists(OUT_NSE) else {}
    sess = fresh_session()
    consec_err = 0
    for i, sym in enumerate(todo):
        gaps = set(targets[sym]["qes"])
        names = [sym] + [a for a in aliases(sym) if a != sym]
        key = targets[sym].get("key")
        if key and key.upper() not in {n.upper() for n in names}:
            names.append(key)
        rec = {
            "names": names,
            "rows": 0,
            "rows_by_name": {},
            "in_scope_rows": 0,
            "con_rows_total": 0,
            "first_con_toDate": None,
            "oldest_toDate": None,
            "con_qtr": {},
            "std_qtr": {},
            "con_ann": {},
            "cum_con_qtr": {},
        }
        try:
            qrows = []
            for s in names:
                rows, cached = list_cached(sess, s, "Quarterly")
                if not cached:
                    time.sleep(0.8)
                rec["rows_by_name"][s] = len(rows)
                qrows.extend(rows)
            rec["rows"] = len(qrows)
            qes_all = [to_qe(r.get("toDate")) for r in qrows]
            qes_all = [q for q in qes_all if q]
            rec["oldest_toDate"] = min(qes_all) if qes_all else None
            con_qes = [to_qe(r.get("toDate")) for r in qrows if is_con(r)]
            con_qes = [q for q in con_qes if q]
            rec["con_rows_total"] = len(con_qes)
            rec["first_con_toDate"] = min(con_qes) if con_qes else None
            for r in qrows:
                qe = to_qe(r.get("toDate"))
                if not qe or not (QE_LO <= qe <= QE_HI):
                    continue
                rec["in_scope_rows"] += 1
                if qe not in gaps:
                    continue
                cum = (r.get("cumulative") or "").strip().lower()
                entry = {
                    "link": r.get("resultDetailedDataLink"),
                    "filed": r.get("filingDate"),
                    "cumulative": r.get("cumulative"),
                    "audited": r.get("audited"),
                    "relatingTo": r.get("relatingTo"),
                    "symbol": r.get("symbol"),
                }
                if is_con(r):
                    bucket = "cum_con_qtr" if cum.startswith("cumulative") else "con_qtr"
                    rec[bucket].setdefault(str(qe), entry)
                else:
                    rec["std_qtr"].setdefault(str(qe), r.get("resultDetailedDataLink"))
            # consolidated ANNUAL rows (the §45/§53d FY-identity gate needs them; never a source)
            arows = []
            for s in names:
                arows.extend(fetch_list(sess, s, "Annual"))
                time.sleep(0.8)
            for r in arows:
                if is_con(r):
                    qe = to_qe(r.get("toDate"))
                    if qe and 20080101 <= qe <= 20150631 and r.get("resultDetailedDataLink"):
                        rec["con_ann"][str(qe)] = r["resultDetailedDataLink"]
            consec_err = 0
        except Exception as ex:
            rec["err"] = f"{type(ex).__name__}:{str(ex)[:80]}"
            consec_err += 1
            with contextlib.suppress(Exception):
                sess = fresh_session()
            if consec_err >= 10:
                print("!! 10 consecutive failures -- NSE lockdown? aborting (resumable).", flush=True)
                inv[sym] = rec
                break
        inv[sym] = rec
        if (i + 1) % 10 == 0 or i + 1 == len(todo):
            json.dump(inv, open(OUT_NSE, "w"), indent=0, sort_keys=True)
            hits = sum(len(v["con_qtr"]) for v in inv.values())
            print(
                "  [%d/%d] %s rows=%d con_total=%d first_con=%s | con-qtr hits in scope so far: %d"
                % (i + 1, len(todo), sym, rec["rows"], rec["con_rows_total"], rec["first_con_toDate"], hits),
                flush=True,
            )
    json.dump(inv, open(OUT_NSE, "w"), indent=0, sort_keys=True)
    hits = sum(len(v["con_qtr"]) for v in inv.values())
    errs = sum(1 for v in inv.values() if v.get("err"))
    print("NSE DONE: %d symbols, %d gap cells with a con quarterly row, %d errors" % (len(inv), hits, errs))


# ------------------------------------------------------------------ MC route
def run_mc(targets, todo):
    sys.path.insert(0, os.path.join(SCRIPTS, "agg_tools"))
    import agg_sources as A

    fund = json.load(open(os.path.join(ROOT, "docs", "sf_fundamentals.json")))
    inv = json.load(open(OUT_MC)) if os.path.exists(OUT_MC) else {}
    for i, sym in enumerate(todo):
        gaps = targets[sym]["qes"]
        rec = {"cells": {}}
        try:
            ident = A.mc_id(sym)
            rec["mc_id"] = ident
            if not ident:
                rec["note"] = "no exact symbol match in MC autosuggest"
            else:
                con, cnote = A.mc_quarters(sym, True)
                std, snote = A.mc_quarters(sym, False)
                rec["con_note"], rec["std_note"] = cnote, snote
                rec["con_n"], rec["std_n"] = len(con), len(std)
                rec["con_oldest"] = min(con) if con else None
                rec["std_oldest"] = min(std) if std else None
                # IDENTITY ANCHOR (§81e): MC's STANDALONE series must reproduce our stored std PAT
                # over the gap quarters, or MC is not talking about this company/vintage and its
                # consolidated verdict counts for nothing. Journalled as hits/tries, not a boolean.
                ours = {r[0]: r[1] for r in fund.get(targets[sym].get("key", sym), []) if r[1] is not None}
                tries = hits = 0
                for qe in gaps:
                    sv = (std.get(qe) or {}).get("pat_total")
                    ov = ours.get(qe)
                    if sv is None or ov is None:
                        continue
                    tries += 1
                    if abs(sv - ov) <= max(0.06, abs(ov) * 0.005):
                        hits += 1
                rec["std_anchor"] = {"hits": hits, "tries": tries}
                for qe in gaps:
                    c, s = con.get(qe), std.get(qe)
                    cell = {}
                    if c:
                        cell["con_own"] = c.get("pat_own")
                        cell["con_total"] = c.get("pat_total")
                    if s:
                        cell["std_total"] = s.get("pat_total")
                    cv = cell.get("con_total")
                    sv = cell.get("std_total")
                    if cv is None and c is None:
                        cell["state"] = "no-con-row"
                    elif cv is None:
                        cell["state"] = "con-row-no-pat"
                    elif sv is None:
                        cell["state"] = "no-std-row"  # §85b: unverifiable, HOLD-NO-TWIN
                    elif abs(cv - sv) <= 0.005:
                        cell["state"] = "identical"  # §85: UNRESOLVED
                    else:
                        cell["state"] = "differs"  # candidate only (§100)
                    rec["cells"][str(qe)] = cell
        except Exception as ex:
            rec["err"] = f"{type(ex).__name__}:{str(ex)[:80]}"
        inv[sym] = rec
        if (i + 1) % 10 == 0 or i + 1 == len(todo):
            json.dump(inv, open(OUT_MC, "w"), indent=0, sort_keys=True)
            d = sum(1 for v in inv.values() for c in v["cells"].values() if c.get("state") == "differs")
            print(
                "  [%d/%d] %s con_n=%s oldest=%s | differs-cells so far: %d"
                % (i + 1, len(todo), sym, rec.get("con_n"), rec.get("con_oldest"), d),
                flush=True,
            )
    json.dump(inv, open(OUT_MC, "w"), indent=0, sort_keys=True)
    print("MC DONE: %d symbols" % len(inv))


def main():
    global TARGETS, OUT_NSE, OUT_MC, QE_LO, QE_HI
    args = sys.argv[1:]
    route = args[args.index("--route") + 1] if "--route" in args else "nse"
    limit = int(args[args.index("--limit") + 1]) if "--limit" in args else None
    only = set(args[args.index("--only") + 1].split(",")) if "--only" in args else None
    # --window LO HI / --targets / --out: run the same sweep over another quarter window (the
    # 2015Q1-2019Q4 pass reuses the cached quarterly lists, so only the annual lists refetch).
    if "--window" in args:
        i = args.index("--window")
        QE_LO, QE_HI = int(args[i + 1]), int(args[i + 2])
    if "--targets" in args:
        TARGETS = args[args.index("--targets") + 1]
    if "--out" in args:
        if route == "nse":
            OUT_NSE = args[args.index("--out") + 1]
        else:
            OUT_MC = args[args.index("--out") + 1]
    targets = json.load(open(TARGETS))
    out = OUT_NSE if route == "nse" else OUT_MC
    inv = json.load(open(out)) if os.path.exists(out) else {}
    todo = [s for s in sorted(targets) if s not in inv and (not only or s in only)]
    if limit:
        todo = todo[:limit]
    print("%s discovery: %d symbols to sweep (%d already done)" % (route, len(todo), len(inv)), flush=True)
    (run_nse if route == "nse" else run_mc)(targets, todo)


if __name__ == "__main__":
    main()
