# -*- coding: utf-8 -*-
"""Coverage audit: for a target quarter, who DECLARED a result (authoritative NSE+BSE feeds) vs who we
have NUMBERS for (sf_fundamentals.json + bse_fundamentals.json). Prints the gap, bucketed by exchange +
market cap, and writes scripts/_coverage_gap.json with the missing names so the grind can target them.

This is the reliable substitute for scraping Screener's ~215 result pages: the NSE/BSE announcement feeds
ARE the source of truth for "a result was filed", and matching Screener's total count is a sanity check.

DECLARED truth:
  - NSE: `integrated-filing-results` last 120d (current season; symbol + qe) — same call update_fundamentals uses.
  - BSE: `AnnSubCategoryGetData strCat=Result` over the quarter window (scripcode) + our bse_fundamentals
    (catches board-meeting-category filers the Result scan misses).
COVERED:
  - NSE: sf_fundamentals.json[SYM] has the target QE with a non-null value.
  - BSE: bse_fundamentals.json[scrip] has the target QE.

Run: python -X utf8 scripts/coverage_gap.py [--qe YYYYMMDD]   (default = latest quarter in quarterly_results.json)
"""
import os, sys, json, re, time, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_fundamentals as NB
import bse_fetch as B

HERE = os.path.dirname(os.path.abspath(__file__))
DOCS = os.path.join(HERE, "..", "docs")

def load(p, d):
    try: return json.load(open(p, encoding="utf-8"))
    except Exception: return d

def target_qe():
    if "--qe" in sys.argv: return int(sys.argv[sys.argv.index("--qe") + 1])
    qr = load(os.path.join(DOCS, "quarterly_results.json"), {"quarters": [20260630]})
    return int(qr["quarters"][0])

def nse_declared(qe):
    """NSE symbols that filed a result for `qe` (integrated-filing-results, paginated, same call as
    update_fundamentals.py). Window = the ~150 days after quarter-end (when results are filed)."""
    y, m = qe // 10000, (qe // 100) % 100
    lo = datetime.date(y, m, 28)
    hi = min(datetime.date.today(), lo + datetime.timedelta(days=150))
    jar = NB.nse_jar()
    hdr = {"User-Agent": NB.UA, "Accept": "application/json",
           "Referer": "https://www.nseindia.com/companies-listing/corporate-filings-financial-results"}
    base = ("https://www.nseindia.com/api/integrated-filing-results?index=equities&period=Quarterly"
            "&from_date=%s&to_date=%s" % (lo.strftime("%d-%m-%Y"), hi.strftime("%d-%m-%Y")))
    out = set(); page = 1; total = 0
    try:
        while True:
            jb = json.loads(NB._get(base + "&page=%d&size=500" % page, headers=hdr, jar=jar, timeout=60))
            rows = jb if isinstance(jb, list) else (jb.get("data", []) or [])
            MON = {"jan":1,"feb":2,"mar":3,"apr":4,"may":5,"jun":6,"jul":7,"aug":8,"sep":9,"oct":10,"nov":11,"dec":12}
            for r in rows:
                sym = str(r.get("symbol") or "").strip().upper()
                qd = str(r.get("qe_Date") or "")
                m = re.match(r"(\d{1,2})-([A-Za-z]{3})-(\d{4})", qd)   # NSE format: 30-JUN-2026
                if not (sym and m): continue
                qi = int(m.group(3)) * 10000 + MON.get(m.group(2).lower(), 0) * 100 + int(m.group(1))
                if qi != qe: continue
                # match update_fundamentals' filter: only filings with a parseable XBRL P&L (not
                # governance/segment-only) count as "should be covered" — else we overstate the gap.
                if not str(r.get("xbrl") or "").startswith("http"): continue
                if "governance" in (str(r.get("type") or "")).lower(): continue
                out.add(sym)
            if not isinstance(jb, list): total = max(total, jb.get("totalCount") or 0)
            if isinstance(jb, list) or not rows or page > 60: break
            page += 1
    except Exception as ex:
        print("NSE declared fetch ERR:", str(ex)[:80])
    return out

def bse_declared(qe, univ_codes):
    """BSE-only scripcodes that filed a result FOR quarter `qe`. ⚠️ BSE companies file late — a MARCH
    result often lands in Jul/Aug/Sep — so we must read the reporting period from each filing's headline
    (via fetch_bse_results.qe_from_head), NOT assume the filing date maps to the quarter. Headlines that
    don't state a period are counted as `unknown` (returned separately), never silently as `qe`."""
    import fetch_bse_results as FR
    y, m = qe // 10000, (qe // 100) % 100
    lo = datetime.date(y, m, 28)
    hi = min(datetime.date.today(), lo + datetime.timedelta(days=150))
    op = B.session(); time.sleep(1)
    got = set(); unknown = set(); cur = lo
    while cur <= hi:
        chi = min(cur + datetime.timedelta(days=9), hi)
        F, T = cur.strftime("%Y%m%d"), chi.strftime("%Y%m%d")
        page = 1
        while page <= 40:
            url = ("https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w?pageno=%d&strCat=Result"
                   "&strPrevDate=%s&strToDate=%s&strScrip=&strSearch=P&strType=C&subcategory=-1" % (page, F, T))
            try: tab = json.loads(B.get(op, url)).get("Table", []) or []
            except Exception: break
            if not tab: break
            for r in tab:
                sc = str(r.get("SCRIP_CD") or "")
                if sc not in univ_codes: continue
                pq = FR.qe_from_head(r.get("HEADLINE"), r.get("NEWSSUB"))
                if pq == qe: got.add(sc)
                elif pq == 0: unknown.add(sc)     # period not stated in headline
            page += 1; time.sleep(0.15)
        cur = chi + datetime.timedelta(days=1)
    got_codes = got
    unknown -= got_codes                          # a scrip with one dated filing counts as known
    return got_codes, unknown

def main():
    qe = target_qe()
    print("=== Coverage audit for quarter %d ===" % qe)
    sf = load(os.path.join(DOCS, "sf_fundamentals.json"), {})
    bf = load(os.path.join(DOCS, "bse_fundamentals.json"), {"px": {}}).get("px", {})
    univ = {str(r[0]): r for r in load(os.path.join(DOCS, "bse_universe.json"), {"rows": []})["rows"]}

    # covered — sf_fundamentals[SYM] is a LIST of [qe, std, annStd, con, annCon] rows
    def rows_of(qs): return qs if isinstance(qs, list) else list(qs.values())
    nse_cov = set(s for s, qs in sf.items() if any(
        isinstance(row, list) and row and int(row[0]) == qe and len(row) > 1 and
        (row[1] is not None or (len(row) > 3 and row[3] is not None)) for row in rows_of(qs)))
    bse_cov = set(c for c, qs in bf.items() if str(qe) in qs)
    print("COVERED: NSE %d, BSE-only %d" % (len(nse_cov), len(bse_cov)))

    # declared (authoritative) — BSE quarter parsed from each filing's headline (late March filers
    # must NOT be miscounted as the June quarter). `unknown` = filed a result but headline didn't
    # state the period; we grind those too but don't assert they're for `qe`.
    nse_dec = nse_declared(qe)
    bse_dec, bse_unknown = bse_declared(qe, set(univ))
    bse_dec |= set(c for c in bf if str(qe) in bf[c])          # ∪ confirmed odd-category filers for qe
    print("DECLARED for %d: NSE %d, BSE-only %d (+%d BSE undated-period filings)"
          % (qe, len(nse_dec), len(bse_dec), len(bse_unknown)))

    nse_miss = sorted(nse_dec - nse_cov)
    bse_miss = sorted(bse_dec - bse_cov, key=lambda c: -(univ.get(c, [0]*7)[6] or 0))
    print("\nMISSING NSE (declared, no number): %d" % len(nse_miss))
    print("  ", nse_miss[:30])
    print("MISSING BSE-only (declared, no number): %d" % len(bse_miss))
    for c in bse_miss[:30]:
        u = univ.get(c, [c, c, c, "", "", 0, 0, ""])
        print("   %8s %-12s %-34s %8.0f cr" % (c, u[1], u[2][:34], u[6] or 0))

    out = {"qe": qe, "nse_missing": nse_miss,
           "bse_missing": [{"scrip": c, "tkr": univ.get(c, ["","?"])[1], "mcap": univ.get(c, [0]*7)[6]} for c in bse_miss]}
    json.dump(out, open(os.path.join(HERE, "_coverage_gap.json"), "w"), separators=(",", ":"))
    print("\nWrote scripts/_coverage_gap.json (%d NSE + %d BSE-only missing)" % (len(nse_miss), len(bse_miss)))

if __name__ == "__main__":
    main()
