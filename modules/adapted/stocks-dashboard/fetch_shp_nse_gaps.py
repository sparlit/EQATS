# -*- coding: utf-8 -*-
"""Fill point-in-time Nifty-500 FII/DII holes from NSE's SHP master, newest quarter first.

Companion to fetch_shp_bse_hist.py, which can only reach BSE-listed names. This one is the route
for the NSE-ONLY cohort (BSE Ltd, CDSL — an exchange cannot list on itself) and for anything BSE
serves badly. NSE's master DOES answer for historical quarters as long as you ask for the filing
SEASON (QE → QE+180d, submission-date window) — the "rolling-recent-window-only" verdict of
2026-08-02 came from querying from=to=QE, which the silent as-on→submission switch had broken.
Depth thins out going back: ~2,100 as-on rows at Sep-2024, 1,800 at Dec-2021, 34 at Sep-2019.

Writes a LEDGER (never shp_history directly — one-writer rule, §22):
scripts/shp_fill_nse_gaps.json.gz, applied fill-only by apply_bse_hist_ledger().

  python3 -X utf8 scripts/fetch_shp_nse_gaps.py --from-qe 2019-09-30
  python3 -X utf8 scripts/fetch_shp_nse_gaps.py --symbols BSE,CDSL
Resumable: cells already in the ledger, and (sym,qe) pairs NSE has no row for, are skipped.
"""
import os, sys, json, gzip, time, argparse, collections
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import fetch_shareholding as FS
import build_fundamentals as B

LEDGER = os.path.join(HERE, "shp_fill_nse_gaps.json.gz")
MISSES = os.path.join(HERE, "_shp_nse_absent.json")
MEMB = os.path.join(HERE, "indices_history.json")
RMAPP = os.path.join(HERE, "_rename_map.json")
RMAP = json.load(open(RMAPP, encoding="utf-8"))


def norm(s):
    s = str(s).strip().upper()
    seen = set()
    while s in RMAP and s not in seen and RMAP[s] != s:
        seen.add(s)
        s = RMAP[s]
    return s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-qe", default="2019-09-30")
    ap.add_argument("--symbols", default="")
    a = ap.parse_args()

    hist = FS.load_hist()
    FS.apply_bse_hist_ledger(hist)
    have = collections.defaultdict(dict)
    keyfor = {}
    for k, v in hist.items():
        if k.startswith("_") or not isinstance(v, dict):
            continue
        n = norm(k)
        have[n].update(v)
        if n not in keyfor or len(v) > len(hist.get(keyfor[n], {})):
            keyfor[n] = k

    ledger = {"_meta": {}, "fills": {}}
    if os.path.exists(LEDGER):
        with gzip.open(LEDGER, "rt", encoding="utf-8") as fh:
            ledger = json.load(fh)
    fills = ledger.setdefault("fills", {})
    absent = set(tuple(x) for x in (json.load(open(MISSES)) if os.path.exists(MISSES) else []))

    ih = json.load(open(MEMB, encoding="utf-8"))
    snaps = sorted((s["effectiveDate"], [norm(x) for x in s["symbols"]
                                         if not str(x).upper().startswith("DUMMY")])
                   for s in ih["Nifty 500"])

    def members(qe):
        best = []
        for ed, syms in snaps:
            if ed <= qe:
                best = syms
            else:
                break
        return best

    only = {norm(s) for s in a.symbols.split(",") if s.strip()} if a.symbols else None
    last = max(q for qs in have.values() for q in qs)
    qes = sorted([q for q in ["%d%s" % (y, suf) for y in range(2016, int(last[:4]) + 1)
                              for suf in ("-03-31", "-06-30", "-09-30", "-12-31")]
                  if a.from_qe <= q <= last], reverse=True)

    gaps = collections.defaultdict(list)
    for qe in qes:
        for s in sorted(set(members(qe))):
            if only and s not in only:
                continue
            if qe in have.get(s, {}) or qe in fills.get(keyfor.get(s, s), {}) or (s, qe) in absent:
                continue
            gaps[qe].append(s)
    total = sum(len(v) for v in gaps.values())
    print("gaps: %d cells over %d quarters" % (total, len(gaps)))
    if not total:
        return

    jar = B.nse_jar()
    got = norow = bad = 0
    new_absent = []
    for qe in qes:
        want = gaps.get(qe)
        if not want:
            continue
        try:
            recs = FS.fetch_master(jar, qe)
        except Exception as e:
            print("  %s master FAILED %r — skipped" % (qe, e)); continue
        best = {}
        for r in recs:
            sym = norm(str(r.get("symbol") or ""))
            sub = FS.iso_date(r.get("submissionDate")) or FS.iso_date(r.get("broadcastDate"))
            xb = str(r.get("xbrl") or "").strip()
            if not sym or not sub or not xb.lower().startswith("http"):
                continue
            if sym not in best or sub >= best[sym][0]:
                best[sym] = (sub, xb)
        for s in want:
            hit = best.get(s)
            if not hit:
                new_absent.append((s, qe)); norow += 1
                print("  %s %-12s no row in NSE's archive" % (qe, s)); continue
            try:
                res = FS.parse_shp(ET.fromstring(FS.fetch_xbrl(hit[1], jar)), qe)
            except Exception as e:
                bad += 1
                print("  %s %-12s fetch/parse err %r" % (qe, s, e)); continue
            if not isinstance(res, dict):
                bad += 1
                print("  %s %-12s parse refused" % (qe, s)); continue
            fills.setdefault(keyfor.get(s, s), {})[qe] = [
                res["prom"], res["fii"], res["dii"], res["mf"], res["ins"],
                hit[0], res.get("nsh"), "nse:%s" % hit[0]]
            got += 1
            print("  %s %-12s fii=%-6s dii=%-6s prom=%-6s nsh=%s" % (qe, s, res["fii"], res["dii"], res["prom"], res.get("nsh")))
        flush(ledger, fills, new_absent, absent)

    print("\nDONE: +%d cells, %d with no NSE row, %d fetch/parse failures" % (got, norow, bad))
    print("ledger: %s (%d symbols, %d cells)"
          % (os.path.basename(LEDGER), len(fills), sum(len(v) for v in fills.values())))


def flush(ledger, fills, new_absent, absent):
    ledger["_meta"] = {"source": "NSE corporate-share-holdings-master XBRL",
                       "built": time.strftime("%Y-%m-%d %H:%M IST"),
                       "symbols": len(fills), "cells": sum(len(v) for v in fills.values())}
    tmp = LEDGER + ".tmp%d" % os.getpid()
    with gzip.open(tmp, "wt", encoding="utf-8") as fh:
        json.dump(ledger, fh, separators=(",", ":"))
    os.replace(tmp, LEDGER)
    if new_absent:
        absent.update(new_absent)
        del new_absent[:]
        json.dump(sorted(absent), open(MISSES, "w"), separators=(",", ":"))


if __name__ == "__main__":
    main()
