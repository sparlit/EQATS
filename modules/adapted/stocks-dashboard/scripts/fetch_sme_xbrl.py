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
"""SME + long-period balance-sheet backfill for xbrl_extra (runbook §148).

WHY. The deep ledger held NO balance sheet for the NSE SME board and none from any filing whose
reporting period is longer than a quarter:
  * SME companies file HALF-YEARLY results in the NON-Ind-AS taxonomy (TangibleAssets, not
    PropertyPlantAndEquipment) — the builder knew only the Ind-AS names;
  * build_xbrl_extra.parse_file returned None for any OneD > 100 days, so 877 cached six-month
    INTEGRATED filings (481 companies, 172 of them SME) contributed nothing;
  * the SME filings from 2024 were never fetched at all (the nightly lists a 14-day window).
NSE lists SME XBRL only from the FY24 year-end results (filed Apr-2024); 2020-2023 SME rows carry
the placeholder link ".../corporate/xbrl/-" (measured 2026-09-23).

WHAT. Three steps, each resumable:
  --list    month-by-month SME results lists, 2024-01 → today, from BOTH endpoints
            (corporates-financial-results: the 2024 NONINDAS files; integrated-filing-results: the
            2025+ INTEGRATED files) → scripts/_sme_xbrl_list.json (gitignored)
  --fetch   download each listed XBRL into scripts/_xbrl_cache_sme/ (a SEPARATE cache: build_revop
            reads the main cache and trusts the context block, which in 2024 SME files says Jul-Sep
            for an Apr-Sep half — so these files must never reach it) and record every filename in
            scripts/xbrl_sme_files.json (tracked; build_xbrl_extra routes a listed Half-yearly /
            Yearly file to the BS-only parser)
  --merge   parse the SME cache + the main cache's long-period files with build_xbrl_extra and
            merge ONLY the BS-only rows, FILL-ONLY, into scripts/xbrl_extra.json.gz

Run from a worktree:
  XBRL_CACHE=/Users/dhruvan/stocks-dashboard/scripts/_xbrl_cache \
  SME_CACHE=/Users/dhruvan/stocks-dashboard/scripts/_xbrl_cache_sme \
  python3 -X utf8 scripts/fetch_sme_xbrl.py --list --fetch --merge [--dry]
"""
import argparse
import contextlib
import datetime
import gzip
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
LIST = os.path.join(HERE, "_sme_xbrl_list.json")
LEDGER = os.path.join(HERE, "xbrl_sme_files.json")
SME_CACHE = os.environ.get("SME_CACHE") or os.path.join(HERE, "_xbrl_cache_sme")
GZ = os.path.join(HERE, "xbrl_extra.json.gz")
REF = "https://www.nseindia.com/companies-listing/corporate-filings-financial-results"
START = datetime.date(2024, 1, 1)


def canon(url):
    import re

    return re.sub(r"[^A-Za-z0-9]", "_", url.rsplit("/", 1)[-1])


class NSE:
    """curl_cffi Chrome session (the transport update_fundamentals / xtra_nightly already use)."""

    def __init__(self):
        self.s = None

    def get(self, url, timeout=120):
        from curl_cffi import requests as cr

        for attempt in range(4):
            try:
                if self.s is None:
                    self.s = cr.Session(impersonate="chrome")
                    self.s.get("https://www.nseindia.com/", timeout=30)
                    self.s.get(REF, timeout=30)
                r = self.s.get(url, headers={"Referer": REF}, timeout=timeout)
                if r.status_code == 200:
                    return r.text
                raise RuntimeError("HTTP %d" % r.status_code)
            except Exception as e:
                self.s = None
                print("   retry %d %s: %s" % (attempt + 1, url[-70:], str(e)[:70]), flush=True)
                time.sleep(5 * (attempt + 1))
        raise RuntimeError("gave up: " + url)


def months(a, b):
    d = a
    while d <= b:
        nxt = (d.replace(day=28) + datetime.timedelta(days=4)).replace(day=1)
        yield d, min(nxt - datetime.timedelta(days=1), b)
        d = nxt


def do_list(nse):
    rows = {}
    with contextlib.suppress(OSError, ValueError):
        rows = {r["xbrl"]: r for r in json.load(open(LIST))}
    today = datetime.date.today()
    for a, b in months(START, today):
        f, t = a.strftime("%d-%m-%Y"), b.strftime("%d-%m-%Y")
        got = 0
        for per in ("Half-Yearly", "Annual", "Quarterly"):
            u = (
                f"https://www.nseindia.com/api/corporates-financial-results?index=sme&period={per}"
                f"&from_date={f}&to_date={t}"
            )
            j = json.loads(nse.get(u))
            for r in j if isinstance(j, list) else j.get("data", []):
                xb = r.get("xbrl") or ""
                if xb.lower().endswith(".xml"):
                    rows.setdefault(
                        xb,
                        {
                            "xbrl": xb,
                            "symbol": r.get("symbol"),
                            "toDate": r.get("toDate"),
                            "fromDate": r.get("fromDate"),
                            "cons": r.get("consolidated"),
                            "period": per,
                            "src": "cfr",
                            "bcast": r.get("broadCastDate"),
                        },
                    )
                    got += 1
            time.sleep(1.2)
        page = 1
        while True:
            u = (
                "https://www.nseindia.com/api/integrated-filing-results?index=sme&period=Quarterly"
                "&from_date=%s&to_date=%s&page=%d&size=200" % (f, t, page)
            )
            j = json.loads(nse.get(u))
            d = j.get("data", []) if isinstance(j, dict) else j
            for r in d or []:
                xb = r.get("xbrl") or ""
                if xb.lower().endswith(".xml") and "governance" not in (r.get("type") or "").lower():
                    rows.setdefault(
                        xb,
                        {
                            "xbrl": xb,
                            "symbol": r.get("symbol"),
                            "toDate": r.get("qe_Date") or r.get("toDate"),
                            "period": r.get("period"),
                            "src": "ifr",
                            "bcast": r.get("broadcast_Date"),
                        },
                    )
                    got += 1
            total = (j.get("totalCount") or 0) if isinstance(j, dict) else 0
            if not d or page * 200 >= total or page > 50:
                break
            page += 1
            time.sleep(1.2)
        print("list %s..%s: +%d rows seen, %d unique so far" % (f, t, got, len(rows)), flush=True)
        json.dump(list(rows.values()), open(LIST, "w"))
    return list(rows.values())


def do_fetch(nse, rows):
    os.makedirs(SME_CACHE, exist_ok=True)
    have = set(os.listdir(SME_CACHE))
    try:
        ledger = set(json.load(open(LEDGER)))
    except (OSError, ValueError):
        ledger = set()
    new = fail = 0
    for i, r in enumerate(rows):
        fn = canon(r["xbrl"])
        ledger.add(fn)
        if fn in have:
            continue
        try:
            xml = nse.get(r["xbrl"], timeout=90)
        except Exception as e:
            fail += 1
            print("  FAIL {} {}".format(r.get("symbol"), str(e)[:60]))
            continue
        if len(xml) < 500 or "<xbrli:xbrl" not in xml[:3000]:
            fail += 1
            print("  BAD  %s %s (%d bytes)" % (r.get("symbol"), fn[:40], len(xml)))
            continue
        with open(os.path.join(SME_CACHE, fn), "w", encoding="utf-8") as fh:
            fh.write(xml)
        have.add(fn)
        new += 1
        if new % 100 == 0:
            print("  fetched %d (%d/%d listed, %d failed)" % (new, i + 1, len(rows), fail), flush=True)
            json.dump(sorted(ledger), open(LEDGER, "w"), indent=0)
        time.sleep(0.8)
    json.dump(sorted(ledger), open(LEDGER, "w"), indent=0)
    print("fetch: +%d files, %d failed, cache %d, ledger %d" % (new, fail, len(have), len(ledger)))


def pow10_off(v, ref, tol=0.03):
    """Exactly 10^k apart (k = ±1..3)? The filer scale-error signature (§147/§148)."""
    if not v or not ref:
        return False
    r = abs(v / ref)
    return any(abs(r / f - 1) <= tol for f in (10, 100, 1000, 0.1, 0.01, 0.001))


def scale_screen(cands, data):
    """Drop BS-only candidate rows carrying a filer power-of-ten error. Anchor = share capital
    (it almost never moves by exactly 10^k): the median of every sc this (symbol, basis) shows in
    the candidates AND the committed ledger. Rows without sc fall back to Total Assets vs the
    nearest-period neighbour. TRUST Sep-2024 filed sc 2.38 / assets 11.63 cr beside 23.83 / 117.56
    in Mar-25 and Sep-25 — every money field /10 (measured 2026-09-23)."""
    import statistics as st

    by = {}
    for r in cands:
        for b in ("s", "c"):
            if r[b]:
                by.setdefault((r["sym"], b), []).append((r["qe"], r[b]))
    for sym, qs in data.items():
        for qe, cell in qs.items():
            for b in ("s", "c"):
                d = cell.get(b) if isinstance(cell, dict) else None
                if isinstance(d, dict) and (sym, b) in by and (d.get("sc") or d.get("assets")):
                    by[(sym, b)].append((int(qe), dict(d, _store=1)))
    drop = set()
    for (sym, b), rows in by.items():
        scs = [d["sc"] for _, d in rows if d.get("sc")]
        med = st.median(scs) if len(scs) >= 2 else None
        rows.sort(key=lambda t: t[0])
        for i, (qe, d) in enumerate(rows):
            if d.get("_store"):
                continue
            if med and d.get("sc"):
                if pow10_off(d["sc"], med):
                    drop.add((sym, qe, b))
                continue
            nb = [rows[j][1].get("assets") for j in (i - 1, i + 1) if 0 <= j < len(rows)]
            nb = [x for x in nb if x]
            if d.get("assets") and nb and all(pow10_off(d["assets"], x) for x in nb):
                drop.add((sym, qe, b))
    return drop


def do_merge(dry):
    import build_xbrl_extra as BX  # reads xbrl_sme_files.json at import — fetch first

    data = json.loads(gzip.decompress(open(GZ, "rb").read()))
    jobs = [(SME_CACHE, f) for f in os.listdir(SME_CACHE)] if os.path.isdir(SME_CACHE) else []
    main = BX.CACHE
    for f in os.listdir(main):  # the main cache's long-period files (INTEGRATED halves)
        if f.startswith("INTEGRATED"):
            jobs.append((main, f))
    jobs.sort(key=lambda j: BX.ts_key(j[1]))
    cands = []
    for d, f in jobs:
        try:
            r = BX.parse_file(os.path.join(d, f), f)
        except Exception:
            r = None
        if r and r.get("bso"):
            r["_main"] = d == main
            cands.append(r)
    drop = scale_screen(cands, data)
    print("scale screen: %d basis-rows dropped as filer power-of-ten" % len(drop))
    for x in sorted(drop)[:40]:
        print("   drop", x)
    stats = {
        "files": len(jobs),
        "bso": len(cands),
        "cells_new": 0,
        "fields_filled": 0,
        "fields_kept": 0,
        "new_from_sme": 0,
        "new_from_main": 0,
    }
    for r in cands:  # ascending filing time: a later filing fills first-come
        cell = data.setdefault(r["sym"], {}).setdefault(str(r["qe"]), {})
        for b in ("s", "c"):
            if not r[b] or (r["sym"], r["qe"], b) in drop:
                continue
            if b not in cell:
                stats["cells_new"] += 1
                stats["new_from_main" if r["_main"] else "new_from_sme"] += 1
            tgt = cell.setdefault(b, {})
            for k, v in r[b].items():
                if k in tgt:
                    stats["fields_kept"] += 1
                else:
                    tgt[k] = v
                    stats["fields_filled"] += 1
    for sym in [s for s, qs in data.items() if not qs]:
        del data[sym]
    print("merge:", stats)
    if not dry:
        blob = json.dumps(data, separators=(",", ":")).encode("utf-8")
        open(GZ, "wb").write(gzip.compress(blob, 9))
        print("wrote", GZ)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--fetch", action="store_true")
    ap.add_argument("--merge", action="store_true")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    nse = NSE()
    rows = None
    if a.list:
        rows = do_list(nse)
    if a.fetch:
        rows = rows if rows is not None else json.load(open(LIST))
        do_fetch(nse, rows)
    if a.merge:
        do_merge(a.dry)


if __name__ == "__main__":
    main()
