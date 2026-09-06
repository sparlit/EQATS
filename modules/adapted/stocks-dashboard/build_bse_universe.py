# -*- coding: utf-8 -*-
"""Build docs/bse_universe.json — the BSE-ONLY equity universe (stocks listed on BSE but NOT on NSE).

Our core price/fundamentals dataset is NSE-keyed, so ~2,700 BSE-only companies (e.g. Cella Space,
NSDL) never appear in the tool. This file is the backbone for covering them: one row per BSE-only
active-equity scrip with the metadata the pages need (ticker, name, ISIN, group, mcap, sector).

Sources (both bulk, no per-scrip loop for the base list):
- BSE `ListofScripData` — ALL active equity scrips (SCRIP_CD, scrip_id, ISIN, GROUP, FACE_VALUE, Mktcap…).
- NSE `EQUITY_L.csv` — the NSE ISIN set to subtract (BSE-only = ISIN not on NSE).

Sector is enriched per-scrip from BSE `ComHeadernew` (Industry), newest/biggest first, budgeted so a run
stays quick; already-known sectors are cached in scripts/_bse_sectors.json and reused.

Output: {"updated","count", "rows":[[scrip_cd, ticker, name, isin, group, faceval, mcap_cr, sector], …]}
        sorted by market cap desc. Guard: refuses to overwrite a good file with a tiny/failed fetch.

Run: python -X utf8 scripts/build_bse_universe.py [--sector-budget N]
"""
import os, sys, json, io, csv, time, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bse_fetch as B

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "docs", "bse_universe.json")
SEC_CACHE = os.path.join(HERE, "_bse_sectors.json")
NSE_CACHE = os.path.join(HERE, "_nse_universe.json")
MIN_ROWS = 800                      # a broken fetch must never clobber a good universe

def nse_isin_set():
    """NSE equity ISINs (to subtract). Cached; refreshed from EQUITY_L.csv when possible."""
    import build_fundamentals as NB
    jar = NB.nse_jar()
    hdr = {"User-Agent": NB.UA, "Accept": "*/*",
           "Referer": "https://www.nseindia.com/market-data/securities-available-for-trading"}
    for url in ("https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv",
                "https://archives.nseindia.com/content/equities/EQUITY_L.csv"):
        try:
            raw = NB._get(url, headers=hdr, jar=jar, timeout=60)
            isin = set(); syms = set()
            for row in csv.DictReader(io.StringIO(raw)):
                iz = (row.get(" ISIN NUMBER") or row.get("ISIN NUMBER") or "").strip()
                sy = (row.get("SYMBOL") or "").strip()
                if iz: isin.add(iz)
                if sy: syms.add(sy)
            if len(isin) > 1500:
                json.dump({"isin": sorted(isin), "sym": sorted(syms)}, open(NSE_CACHE, "w"))
                return isin
        except Exception as ex:
            print("NSE list fetch failed (%s), trying next/cache" % str(ex)[:60])
    if os.path.exists(NSE_CACHE):
        return set(json.load(open(NSE_CACHE))["isin"])
    raise SystemExit("no NSE ISIN set available")

def bse_active_equity(op):
    r = B.get(op, "https://api.bseindia.com/BseIndiaAPI/api/ListofScripData/w"
                  "?Group=&Scripcode=&industry=&segment=Equity&status=Active")
    return json.loads(r if isinstance(r, str) else r.decode("utf8", "ignore"))

def sector_of(op, code, cache):
    k = str(code)
    if k in cache: return cache[k]
    try:
        r = B.get(op, "https://api.bseindia.com/BseIndiaAPI/api/ComHeadernew/w"
                      "?quotetype=EQ&scripcode=%s&seriesid=" % code)
        j = json.loads(r if isinstance(r, str) else r.decode("utf8", "ignore"))
        sec = (j.get("Industry") or "").strip() or "Other"
    except Exception:
        sec = ""            # leave blank → retry next run
    cache[k] = sec
    return sec

def mcap(x):
    try: return round(float(x.get("Mktcap") or 0), 2)
    except Exception: return 0.0

def main():
    budget = 400
    if "--sector-budget" in sys.argv:
        budget = int(sys.argv[sys.argv.index("--sector-budget") + 1])
    op = B.session(); time.sleep(1)
    nse = nse_isin_set()
    allbse = bse_active_equity(op)
    bse_only = [x for x in allbse if (x.get("ISIN_NUMBER") or "").strip() and
                (x.get("ISIN_NUMBER") or "").strip() not in nse]
    bse_only.sort(key=mcap, reverse=True)
    print("BSE active equity %d; BSE-only %d" % (len(allbse), len(bse_only)))

    cache = json.load(open(SEC_CACHE)) if os.path.exists(SEC_CACHE) else {}
    spent = 0
    rows = []
    for x in bse_only:
        code = x["SCRIP_CD"]
        sec = cache.get(str(code), "")
        if not sec and spent < budget and mcap(x) > 0:   # enrich biggest-first within budget
            sec = sector_of(op, code, cache); spent += 1
            if spent % 50 == 0:
                json.dump(cache, open(SEC_CACHE, "w")); time.sleep(0.2)
        try: fv = round(float(x.get("FACE_VALUE") or 0), 2)
        except Exception: fv = 0
        rows.append([int(code), (x.get("scrip_id") or "").strip().upper(),
                     (x.get("Scrip_Name") or "").strip(), (x.get("ISIN_NUMBER") or "").strip(),
                     (x.get("GROUP") or "").strip(), fv, mcap(x), sec])
    json.dump(cache, open(SEC_CACHE, "w"))

    if len(rows) < MIN_ROWS and os.path.exists(OUT):
        raise SystemExit("ABORT: only %d rows — keeping existing bse_universe.json" % len(rows))

    ist = datetime.datetime.utcnow() + datetime.timedelta(hours=5, minutes=30)
    out = {"updated": ist.strftime("%Y-%m-%d %H:%M IST"), "count": len(rows),
           "sectors_known": sum(1 for r in rows if r[7]), "rows": rows}
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    print("WROTE %s: %d BSE-only stocks (%d with sector; +%d sectors this run)"
          % (os.path.normpath(OUT), len(rows), out["sectors_known"], spent))

if __name__ == "__main__":
    main()
