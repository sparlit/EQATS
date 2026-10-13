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


#!/usr/bin/env python3
"""§164r — our-side fixes from Quantmac's reply v4 (28-Sep-2026; ~/stocks-cache/shp/quantmac/v4). One stage per finding,
each writing proposals {"SYM|DATE": {was, cell, src, why}} for scripts/_shp_164_write.py (quarter keys) or
scripts/_shp_164q_events.py write (event keys). Every amount is read from the company's own filing for that quarter.

  zensar <out.json>   ZENSARTECH Mar-2009..Sep-2015: the §160 hand-off had moved the page's Overseas Corporate Bodies row
                      (10,301,294 shares) into FII under the name "Marina Holdco (FPI) Ltd"; the company's own >1% table
                      names that block "Electra Partners Mauritius Ltd" for those quarters (qtrid 61-87) and "Marina Holdco
                      (FPI) Ltd" only from Dec-2015. No FPI mark and no document proving Electra a foreign institution ->
                      the block leaves FII (to public; DII untouched). Jun-2006..Dec-2008 the company filed it on the Foreign
                      Venture Capital Investors row -> FII by its own mark, unchanged.
  anndates-fetch       every Nifty 500 (current + former) quarterly row from Mar-2014 dated > 21 days after its quarter-end:
                       BSE's announcement stream for [quarter-end + 1, our date] (AnnSubCategoryGetData, honest bse_headers,
                       every page, ~1 s apart), cached in ~/stocks-cache/shp/v4work/ann
  anndates-decide <out.json>   the EARLIEST "Shareholding for the Period Ended <that quarter-end>" announcement earlier than
                       our date -> a shp_lag_fix days_earlier entry (calendar day, midnight rule). BSE's SHP list row "New"
                       dated later = BSE's XBRL copy uploaded after the filing (BAJFINANCE Mar-2019: announced 13-Apr-2019,
                       list 16-May-2019). A quarter BSE keeps ONLY as a revision moves only when Quantmac's independent
                       reading of the original at a month-end in [announcement, our date) equals our FII (§164b rule).
  table3 <out.json>    Mar-2016 quarters whose BSE page hides FII in a lump (held in §164l / retracted in §156): BSE's own filed
                       Table III (api Corp_shpSec_SHPPubShold_ng, qtrid 89 — copies supplied by Quantmac with sha256, 11 companies)
                       read with the SAME rules as the 2015-22 XBRL quarters: FPI/FVCI rows = FII; MF/VCF/AIF/banks/insurance/
                       pension = DII; the institutional Any-Other row by its labelled sub-rows (count > 0) or, without labels, by its
                       named holders (shared classifier + proof file) with the unnamed rest = FII unless every named holder is
                       Indian (D1); unproven named holders stay in DII (raw placement); NBFC row = DII (R3); domestic-institution
                       labels/holders parked in non-institutions = DII (R2); a foreign-institution label filed in non-institutions
                       = FII; a named non-institution holder = FII only when the filer's own 2022-form filing lists it under
                       Institutions (Foreign) (R2-FII); Overseas Depositories = neither (§151). Denominator = the page's total.
                       A quarter naming a holder of UNPROVEN class is held (§164j keeps such holders as stored; a fresh quarter
                       has nothing stored): VRLLOG (NSR-PE Mauritius LLC).
  nsefill              the NSE SHP XBRLs Quantmac supplied (40, sha256 in their manifest; NSE's master API is locked to us): each
                       read by parse_shp, keyed by the file's OWN DateOfReport (EIHOTEL prints 2010-10-20 for its 20-Oct-2020 upload:
                       mistyped year -> the upload day), identity = the file's Symbol, visible from the calendar day of NSE's upload
                       stamp in the file name. Mid-quarter rows -> scripts/shp_event_fills.json (fill-only, fetch_shareholding.
                       apply_event_fills); quarter-end rows -> shp_fill_n500_gaps.json.gz (fill-only). The §164q runner then gives
                       them the same row-level rules (it reads each row's own file).
  wb-fetch             pre-2014 filing times: BSE's retired page shareholding/searchresult.asp?scripcd=<code> listed every SHP filing
                       with 'For Quarter Ending | Date & Time' (e.g. NAGPUR POWER Dec-2011: Thursday, February 02, 2012 4:26:30 PM).
                       Wayback holds 7,577 captures (2002-2012; 4,593 in 2008; 253 scrips have one from 2010+). The LATEST capture
                       per scrip lists every filing up to that day. One capture per Nifty 500 (current + former) scrip, raw (id_),
                       ~1.5 s apart, cached in ~/stocks-cache/shp/v4work/wb.
  wb-decide <out.json> a store row dated only by the qe+21 convention (served UN-DATED today) gets a shp_sub_dates entry = the
                       CALENDAR day of that filing time (midnight rule §149), when the capture's company name matches ours.
  vstind <out.json>    VSTIND Dec-2016: the filing lists "Matthews India Fund 7.68" on the institutional Other axis while that block
                       totals 0.12 (the fund sits in the FPI row), so R1 hit its overflow guard and dropped the whole evaluation —
                       including the 0.12 row the filer LABELS "Foreign Institutional Investors" (counted in Sep-2016 and Mar-2017).
                       That labelled row moves dii -> fii (Quantmac 9.7557).
"""
import glob
import gzip
import html
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
C = os.path.expanduser("~/stocks-cache/shp")
PAGE_DIRS = [
    os.path.join(C, d)
    for d in (
        "dii_session/aspx_pages",
        "w164n/aspx_pages",
        "w164o/aspx_pages",
        "seambase/pages",
        "seambase/fa/cache",
    )
]
PERENT_DIRS = [
    os.path.join(C, d)
    for d in ("dii_session/shpperent", "seamholes/shpperent", "seambase/fa/shpperent")
]


def qtrid(qe):
    y = int(qe[:4])
    m = int(qe[5:7])
    return (y - 2001) * 4 + {3: 29, 6: 30, 9: 31, 12: 32}[m]


def _rows(t):
    out = []
    for r in re.findall(r"<tr[^>]*>(.*?)</tr>", t, re.S | re.I):
        c = [
            html.unescape(re.sub(r"<[^>]+>", "", x)).strip()
            for x in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", r, re.S | re.I)
        ]
        c = [x for x in c if x]
        if c:
            out.append(c)
    return out


def _read(dirs, code, q):
    for d in dirs:
        for p in sorted(glob.glob(os.path.join(d, "%s_%d*.html.gz" % (code, q)))):
            return gzip.open(p).read().decode("utf8", "replace"), p
    return None, None


def _num(x):
    try:
        return float(str(x).replace(",", ""))
    except Exception:
        return None


def zensar(out):
    code, sym = 504067, "ZENSARTECH"
    hist = json.load(open(os.path.join(HERE, "shp_history.json")))[sym]
    P = {}
    for qe in sorted(hist):
        if not ("2009-03-31" <= qe <= "2015-09-30"):
            continue
        q = qtrid(qe)
        t, p = _read(PAGE_DIRS, code, q)
        pe, pp = _read(PERENT_DIRS, code, q)
        if not t or not pe:
            print(f"  {qe}: page or >1% table missing — skipped")
            continue
        ocb = [r for r in _rows(t) if r[0].startswith("Overseas Corporate Bodies") and len(r) > 2]
        tot = [r for r in _rows(t) if r[0].startswith("Total (A)+(B)+(C)") and len(r) > 2]
        names = [r for r in _rows(pe) if r and r[0].isdigit() and len(r) > 2]
        if len(ocb) != 1 or not tot:
            print(f"  {qe}: OCB row / total not unique on the page — skipped")
            continue
        sh, T = _num(ocb[0][2]), _num(tot[-1][2])
        # the whole OCB row moved in §160; it is Electra's block (+ a 10-share second OCB in Mar-2009..Jun-2010), none of it
        # FPI-marked: the quarter's table must name Electra inside the row and must not name the later Marina Holdco (FPI)
        holder = [
            r[1]
            for r in names
            if re.search(r"electra partners mauritius", r[1], re.I)
            and (_num(r[2]) or 0) <= sh
            and (_num(r[2]) or 0) >= 0.999 * sh
        ]
        if not holder or any(re.search(r"marina holdco", r[1], re.I) for r in names):
            print(
                f"  {qe}: the OCB row is not Electra Partners Mauritius' block on this quarter's table — skipped"
            )
            continue
        amt = round(sh / T * 100, 4)
        cur = hist[qe]
        new = list(cur)
        new[1] = round(cur[1] - amt, 4)
        if new[1] < -0.005:
            print(f"  {qe}: fii would go negative — skipped")
            continue
        P[f"{sym}|{qe}"] = {
            "was": cur,
            "cell": new,
            "src": "bseaspx:%d:%d + shpperent" % (code, q),
            "why": (
                "§164r ZENSARTECH (2026-09-28, Quantmac v4): the page's Overseas Corporate Bodies row ({} shares of {} = {:.4f}%) "
                'is "{}" in the company\'s own >1% table for this quarter, under a non-institution row and with no FPI mark; '
                'the "Marina Holdco (FPI) Ltd" name (and its FPI mark) appears only from Dec-2015, and no document proves '
                "Electra a foreign institution -> the block leaves FII (public; DII unchanged). The §160 hand-off had carried "
                "the later name back. fii {:.2f} -> {:.2f}."
            ).format(f"{sh:,.0f}", f"{T:,.0f}", amt, holder[0], cur[1], new[1]),
            "ocb_shares": sh,
            "total_shares": T,
        }
        print(f"  {qe} fii {cur[1]:.4f} -> {new[1]:.4f} (Electra {amt:.4f})")
    json.dump(P, open(out, "w"), indent=1, ensure_ascii=False)
    print("zensar: %d proposals" % len(P))


W = os.path.join(C, "v4work")
ANN = os.path.join(W, "ann")
LISTS = (
    os.path.join(C, "ev164q", "lists_all")
    if os.path.isdir(os.path.join(C, "ev164q", "lists_all"))
    else os.path.join(C, "bse_all")
)
MON_Q = {"March": 3, "June": 6, "September": 9, "December": 12}
MONTHS = [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]


def _scope():
    sc = json.load(open(os.path.join(C, "w164n_d1", "exmember_scope.json")))
    return set(sc["current"]) | set(sc["ex"])


def _fa():
    import fetch_shareholding as F

    return getattr(F, "FUND_ALIAS", None) or json.load(
        open(os.path.join(C, "quantmac", "fund_alias.json"))
    )


def _list(sym):
    p = os.path.join(LISTS, sym + ".json")
    if not os.path.exists(p):
        return None
    t = json.load(open(p))
    return t.get("Table") if isinstance(t, dict) else t


def _code(rows):
    for r in rows or []:
        f = (r.get("XbrlFile") or "").strip()
        if f:
            return f.split("_")[0]
    for r in rows or []:
        m = re.search(r"/(\d{6})/", str(r.get("navigateurl", "")))
        if m:
            return m.group(1)


def _late(max_lag=21):
    """(sym, qe, served date, lag): the SERVED visibility date (docs/shp_engine.json, after the lag / sub-date ledgers are
    re-asserted; the original row when a quarter also carries a re-filing row) — not the store's raw sub."""
    from datetime import date

    eng = json.load(open(os.path.join(os.path.dirname(HERE), "docs", "shp_engine.json")))
    sc = _scope()
    fa = _fa()
    out = []
    for sym, rows in eng.items():
        if not (sym in sc or fa.get(sym) in sc):
            continue
        by = {}
        for r in rows:
            if r[0] % 10000 in (331, 630, 930, 1231) and r[0] >= 20140331 and r[3] != 99999999:
                by[r[0]] = min(by.get(r[0], 99999999), r[3])
        for q, sub in by.items():
            qd = date(q // 10000, q // 100 % 100, q % 100)
            sd = date(sub // 10000, sub // 100 % 100, sub % 100)
            if (sd - qd).days > max_lag:
                out.append((sym, qd.isoformat(), sd.isoformat(), (sd - qd).days))
    return sorted(out)


def anndates_fetch(items=None):
    import time
    import urllib.request
    from datetime import date, timedelta

    os.makedirs(ANN, exist_ok=True)
    items = items if items is not None else _late()
    n = ok = bad = 0
    t0 = time.time()
    for sym, qe, sub, _lag in items:
        rows = _list(sym) or _list(_fa().get(sym) or "")
        code = _code(rows)
        if not code:
            continue
        p = os.path.join(ANN, f"{code}_{qe}.json")
        if os.path.exists(p):
            continue
        a = date.fromisoformat(qe) + timedelta(days=1)
        b = min(date.fromisoformat(sub), a + timedelta(days=360))
        got, page, _err = [], 1, None
        while page <= 20:
            u = (
                "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w?pageno=%d&strCat=-1&strPrevDate=%s&strToDate=%s"
                "&strScrip=%s&strSearch=P&strType=C&subcategory=-1"
                % (page, a.strftime("%Y%m%d"), b.strftime("%Y%m%d"), code)
            )
            body = None
            for att in range(3):
                try:
                    body = urllib.request.urlopen(urllib.request.Request(u), timeout=60).read()
                    break
                except Exception as e:
                    repr(e)
                    time.sleep(4 * (att + 1))
            time.sleep(1.0)
            if body is None:
                break
            d = json.loads(body)
            T = d.get("Table") or []
            got += T
            total = ((d.get("Table1") or [{}])[0] or {}).get("ROWCNT")
            if not T or (total is not None and len(got) >= int(total)) or len(T) < 50:
                break
            page += 1
        if body is None:
            bad += 1
            continue
        json.dump(
            {
                "sym": sym,
                "qe": qe,
                "sub": sub,
                "code": code,
                "window": [a.isoformat(), b.isoformat()],
                "rows": got,
            },
            open(p, "w"),
        )
        ok += 1
        n += 1
        if n % 50 == 0:
            print(
                "  %d/%d fetched ok %d bad %d %.0fs" % (n, len(items), ok, bad, time.time() - t0),
                flush=True,
            )
    print("ANN FETCH DONE ok %d bad %d (of %d late quarters)" % (ok, bad, len(items)), flush=True)


def _period_rx(qe):
    y, m, d = int(qe[:4]), int(qe[5:7]), int(qe[8:10])
    mn = MONTHS[m - 1]
    alts = [
        r"%s\s+%d,?\s+%d" % (mn, d, y),
        r"%s\s+%s,?\s+%d" % (mn[:3], d, y),
        r"%d(st|nd|rd|th)?\s+%s,?\s+%d" % (d, mn, y),
        r"%d(st|nd|rd|th)?\s+%s,?\s+%d" % (d, mn[:3], y),
        r"%02d[./-]%02d[./-]%d" % (d, m, y),
        r"%s\s*,?\s*%d\b(?!\d)" % (mn, y) if False else r"(?!x)x",
    ]
    return re.compile("|".join(alts), re.I)


def anndates_decide(out):
    import pickle
    from datetime import date

    hist = json.load(open(os.path.join(HERE, "shp_history.json")))
    lag_led = json.load(open(os.path.join(HERE, "shp_lag_fix.json")))
    qm = {}
    qp = os.path.join(C, "quantmac", "v4", "v4_cells.pkl")
    if os.path.exists(qp):
        for r in pickle.load(open(qp, "rb"))["rows"]:
            if r and hasattr(r[0], "year") and r[3] is not None:
                qm[(r[1], int(r[0].strftime("%Y%m%d")))] = r[3]
    P, st = {}, {}

    def bump(k):
        st[k] = st.get(k, 0) + 1

    for f in sorted(glob.glob(os.path.join(ANN, "*.json"))):
        d = json.load(open(f))
        sym, qe, sub = d["sym"], d["qe"], d["sub"]
        cur = (hist.get(sym) or {}).get(qe)
        if not cur:
            bump("no store row")
            continue
        rx = _period_rx(qe)
        hits = []
        for r in d["rows"]:
            txt = " ".join(str(r.get(k) or "") for k in ("NEWSSUB", "HEADLINE"))
            if re.search(
                r"share\s*holding\s+(pattern\s+)?for\s+the\s+(period|quarter)\s+ended|submitted\s+to\s+bse\s+the\s+share\s*holding\s+pattern",
                txt,
                re.I,
            ) and rx.search(
                txt
            ):  # BSE's own SHP announcement wording only (not SAST / Reg-30 disclosures)
                ts = (r.get("NEWS_DT") or r.get("DT_TM") or "")[:19]
                if ts:
                    hits.append((ts, txt[:120], r.get("ATTACHMENTNAME")))
        if not hits:
            bump("no announcement of that quarter in the window")
            continue
        ts, txt, att = min(hits)
        day = int(ts[:10].replace("-", ""))
        if not (
            int(qe.replace("-", ""))
            < day
            <= int(
                (date.fromisoformat(qe) + __import__("datetime").timedelta(days=400)).strftime(
                    "%Y%m%d"
                )
            )
        ):
            bump("announcement outside [quarter-end, +400 d]")
            continue
        subi = int(sub.replace("-", ""))
        if day >= subi:
            bump("announcement not earlier than our date")
            continue
        st_sub = (
            int(str(cur[5]).replace("-", ""))
            if re.match(r"\d{4}-\d\d-\d\d$", str(cur[5]))
            else None
        )
        if (
            st_sub and day >= st_sub
        ):  # the filing's own stored day is already as early: the served date is a
            bump("stored filing day already as early (served later by the holiday/weekend shift)")
            continue  # non-trading-day shift (§142c), not a lag

        rows = _list(sym) or _list(_fa().get(sym) or "") or []
        qrows = [
            r
            for r in rows
            if (
                lambda x: (
                    len(x) == 2
                    and x[0] in MON_Q
                    and "%s-%02d-%02d" % (x[1], MON_Q[x[0]], 31 if MON_Q[x[0]] in (3, 12) else 30)
                    == qe
                )
            )((r.get("qtr") or "").split())
        ]
        rev_only = bool(qrows) and not any(r.get("filing_date_time") for r in qrows)
        ev = ""
        if rev_only:
            mes = [m for (s_, m), v in qm.items() if s_ == sym and day <= m < subi]
            eq = [m for m in mes if abs(qm[(sym, m)] - (cur[1] or 0)) <= 0.05]
            if not mes or len(eq) != len(mes):
                bump("revision-only: no independent reading of the original equal to our FII")
                continue
            ev = "; §164b rule: BSE keeps only the revision, and Quantmac's reading of the original at {} equals our FII {:.2f} (values stay the revision's)".format(
                ", ".join(str(m) for m in eq), cur[1]
            )
            bump("revision-only, moved on Quantmac's equal reading")
        else:
            bump("moved")
        key = "{}|{}".format(sym, qe.replace("-", ""))
        ent = {
            "days_earlier": (
                date.fromisoformat(sub) - date(day // 10000, day // 100 % 100, day % 100)
            ).days,
            "gated_1530": False,
            "prov": (
                "bse:AnnSubCategoryGetData NEWS_DT of the filing ('{}'); BSE's SHP list {} later (XBRL copy); CALENDAR day "
                "(midnight rule §149); §164r 2026-09-28 (Quantmac v4){}"
            ).format(txt[:90], "keeps only the revision," if rev_only else "row is dated", ev),
            "src": "new",
            "sub": day,
            "ts": ts,
            "was": int(str(cur[5]).replace("-", "")) if isinstance(cur[5], str) else subi,
            "served_before": subi,
            "rule": "midnight-2026-09-23",
            "attachment": att,
        }
        if key in lag_led:
            ent["replaced"] = lag_led[key]
        P[key] = ent
    json.dump(P, open(out, "w"), indent=1, ensure_ascii=False)
    print("anndates-decide:", st, "-> %d entries" % len(P))


DOCS = os.path.join(C, "quantmac", "v4", "docs", "files")


def table3(out):
    # _shp_aspx_rowfix chdirs to DII_ROWFIX_WORK at import and reads its cached generic_rows.json there: use the seam work dir
    os.environ["DII_ROWFIX_WORK"] = os.path.join(C, "seamholes")
    os.environ.setdefault("DII_ROWFIX_LISTS", LISTS)
    os.makedirs(os.path.join(C, "seamholes", "xbrl_bse"), exist_ok=True)
    import _shp_aspx_rowfix as A
    import _shp_dii_rowfix as D

    verdicts = D.load_verdicts()
    hist = json.load(open(os.path.join(HERE, "shp_history.json")))
    P = {}
    for f in sorted(glob.glob(os.path.join(DOCS, "*_2016-03-31_BSE_TABLE3_*.json"))):
        sym = os.path.basename(f).split("_")[0]
        code = os.path.basename(f).split("_")[4]
        if (hist.get(sym) or {}).get("2016-03-31"):
            print(f"  {sym}: store already holds Mar-2016 — skipped")
            continue
        pg = glob.glob(os.path.join(DOCS, f"{sym}_2016-03-31_BSE_SHP_ASPX_89_New.html"))
        if not pg:
            print(f"  {sym}: no page")
            continue
        R = _rows(open(pg[0], encoding="utf8", errors="replace").read())
        tot = [r for r in R if r[0].startswith("Total (A)+(B)+(C)") and len(r) > 2]
        prom = [r for r in R if r[0].startswith("Total shareholding of Promoter") and len(r) > 2]
        if not tot or not prom:
            print(f"  {sym}: page total/promoter missing")
            continue
        T = _num(tot[-1][2])
        PR = _num(prom[0][2])
        t = json.load(open(f))["Table1"]
        stb = [r for r in t if r["Fld_Code"] == "STB1B2B3"]
        if stb and stb[0]["Fld_TotalPercentageOf_A_B_C2"]:
            chk = stb[0]["Fld_TotalNoOfShares"] / T * 100
            if abs(chk - stb[0]["Fld_TotalPercentageOf_A_B_C2"]) > 0.02:
                print(
                    "  {}: page total does not reproduce the table's % ({:.3f} vs {:.2f}) — held".format(
                        sym, chk, stb[0]["Fld_TotalPercentageOf_A_B_C2"]
                    )
                )
                continue

        def pct(sh):
            return (sh or 0) / T * 100

        cat = [
            r
            for r in t
            if not r["Fld_ShareHolderName"] and r["Fld_Code"] and not r["Fld_Code"].startswith("ST")
        ]
        subs = [r for r in t if r["Fld_ShareHolderName"]]

        def total(code):
            return sum(r["Fld_TotalNoOfShares"] or 0 for r in cat if r["Fld_Code"] == code)

        fii_sh = total("B1d") + total("B1e")
        dii_sh = sum(total(c) for c in ("B1a", "B1b", "B1c", "B1f", "B1g", "B1h"))
        ev = []
        mf_sh = total("B1a")
        ins_sh = total("B1g")
        ctx = D.SymCtx(sym, _list(sym) or [], verdicts)
        # institutional Any-Other (B1i)
        Ti = total("B1i")
        lab = [r for r in subs if r["Fld_Code"] == "B1i" and (r["Fld_NoOfShareHolders"] or 0) > 0]
        nam = [r for r in subs if r["Fld_Code"] == "B1i" and not (r["Fld_NoOfShareHolders"] or 0)]
        if Ti:
            if lab and abs(sum(r["Fld_TotalNoOfShares"] or 0 for r in lab) - Ti) <= max(
                1, 0.0005 * Ti
            ):
                for r in lab:
                    k = A.label_class(r["Fld_ShareHolderName"])
                    sh = r["Fld_TotalNoOfShares"] or 0
                    if k is None and re.search(
                        r"foreign\s+ins\w*t\w*\s+invest", r["Fld_ShareHolderName"], re.I
                    ):
                        k = "fii"  # the filer's misspelt label (ARVIND 'Foreign Instutional Investors')
                    if k == "fii":
                        fii_sh += sh
                    elif k == "pub":
                        pass
                    else:
                        dii_sh += sh
                    ev.append(
                        (
                            "B1i-label",
                            r["Fld_ShareHolderName"],
                            round(pct(sh), 4),
                            k or "unresolved->dii",
                        )
                    )
            else:
                named = 0
                cls = []
                for r in nam:
                    c, dest, src = ctx.hclass(
                        r["Fld_ShareHolderName"], pct(r["Fld_TotalNoOfShares"])
                    )
                    sh = r["Fld_TotalNoOfShares"] or 0
                    named += sh
                    cls.append(c)
                    if c == "foreign" and dest == "fii":
                        fii_sh += sh
                    elif c == "foreign" and dest == "public":
                        pass
                    else:
                        dii_sh += sh
                    ev.append(
                        (
                            "B1i-named",
                            r["Fld_ShareHolderName"],
                            round(pct(sh), 4),
                            f"{c}/{dest} {src}",
                        )
                    )
                rest = Ti - named
                if rest > 0:
                    to = "dii" if (cls and all(c == "domestic" for c in cls)) else "fii"
                    if to == "fii":
                        fii_sh += rest
                    else:
                        dii_sh += rest
                    ev.append(("B1i-unnamed-rest", "D1", round(pct(rest), 4), to))
        dii_sh += total("B3b")
        ev.append(("B3b-NBFC", "R3", round(pct(total("B3b")), 4), "dii")) if total("B3b") else None
        for r in [r for r in subs if r["Fld_Code"] == "B3e"]:
            sh = r["Fld_TotalNoOfShares"] or 0
            nm = r["Fld_ShareHolderName"]
            if (r["Fld_NoOfShareHolders"] or 0) > 0:
                k = A.label_class(nm)
                if k == "fii":
                    fii_sh += sh
                    ev.append(("B3e-label", nm, round(pct(sh), 4), "fii"))
                elif k == "dii":
                    dii_sh += sh
                    ev.append(("B3e-label", nm, round(pct(sh), 4), "dii (R2)"))
            else:
                c, dest, src = ctx.hclass(nm, pct(sh))
                if c == "foreign" and dest == "fii" and src.startswith("new-format"):
                    fii_sh += sh
                    ev.append(("B3e-named", nm, round(pct(sh), 4), f"fii (R2-FII, {src})"))
                elif c == "domestic" and re.search(
                    r"insurance|assurance|solvency|mutual fund|provident|pension|\bLIC\b|alternat",
                    nm,
                    re.I,
                ):
                    dii_sh += sh
                    ev.append(("B3e-named", nm, round(pct(sh), 4), f"dii (R2, {src})"))
        unp = [e for e in ev if e[0] == "B1i-named" and str(e[3]).startswith("None/")]
        if unp:
            print(
                "  %-10s HELD: named holder(s) of unproven class %s — §164j keeps such holders where the store has them, and a "
                "fresh quarter has no stored placement to keep" % (sym, [(e[1], e[2]) for e in unp])
            )
            continue
        cell = [
            round(PR / T * 100, 4),
            round(pct(fii_sh), 4),
            round(pct(dii_sh), 4),
            round(pct(mf_sh), 4),
            round(pct(ins_sh), 4),
            "2016-04-21",
        ]
        P[f"{sym}|2016-03-31"] = {
            "cell": cell,
            "src": f"bsetable3:{code}:89 (BSE Corp_shpSec_SHPPubShold_ng, copy supplied by Quantmac 2026-09-27) + bseaspx:{code}:89",
            "denominator": T,
            "ev": ev,
        }
        print(
            "  %-10s prom %.2f fii %.4f dii %.4f | %s"
            % (
                sym,
                cell[0],
                cell[1],
                cell[2],
                "; ".join(f"{e[0]} {str(e[1])[:28]} {e[2]:.2f} {e[3]}" for e in ev)[:400],
            )
        )
    json.dump(P, open(out, "w"), indent=1, ensure_ascii=False)
    print("table3: %d cells" % len(P))


def t3_compute(sym, qe, t, page, ctx, D, A, base=None):
    """base: None = the page total must reproduce the table's %; "page" = the company reports on the FULL share count and the
    table's % leaves its depository-receipt block out (UFLEX Dec-2015) -> divide by the page's (A)+(B)+(C); "table" = the page
    total does not belong to this table (VAIBHAVGBL Mar-2016: page 28.6 M shares vs the table's 32.5 M) -> the table's own
    base, promoter = 100 - public %."""
    import _shp_d1_rowfix as D1

    """One Dec-2015 / Mar-2016 quarter from BSE's Table III JSON + the same quarter's BSE page (total (A)+(B)+(C) and the promoter
    row), read with the XBRL-era rules exactly as `table3` does. -> (cell5, ev, T) or (None, reason, None)."""
    R = _rows(page)
    tot = [r for r in R if r[0].startswith("Total (A)+(B)+(C)") and len(r) > 2]
    prom = [r for r in R if r[0].startswith("Total shareholding of Promoter") and len(r) > 2]
    if not tot or not prom:
        return None, "page total/promoter missing", None
    T = _num(tot[-1][2])
    PR = _num(prom[0][2])
    stb = [r for r in t if r["Fld_Code"] == "STB1B2B3"]
    if stb and stb[0]["Fld_TotalPercentageOf_A_B_C2"]:
        chk = stb[0]["Fld_TotalNoOfShares"] / T * 100
        if base == "table":
            T = stb[0]["Fld_TotalNoOfShares"] / stb[0]["Fld_TotalPercentageOf_A_B_C2"] * 100
            PR = T * (100 - stb[0]["Fld_TotalPercentageOf_A_B_C2"]) / 100
        elif base == "page":
            if chk >= stb[0]["Fld_TotalPercentageOf_A_B_C2"]:
                return None, "page base is not the larger (full) count", None
        elif abs(chk - stb[0]["Fld_TotalPercentageOf_A_B_C2"]) > 0.02:
            return (
                None,
                "page total does not reproduce the table's % ({:.3f} vs {:.2f})".format(
                    chk, stb[0]["Fld_TotalPercentageOf_A_B_C2"]
                ),
                None,
            )

    def pct(sh):
        return (sh or 0) / T * 100

    cat = [
        r
        for r in t
        if not r["Fld_ShareHolderName"] and r["Fld_Code"] and not r["Fld_Code"].startswith("ST")
    ]
    subs = [r for r in t if r["Fld_ShareHolderName"]]

    def total(code):
        return sum(r["Fld_TotalNoOfShares"] or 0 for r in cat if r["Fld_Code"] == code)

    fii_sh = total("B1d") + total("B1e")
    dii_sh = sum(total(c) for c in ("B1a", "B1b", "B1c", "B1f", "B1g", "B1h"))
    ev = []
    mf_sh = total("B1a")
    ins_sh = total("B1g")
    # Institutional Any-Other (B1i). A sub-row is a LABEL only when its text is a category the classifier knows (incl. the
    # misspelt 'Fil (foriegn Institutional Investor)'); any other text is a HOLDER, whatever its holder count (SHREECEM Dec-2015
    # 'FLT LIMITED' carries a count of 1; BERGEPAINT's 'Naianda India Fund Ltd' is a misspelt fund, not a category). Holders take
    # the shared classifier (documents / the filer's own 2022-form placement); the unnamed rest follows D1 with the
    # neighbouring-filing gate (§164r batch 5).
    FTOL = re.compile(r"f(?:or|ro)(?:ei|ie|e)gn\s+ins\w*t\w*\s+inv", re.I)
    COMP = re.compile(
        r"^\W*(?:non[\s-]*)?domestic\s+compan", re.I
    )  # company-type category, like 'Foreign Companies'
    Ti = total("B1i")
    rows_i = [r for r in subs if r["Fld_Code"] == "B1i"]

    def klass(r):
        nm = r["Fld_ShareHolderName"]
        k = (
            A.label_class(nm)
            or ("fii" if FTOL.search(nm) else None)
            or ("pub" if COMP.search(nm) else None)
        )
        if (r["Fld_NoOfShareHolders"] or 0) > 0:
            return k  # a category row: its text decides; unknown text = a holder
        return (
            k if k == "fii" else None
        )  # a name cell holding an FII label ('OTHER FII'); any other name is a holder
        # ('THE NOMURA TRUST AND BANKING' is not the Trusts category)

    labs = [(r, klass(r)) for r in rows_i if klass(r)]
    hold = [r for r in rows_i if not klass(r)]
    if Ti:
        full = labs and abs(sum(r["Fld_TotalNoOfShares"] or 0 for r, _ in labs) - Ti) <= max(
            1, 0.0005 * Ti
        )
        covered = 0
        cls = []
        for r, k in labs:
            sh = r["Fld_TotalNoOfShares"] or 0
            covered += sh
            if k == "fii":
                fii_sh += sh
            elif k == "pub":
                pass
            else:
                dii_sh += sh
            ev.append(("B1i-label", r["Fld_ShareHolderName"], round(pct(sh), 4), k))
        if not full:
            for r in hold:
                c, dest, src = ctx.hclass(r["Fld_ShareHolderName"], pct(r["Fld_TotalNoOfShares"]))
                sh = r["Fld_TotalNoOfShares"] or 0
                covered += sh
                cls.append(c)
                if c == "foreign" and dest == "fii":
                    fii_sh += sh
                elif c == "foreign" and dest == "public":
                    pass
                else:
                    dii_sh += sh
                ev.append(
                    ("B1i-named", r["Fld_ShareHolderName"], round(pct(sh), 4), f"{c}/{dest} {src}")
                )
            rest = Ti - covered
            if rest > 0:
                to = "dii" if (cls and all(c == "domestic" for c in cls)) else "fii"
                if to == "fii" and pct(rest) >= D1.D1_GATE_MIN:
                    ok, why_g = D1.d1_corroborated(sym, qe, pct(fii_sh + rest), pct(rest))
                    if not ok:
                        to = "dii"
                        ev.append(("B1i-rest-gate", "D1 held", round(pct(rest), 4), why_g))
                if to == "fii":
                    fii_sh += rest
                else:
                    dii_sh += rest
                ev.append(("B1i-unnamed-rest", "D1", round(pct(rest), 4), to))
    dii_sh += total("B3b")
    if total("B3b"):
        ev.append(("B3b-NBFC", "R3", round(pct(total("B3b")), 4), "dii"))
    for r in [r for r in subs if r["Fld_Code"] == "B3e"]:
        sh = r["Fld_TotalNoOfShares"] or 0
        nm = r["Fld_ShareHolderName"]
        if (r["Fld_NoOfShareHolders"] or 0) > 0:
            k = A.label_class(nm)
            if k == "fii":
                fii_sh += sh
                ev.append(("B3e-label", nm, round(pct(sh), 4), "fii"))
            elif k == "dii":
                dii_sh += sh
                ev.append(("B3e-label", nm, round(pct(sh), 4), "dii (R2)"))
        else:
            c, dest, src = ctx.hclass(nm, pct(sh))
            if c == "foreign" and dest == "fii" and src.startswith("new-format"):
                fii_sh += sh
                ev.append(("B3e-named", nm, round(pct(sh), 4), f"fii (R2-FII, {src})"))
            elif c == "domestic" and re.search(
                r"insurance|assurance|solvency|mutual fund|provident|pension|\bLIC\b|alternat",
                nm,
                re.I,
            ):
                dii_sh += sh
                ev.append(("B3e-named", nm, round(pct(sh), 4), f"dii (R2, {src})"))
    unp = [e for e in ev if e[0] == "B1i-named" and str(e[3]).startswith("None/")]
    if unp:
        return None, "named holder(s) of unproven class %s" % [(e[1], e[2]) for e in unp], None
    return (
        [
            round(PR / T * 100, 4),
            round(pct(fii_sh), 4),
            round(pct(dii_sh), 4),
            round(pct(mf_sh), 4),
            round(pct(ins_sh), 4),
        ],
        ev,
        T,
    )


def t3fix(keys, out):
    """Batch 6: Dec-2015 / Mar-2016 cells we hold from third-party or page-seam fills, re-read from BSE's own Table III
    (api Corp_shpSec_SHPPubShold_ng/w?SCRIPCODE=<code>&QtrCode=<qtrid>.00 - Quantmac's v5 gave the parameter names) + the page."""
    import time

    import bse_headers as BH

    os.environ["DII_ROWFIX_WORK"] = os.path.join(C, "seamholes")
    os.environ.setdefault("DII_ROWFIX_LISTS", LISTS)
    import _shp_aspx_rowfix as A
    import _shp_dii_rowfix as D

    verdicts = D.load_verdicts()
    hist = json.load(open(os.path.join(HERE, "shp_history.json")))
    cache = os.path.join(W, "t3")
    os.makedirs(cache, exist_ok=True)
    P = {}

    def get(u, p):
        if os.path.exists(p):
            return open(p, "rb").read()
        for a in range(3):
            r = BH.get(u, timeout=60)
            time.sleep(1.0)
            if r.status_code == 200 and len(r.content) > 500:
                open(p, "wb").write(r.content)
                return r.content
            time.sleep(10 * (a + 1))
        return None

    for key in keys:
        base = None
        code_ov = None
        parts = key.split("|")
        for extra in parts[2:]:
            if extra.startswith("code="):
                code_ov = extra[5:]
            elif extra:
                base = extra
        key = "|".join(parts[:2])
        sym, qe = key.split("|")
        qi = qtrid(qe)
        cur = (hist.get(sym) or {}).get(qe)
        code = code_ov or _code(_list(sym) or _list(_fa().get(sym) or "") or [])
        if not code or not cur:
            print(f"  {key}: no code / no store row")
            continue
        tj = get(
            "https://api.bseindia.com/BseIndiaAPI/api/Corp_shpSec_SHPPubShold_ng/w?SCRIPCODE=%s&QtrCode=%d.00"
            % (code, qi),
            os.path.join(cache, "%s_%d_t3.json" % (code, qi)),
        )
        pg = get(
            "https://www.bseindia.com/corporates/ShareholdingPattern.aspx?scripcd=%s&flag_qtr=1&qtrid=%d.00&Flag=New"
            % (code, qi),
            os.path.join(cache, "%s_%d_page.html" % (code, qi)),
        )
        if not tj or not pg:
            print(f"  {key}: fetch failed")
            continue
        t = json.loads(tj).get("Table1") or []
        if not t:
            print(f"  {key}: empty Table III")
            continue
        ctx = D.SymCtx(sym, _list(sym) or [], verdicts)
        cell, ev, T = t3_compute(sym, qe, t, pg.decode("utf-8", "ignore"), ctx, D, A, base)
        if cell is None:
            print("  %-12s HELD: %s" % (key, ev))
            continue
        new = list(cur)
        new[:5] = cell
        P[key] = {
            "was": cur,
            "cell": new,
            "src": "bsetable3:%s:%d + bseaspx:%s:%d" % (code, qi, code, qi),
            "ev": ev,
            "denominator": T,
            "why": (
                "§164r batch 6 (Quantmac v5): read from BSE's own Table III of this filing (Corp_shpSec_SHPPubShold_ng, "
                "QtrCode %d) and the quarter's BSE page total, with the XBRL-era rules; the stored cell came from %s. "
                "fii %.2f -> %.2f, dii %.2f -> %.2f. Rows: %s"
            )
            % (
                qi,
                "a third-party / page-seam fill",
                cur[1] or 0,
                cell[1],
                cur[2] or 0,
                cell[2],
                "; ".join(f"{e[0]} {str(e[1])[:40]} {e[2]:.2f} {e[3]}" for e in ev)[:500],
            ),
        }
        print(
            "  %-12s fii %.2f -> %.2f dii %.2f -> %.2f | %s"
            % (
                key,
                cur[1] or 0,
                cell[1],
                cur[2] or 0,
                cell[2],
                "; ".join(f"{e[0]} {str(e[1])[:24]} {e[2]:.2f} {e[3]}" for e in ev)[:300],
            )
        )
    json.dump(P, open(out, "w"), indent=1, ensure_ascii=False)
    print("t3fix: %d proposals" % len(P))


def nsefill():
    from datetime import date

    import fetch_shareholding as F

    fa = _fa()
    hist = json.load(open(os.path.join(HERE, "shp_history.json")))
    ev = F.load_events()
    ep = os.path.join(HERE, "shp_event_fills.json")
    led = (
        json.load(open(ep, encoding="utf-8"))
        if os.path.exists(ep)
        else {
            "_doc": [
                "§164r (2026-09-28): EVENT rows read from exchange documents the NSE fetch cannot reach (NSE's master API is locked).",
                "fetch_shareholding.apply_event_fills adds a row only where the symbol has none at that as-on date (fill-only, a fetched",
                "filing always wins); cell_fix / shp_event_redate / revisions then treat it like any fetched row. Row = [prom, fii, dii,",
                "mf, ins, visible-from (calendar day of the NSE upload stamp in the file name), holders, source].",
            ],
            "fills": {},
        }
    )
    gp = os.path.join(HERE, "shp_fill_n500_gaps.json.gz")
    graw = gzip.open(gp, "rt", encoding="utf-8").read()
    gled = json.loads(graw)
    ne = nq = 0
    for f in sorted(glob.glob(os.path.join(DOCS, "*_NSE_XBRL_*.xml"))):
        b = os.path.basename(f)
        sym = b.split("_")[0]
        t = open(f, "rb").read()
        m = re.search(r"(SHP_\d+_\d+_(\d{14})_WEB\.xml)$", b)
        fn, st = m.group(1), m.group(2)
        vis = f"{st[4:8]}-{st[2:4]}-{st[0:2]}"
        dr = re.search(rb"DateOfReport[^>]*>([^<]+)<", t)
        xs = re.search(rb"<[^>]*:Symbol[^>]*>([^<]+)<", t)
        d = dr.group(1).decode().strip() if dr else None
        xsym = xs.group(1).decode().strip() if xs else None
        if not xsym or not (xsym == sym or fa.get(xsym) == sym or fa.get(sym) == xsym):
            print(f"  {b}: symbol {xsym} — held")
            continue
        why_d = ""
        if d and not (0 <= (date.fromisoformat(vis) - date.fromisoformat(d)).days <= 60):
            why_d = f"; the file's DateOfReport {d} is not within 60 days before its upload (mistyped) -> keyed by the upload day"
            d = vis
        if not d:
            print(f"  {b}: no DateOfReport — held")
            continue
        r = F.parse_shp(t, d)
        if not r:
            print(f"  {b}: parse_shp found no anchored categories — held")
            continue
        src = f"nse:{fn} (copy supplied by Quantmac 2026-09-27; NSE upload stamp {st}{why_d})"
        row = [r["prom"], r["fii"], r["dii"], r.get("mf"), r.get("ins"), vis, r.get("nsh"), src]
        if d[5:] in ("03-31", "06-30", "09-30", "12-31"):
            if d in (hist.get(sym) or {}) or d in (gled["fills"].get(sym) or {}):
                print(f"  {sym} {d}: quarter already held — nothing to add")
                continue
            gled["fills"].setdefault(sym, {})[d] = row
            nq += 1
        else:
            if d in (ev.get(sym) or {}):
                print(f"  {sym} {d}: event already held")
                continue
            led["fills"].setdefault(sym, {})[d] = row
            ne += 1
    json.dump(led, open(ep, "w", encoding="utf-8"), indent=1, ensure_ascii=False, sort_keys=True)
    gled.setdefault("_meta", {})["note_164r"] = (
        "2026-09-28 §164r: quarter-end NSE XBRLs supplied by Quantmac (GFLLIMITED/MONSANTO Mar-2019), visible from the NSE upload stamp day"
    )
    with gzip.open(gp, "wt", encoding="utf-8") as fh:
        fh.write(json.dumps(gled, separators=(",", ":"), ensure_ascii=True))
    print("nsefill: %d event rows, %d quarter rows" % (ne, nq))


def table3_write(path):
    """p_table3 cells -> scripts/shp_fill_seam_aspx.json.gz (fill-only; the ledger's own layout = json.dumps defaults)."""
    P = json.load(open(path))
    hist = json.load(open(os.path.join(HERE, "shp_history.json")))
    p = os.path.join(HERE, "shp_fill_seam_aspx.json.gz")
    led = json.loads(gzip.open(p, "rt", encoding="utf-8").read())
    fills = led.setdefault("fills", {})
    n = skip = 0
    for k, v in P.items():
        sym, qe = k.split("|")
        if qe in (hist.get(sym) or {}) or qe in (fills.get(sym) or {}):
            skip += 1
            continue
        fills.setdefault(sym, {})[qe] = list(v["cell"]) + [
            None,
            v["src"]
            + " | §164r "
            + "; ".join(f"{e[0]} {str(e[1])[:40]} {e[2]:.2f} {e[3]}" for e in v["ev"])[:600],
        ]
        n += 1
    led["_built"] = (
        str(led.get("_built", "")) + " | §164r 2026-09-28 Mar-2016 BSE Table III (%d)" % n
    )
    with gzip.open(p, "wt", encoding="utf-8") as fh:
        fh.write(json.dumps(led))
    print("table3-write: %d cells added, %d skipped" % (n, skip))


WB = os.path.join(W, "wb")


def wb_fetch():
    import time
    import urllib.error
    import urllib.request

    rows = json.load(open(os.path.join(WB, "cdx_searchresult.json")))
    latest = {}
    for ts, orig, _st, _ln in rows:
        m = re.search(r"scripcd=(\d{6})", orig)
        if m and (m.group(1) not in latest or ts > latest[m.group(1)][0]):
            latest[m.group(1)] = (ts, orig)
    sc = _scope()
    fa = _fa()
    hist = json.load(open(os.path.join(HERE, "shp_history.json")))
    want = {}
    for sym in hist:
        if sym.startswith("_") or not (sym in sc or fa.get(sym) in sc):
            continue
        code = _code(_list(sym) or _list(fa.get(sym) or "") or [])
        if code and code in latest:
            want[code] = sym
    UA = {"User-Agent": "stocks-dashboard-research/1.0 (personal research)"}
    # The archive refuses connections for minutes when paced at 1.5 s (measured 28-Sep 09:05) -> 4 s pace, and a refusal /
    # 429 / 5xx waits 3-10 min and retries the SAME page (a transient is never counted as a missing page). Every page that
    # still fails is written with its reason to wb/_fail.json — no silent skip.
    PACE, fails = 4.0, {}
    fp = os.path.join(WB, "_fail.json")
    ok = bad = 0
    for i, (code, sym) in enumerate(sorted(want.items())):
        ts, orig = latest[code]
        p = os.path.join(WB, f"{code}_{ts}.html")
        if os.path.exists(p):
            continue
        u = f"https://web.archive.org/web/{ts}id_/{orig}"
        b = b""
        why = ""
        for a in range(5):
            try:
                b = urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=90).read()
                why = ""
                break
            except urllib.error.HTTPError as e:
                why = "HTTP %d" % e.code
                if e.code in (404, 403):
                    break
            except Exception as e:
                why = repr(e)[:120]
            wait = min(600, 180 * (a + 1))
            print("    %s %s -> wait %ds" % (code, why, wait), flush=True)
            time.sleep(wait)
        time.sleep(PACE)
        if b"For Quarter Ending" in b or b"Quarter Ended" in b:
            open(p, "wb").write(b)
            ok += 1
            fails.pop(code, None)  # 2008+ / 2007 layout
        else:
            bad += 1
            fails[code] = {
                "sym": sym,
                "ts": ts,
                "why": why or ("no filing table (%d bytes)" % len(b)),
            }
            json.dump(fails, open(fp, "w"), indent=0)
        if i % 50 == 0:
            print("  %d/%d ok %d bad %d" % (i, len(want), ok, bad), flush=True)
    print(
        "WB FETCH DONE ok %d bad %d (of %d scope scrips with a capture)" % (ok, bad, len(want)),
        flush=True,
    )


def lag_write(path, ledger="shp_lag_fix.json"):
    """Merge a decide-stage proposal file into scripts/<ledger> (flat {SYM|YYYYMMDD: entry}). An existing entry for the
    key is kept under `replaced` (the decision that superseded it stays auditable)."""
    P = json.load(open(path))
    lp = os.path.join(HERE, ledger)
    raw = open(lp, encoding="utf-8").read()
    led = json.loads(raw)
    n_new = n_rep = 0
    for k, v in sorted(P.items()):
        ent = dict(v)
        if k in led:
            if led[k] == v:
                continue
            ent["replaced"] = led[k]
            n_rep += 1
        else:
            n_new += 1
        led[k] = ent
    compact = raw.lstrip().startswith(
        '{"'
    )  # shp_sub_dates.json is one line; shp_lag_fix.json is indent=0
    txt = json.dumps(
        led,
        ensure_ascii=("\\u00" in raw) or not any(ord(ch) > 127 for ch in raw),
        **({"separators": (",", ":")} if compact else {"indent": 0}),
    )
    open(lp, "w", encoding="utf-8").write(txt + ("\n" if raw.endswith("\n") else ""))
    print("%s: %d new, %d replaced (kept under 'replaced')" % (ledger, n_new, n_rep))


DR7 = ["ADVANTA", "DCW", "KGL", "ORIENTHOT", "PAISALO", "ROLTA", "STERLINBIO"]


def drrebase(out):
    """§164a (D2) for the 7 companies it missed: each one's own first 2015-form XBRL prints Promoter + Public = 100 with the
    depository-receipt custodian OUTSIDE the 100 (reply #4 d2_basis.json), so its pre-2016 cells read on the page's
    % of (A+B+C) column move onto (A+B): all five slots x total(A+B+C)/total(A+B) shares from the SAME quarter's BSE page.
    Same parse and per-cell basis test as scripts/_shp_164a_dr_rebase.py (promoter row, else mutual-fund row, decides
    which column the stored cell was read on). Pages: www.bseindia.com ShareholdingPattern.aspx via bse_headers (honest)."""
    import gzip
    import time

    import bse_headers as BH

    b2 = json.load(open(os.path.join(C, "reply4", "d2_basis.json")))
    hist = json.load(open(os.path.join(HERE, "shp_history.json")))
    cache = os.path.join(W, "aspx_dr")
    os.makedirs(cache, exist_ok=True)
    NUM = r"\s+(\d+)\s+(\d+)\s+(\d+)\s+([\d.]+)\s+([\d.]+)"

    def page(c, qi):
        for pth in (
            os.path.join(cache, "%d_%d.html.gz" % (c, qi)),
            os.path.join(C, "seambase", "pages", "%d_%d.html.gz" % (c, qi)),
        ):
            if os.path.exists(pth):
                return gzip.open(pth, "rt", encoding="utf-8", errors="ignore").read()
        u = (
            "https://www.bseindia.com/corporates/ShareholdingPattern.aspx?scripcd=%d&flag_qtr=1&qtrid=%d.00&Flag=New"
            % (c, qi)
        )
        for a in range(3):
            r = BH.get(u, timeout=60)
            time.sleep(1.0)
            if r.status_code == 200 and len(r.content) > 3000:
                txt = r.content.decode("utf-8", "ignore")
                with gzip.open(
                    os.path.join(cache, "%d_%d.html.gz" % (c, qi)), "wt", encoding="utf-8"
                ) as fh:
                    fh.write(txt)
                return txt
            if r.status_code in (403, 429, 500, 502, 503):
                time.sleep(30 * (a + 1))
                continue
            return None
        return None

    def parse(txt):
        t = re.sub(r"\s+", " ", re.sub(r"<[^>]*>", " ", txt).replace("&nbsp;", " "))

        def g(m):
            return (int(m.group(2)), float(m.group(4)), float(m.group(5))) if m else None

        m1 = re.search(r"Total \(A\)\+\(B\)" + NUM, t)
        m2 = re.search(r"Total \(A\)\+\(B\)\+\(C\)" + NUM, t)
        if not (m1 and m2):
            return None
        return {
            "ab": g(m1),
            "abc": g(m2),
            "prom": g(
                re.search(r"Total shareholding of Promoter and Promoter Group \(A\)" + NUM, t)
            ),
            "mf": g(re.search(r"Mutual Funds */ *UTI" + NUM, t)),
        }

    P, st = {}, {}
    for sym in DR7:
        c = int(b2[sym]["file"].split("_")[0])
        for q in sorted(hist.get(sym, {})):
            if q > "2016-03-31" or q < "2001-03-31":
                continue
            cell = hist[sym][q]
            key = sym + "|" + q
            txt = page(c, qtrid(q))
            if not txt:
                st[key] = "no page"
                continue
            p = parse(txt)
            if not p:
                st[key] = "page unparsed / new format"
                continue
            ab, abc = p["ab"][0], p["abc"][0]
            if abc <= ab:
                st[key] = "no custodian shares this quarter"
                continue
            f = abc / ab
            if p["prom"] and p["prom"][2] > 0.5:
                ref, stored = p["prom"], cell[0]
            elif p["mf"] and p["mf"][2] > 0.3 and cell[3] is not None:
                ref, stored = p["mf"], cell[3]
            else:
                st[key] = "no reference row"
                continue
            dAB, dABC = abs(stored - ref[1]), abs(stored - ref[2])
            if dAB + 0.02 < dABC:
                st[key] = "already on (A+B)"
                continue
            if dABC > 0.06:
                st[key] = "stored reference matches neither column"
                continue
            new = list(cell)
            for i in range(5):
                if isinstance(new[i], (int, float)):
                    new[i] = round(new[i] * f, 4)
            P[key] = {
                "was": cell,
                "cell": new,
                "src": "bseaspx:%d_%d" % (c, qtrid(q)),
                "why": (
                    "§164a depository-receipt basis (§164r 2026-09-28, the 7 companies §164a missed; found by the Quantmac v4 "
                    "reply build): this company's own first XBRL (%s) prints Promoter + Public = 100 with the custodian (shares "
                    "underlying ADRs/GDRs) OUTSIDE the 100, so its pre-2016 page values move from the page's %% of (A+B+C) column "
                    "onto (A+B): all slots x %.6f = total (A+B+C) %d shares / (A+B) %d shares on the same quarter's BSE page; "
                    "fii %.2f -> %.2f."
                )
                % (b2[sym]["file"], f, abc, ab, cell[1] or 0, new[1] or 0),
            }
            st[key] = "REBASE"
    import collections

    print(collections.Counter(v for v in st.values()))
    print(collections.Counter(k.split("|")[0] for k in P))
    json.dump(P, open(out, "w"), indent=1, ensure_ascii=False)


def d1gate(path):
    """Option A (user 2026-09-28): write the D1 corroboration gate (scripts/_shp_d1_rowfix.d1_corroborated) onto the cells it
    already moved. For each recorded unnamed-remainder move >= 1 pp that neither neighbouring filing supports, ONLY the D1
    amount returns to dii (other rules' moves in the same entry stay); the prior entry is kept under `superseded`, the audit
    entry is updated in place (d1 -> 0, d1_held, d1_gate) so the runner's chain reading stays valid."""
    import _shp_d1_rowfix as D1
    import fetch_shareholding as F

    cands = json.load(open(path))
    hist = json.load(open(os.path.join(HERE, "shp_history.json")))
    ev = F.load_events()
    lp = os.path.join(HERE, "shp_cell_fix.json")
    raw = open(lp, encoding="utf-8").read()
    led = json.loads(raw)
    fix = led["fix"]
    ap = os.path.join(HERE, "_shp_164_audit.json")
    araw = open(ap, encoding="utf-8").read()
    aud = json.loads(araw)
    cells = aud.get("cells", aud)
    n = 0
    skip = []
    for c in cands:
        sym, d = c["key"].split("|")
        d1 = float(c["d1"])
        cur = (ev.get(sym) or {}).get(d) if c["event"] else (hist.get(sym) or {}).get(d)
        prior = (fix.get(sym) or {}).get(d)
        if cur is None or not prior or not F._cell_eq(cur, prior.get("cell")):
            skip.append((c["key"], "store moved"))
            continue
        ok, why_g = D1.d1_corroborated(sym, d, cur[1], d1)
        if ok:
            skip.append((c["key"], "corroborated now"))
            continue
        new = list(cur)
        new[1] = round(cur[1] - d1, 4)
        new[2] = round((cur[2] or 0) + d1, 4)
        why = (
            f"{D1.MARK} — D1 corroboration gate (§164r batch 5, user 2026-09-28 'Option A ... do this'): the unnamed Other-Institutions "
            f"remainder D1 had moved to FII ({d1:.2f} pp) goes back to DII: neither of the company's neighbouring filings shows a foreign "
            f"holding that size ({why_g}). Only the D1 amount moves; fii {cur[1]:.2f} -> {new[1]:.2f}, dii {cur[2] or 0:.2f} -> {new[2]:.2f}."
        )
        fix[sym][d] = {
            "cell": new,
            "was": list(cur),
            "src": prior.get("src"),
            "why": why,
            "superseded": prior,
        }
        a = cells.setdefault(c["key"], {})
        a["d1_held"] = d1
        a["d1"] = 0.0
        a["d1_gate"] = why_g
        a["parts"] = [x for x in (a.get("parts") or []) if not x.startswith("D1 unnamed")] + [
            "D1 held: not corroborated (§164r batch 5)"
        ]
        n += 1
    json.dump(led, open(lp, "w", encoding="utf-8"), indent=1, ensure_ascii=("\\u00" in raw))
    json.dump(aud, open(ap, "w", encoding="utf-8"), indent=0, ensure_ascii=("\\u00" in araw))
    print("d1gate: %d written, skipped %s" % (n, skip))


def lag_revert(path, ledger="shp_lag_fix.json"):
    """Undo batch-2 re-dates for the keys in <path> (a JSON list whose items start with the key): restore the entry each one
    replaced (kept under `replaced`), else remove the key. Same format-preserving writer as lag_write."""
    keys = [x[0] if isinstance(x, list) else x for x in json.load(open(path))]
    lp = os.path.join(HERE, ledger)
    raw = open(lp, encoding="utf-8").read()
    led = json.loads(raw)
    rest = rem = miss = 0
    for k in keys:
        e = led.get(k)
        if not e or "§164r" not in str(e.get("prov", "")):
            miss += 1
            continue
        if isinstance(e.get("replaced"), dict):
            led[k] = e["replaced"]
            rest += 1
        else:
            del led[k]
            rem += 1
    compact = raw.lstrip().startswith('{"')
    txt = json.dumps(
        led,
        ensure_ascii=("\\u00" in raw) or not any(ord(ch) > 127 for ch in raw),
        **({"separators": (",", ":")} if compact else {"indent": 0}),
    )
    open(lp, "w", encoding="utf-8").write(txt + ("\n" if raw.endswith("\n") else ""))
    print(
        "%s: %d restored to the replaced entry, %d removed, %d not a §164r entry"
        % (ledger, rest, rem, miss)
    )


def _undated_items():
    """In-scope quarters Mar-2014..Mar-2016 the engine still serves UN-DATED (fallback quarter-end + 28): window quarter-end ->
    + 150 days for the company's first SHP announcement."""
    from datetime import date, timedelta

    keys = json.load(open(os.path.join(W, "undated_2014_16.json")))
    return [
        (
            s,
            "%d-%02d-%02d" % (q // 10000, q // 100 % 100, q % 100),
            (date(q // 10000, q // 100 % 100, q % 100) + timedelta(days=150)).isoformat(),
            0,
        )
        for s, q in keys
    ]


def undated_decide(out):
    """Batch 6d (Quantmac v5 'you serve a quarter-end + 28 estimate, its real filing is later'): date the un-dated 2014..Mar-2016
    quarters from the company's first 'Shareholding for the Period Ended' announcement. LATER than the + 28 fallback -> always
    served from the announcement (removes look-ahead). EARLIER -> only for an XBRL-era quarter (Dec-2015 / Mar-2016) whose BSE list
    shows ONE version, never revised, whose parse equals our stored promoter + MF (the announced filing IS our figures); page-era
    quarters keep the fallback when the announcement is earlier (the page shows the latest version; a revision's figures must not be
    served from the first filing's day - batch 6b)."""
    from datetime import date, timedelta

    import fetch_shareholding as F

    hist = json.load(open(os.path.join(HERE, "shp_history.json")))
    sub_led = json.load(open(os.path.join(HERE, "shp_sub_dates.json"), encoding="utf-8"))
    P, st = {}, {}

    def bump(k):
        st[k] = st.get(k, 0) + 1

    MONQ = {"March": 3, "June": 6, "September": 9, "December": 12}
    for sym, qe, _, _ in _undated_items():
        rows = _list(sym) or _list(_fa().get(sym) or "")
        code = _code(rows)
        k = sym if sym in hist else _fa().get(sym, sym)
        cur = (hist.get(k) or {}).get(qe)
        if not code or not cur:
            bump("no code / no store row")
            continue
        pth = os.path.join(ANN, f"{code}_{qe}.json")
        if not os.path.exists(pth):
            bump("not fetched")
            continue
        d = json.load(open(pth))
        rx = _period_rx(qe)
        hits = []
        for r in d["rows"]:
            txt = " ".join(str(r.get(x) or "") for x in ("NEWSSUB", "HEADLINE"))
            if re.search(
                r"share\s*holding\s+(pattern\s+)?for\s+the\s+(period|quarter)\s+ended|submitted\s+to\s+bse\s+the\s+share\s*holding\s+pattern",
                txt,
                re.I,
            ) and rx.search(txt):
                ts = (r.get("NEWS_DT") or r.get("DT_TM") or "")[:19]
                if ts:
                    hits.append((ts, txt[:120]))
        if not hits:
            bump("no SHP announcement in the window")
            continue
        ts, txt = min(hits)
        day = int(ts[:10].replace("-", ""))
        qd = date.fromisoformat(qe)
        fb = int((qd + timedelta(days=28)).strftime("%Y%m%d"))
        conv = int((qd + timedelta(days=21)).strftime("%Y%m%d"))
        key = "{}|{}".format(k, qe.replace("-", ""))
        if key in sub_led:
            bump("sub_dates entry exists")
            continue
        stored = (
            int(str(cur[5]).replace("-", ""))
            if re.match(r"\d{4}-\d\d-\d\d$", str(cur[5]))
            else None
        )
        if stored != conv:
            bump("stored date is not the + 21 convention (served un-dated for another reason)")
            continue
        if day > fb:
            why = "later than the + 28 fallback"
        else:
            if qe < "2015-12-31":
                bump("earlier than fallback, page era: held (revision unknown)")
                continue
            vers = [
                r
                for r in rows
                if (
                    lambda x: (
                        len(x) == 2
                        and x[0] in MONQ
                        and "%s-%02d-%02d" % (x[1], MONQ[x[0]], 31 if MONQ[x[0]] in (3, 12) else 30)
                        == qe
                    )
                )((r.get("qtr") or "").split())
            ]
            if (
                len(vers) != 1
                or vers[0].get("revised_date_time")
                or not (vers[0].get("XbrlFile") or "").strip()
            ):
                bump("earlier than fallback, BSE lists a revision / no single version: held")
                continue
            import _shp_dii_rowfix as D

            f = vers[0]["XbrlFile"].strip()
            fp = D.find_file(f)
            if not fp:
                bump("earlier than fallback, version file not cached: held")
                continue
            raw = open(fp, "rb").read()
            raw = __import__("gzip").decompress(raw) if fp.endswith(".gz") else raw
            pr = F.parse_shp(raw.decode("utf-8", "ignore"), qe)
            if (
                not pr
                or abs((pr.get("prom") or 0) - (cur[0] or 0)) > 0.02
                or abs((pr.get("mf") or 0) - (cur[3] or 0)) > 0.02
            ):
                bump("earlier than fallback, the single version's figures differ from ours: held")
                continue
            why = f"earlier than the fallback; BSE lists one never-revised version ({f}) whose promoter/MF equal ours"
        P[key] = {
            "gated_1530": False,
            "prov": f"bse:AnnSubCategoryGetData NEWS_DT of the company's first SHP announcement ('{txt[:90]}'); {why}; CALENDAR day (midnight rule §149); §164r batch 6d 2026-09-29 (Quantmac v5)",
            "src": "bse-ann",
            "sub": day,
            "ts": ts.replace(" ", "T"),
            "was": stored,
            "rule": "midnight-2026-09-23",
        }
        bump("dated (%s)" % ("later" if day > fb else "earlier"))
    json.dump(P, open(out, "w"), indent=1, ensure_ascii=False)
    print("undated-decide:", st, "-> %d entries" % len(P))


def wb_older():
    """Pages whose NEWEST capture holds no filing table (BSE's own 'Error Code:404' page archived with HTTP 200 once the
    page was retired — HINDPETRO 2012-10-02) fall back to that scrip's earlier captures, newest first, up to 4 tries."""
    import time
    import urllib.error
    import urllib.request

    fp = os.path.join(WB, "_fail.json")
    fails = json.load(open(fp))
    rows = json.load(open(os.path.join(WB, "cdx_searchresult.json")))
    caps = {}
    for ts, orig, st, _ln in rows:
        m = re.search(r"scripcd=(\d{6})", orig)
        if m and st == "200":
            caps.setdefault(m.group(1), []).append((ts, orig))
    UA = {"User-Agent": "stocks-dashboard-research/1.0 (personal research)"}
    ok = 0
    for code, f in sorted(fails.items()):
        if not f["why"].startswith("no filing table"):
            continue
        tried = []
        for ts, orig in sorted(caps.get(code, []), reverse=True):
            if ts >= f["ts"] or len(tried) >= 4:
                continue
            p = os.path.join(WB, f"{code}_{ts}.html")
            b = b""
            for a in range(5):
                try:
                    b = urllib.request.urlopen(
                        urllib.request.Request(
                            "https://web.archive.org/web/{}id_/{}".format(
                                ts, orig.replace("&amp", "")
                            ),
                            headers=UA,
                        ),
                        timeout=90,
                    ).read()
                    break
                except urllib.error.HTTPError as e:
                    if e.code in (404, 403):
                        break
                    time.sleep(min(600, 180 * (a + 1)))
                except Exception:
                    time.sleep(min(600, 180 * (a + 1)))
            time.sleep(4.0)
            tried.append(ts)
            if b"For Quarter Ending" in b or b"Quarter Ended" in b:
                open(p, "wb").write(b)
                f["why"] = "newest capture {} has no table; used {}".format(f["ts"], ts)
                f["ok"] = ts
                ok += 1
                break
        else:
            f["tried"] = tried
        json.dump(fails, open(fp, "w"), indent=0)
    print(
        "WB OLDER DONE %d recovered of %d"
        % (ok, sum(1 for f in fails.values() if f["why"].startswith(("no filing", "newest")))),
        flush=True,
    )


def wb_early(path):
    """For every quarter whose latest capture shows a date > qe+45, fetch the scrip's EARLIEST capture taken >= 25 days
    after that quarter-end (and before the latest one): if the quarter was filed on time, that capture lists the
    original date. Same pacing / back-off as wb-fetch."""
    import time
    import urllib.error
    import urllib.request
    from datetime import date, timedelta

    P = json.load(open(path))
    rows = json.load(open(os.path.join(WB, "cdx_searchresult.json")))
    caps = {}
    for ts, orig, st, _ln in rows:
        m = re.search(r"scripcd=(\d{6})", orig)
        if m and st == "200":
            caps.setdefault(m.group(1), []).append((ts, orig.replace("&amp", "")))
    have = {}
    for f in glob.glob(os.path.join(WB, "*.html")):
        c, t = os.path.basename(f)[:-5].split("_")
        have.setdefault(c, set()).add(t)
    _scope()
    fa = _fa()
    code_of = {}
    want = set()
    for k, v in P.items():
        sym, q = k.split("|")
        qd = date(int(q[:4]), int(q[4:6]), int(q[6:]))
        if (date(v["sub"] // 10000, v["sub"] // 100 % 100, v["sub"] % 100) - qd).days <= 45:
            continue
        code = code_of.get(sym) or _code(_list(sym) or _list(fa.get(sym) or "") or [])
        code_of[sym] = code
        if not code:
            continue
        lo = (qd + timedelta(days=25)).strftime("%Y%m%d")
        latest = max(t for t, _ in caps.get(code, [("0", "")]))
        cand = sorted((t, o) for t, o in caps.get(code, []) if lo <= t[:8] and t < latest)
        if cand and cand[0][0] not in have.get(code, set()):
            want.add((code, cand[0][0], cand[0][1]))
    print("wb-early: %d captures to fetch" % len(want), flush=True)
    UA = {"User-Agent": "stocks-dashboard-research/1.0 (personal research)"}
    ok = bad = 0
    for i, (code, ts, orig) in enumerate(sorted(want)):
        p = os.path.join(WB, f"{code}_{ts}.html")
        b = b""
        for a in range(5):
            try:
                b = urllib.request.urlopen(
                    urllib.request.Request(
                        f"https://web.archive.org/web/{ts}id_/{orig}", headers=UA
                    ),
                    timeout=90,
                ).read()
                break
            except urllib.error.HTTPError as e:
                if e.code in (404, 403):
                    break
                time.sleep(min(600, 180 * (a + 1)))
            except Exception:
                time.sleep(min(600, 180 * (a + 1)))
        time.sleep(4.0)
        if b"For Quarter Ending" in b or b"Quarter Ended" in b:
            open(p, "wb").write(b)
            ok += 1
        else:
            bad += 1
        if i % 25 == 0:
            print("  %d/%d ok %d bad %d" % (i, len(want), ok, bad), flush=True)
    print("WB EARLY DONE ok %d bad %d" % (ok, bad), flush=True)


def wb_decide(out):
    import difflib
    from datetime import date, datetime, timedelta

    hist = json.load(open(os.path.join(HERE, "shp_history.json")))
    names = hist.get("_names") or {}
    sub_led = json.load(open(os.path.join(HERE, "shp_sub_dates.json"), encoding="utf-8"))
    sc = _scope()
    fa = _fa()
    code2 = {}
    for sym in hist:
        if sym.startswith("_") or not (sym in sc or fa.get(sym) in sc):
            continue
        code = _code(_list(sym) or _list(fa.get(sym) or "") or [])
        if code:
            code2.setdefault(code, []).append(sym)
    MONQ = {"March": 3, "June": 6, "September": 9, "December": 12}

    def norm(x):
        return re.sub(r"[^a-z]", "", (x or "").lower().replace("limited", "").replace("ltd", ""))

    P, st = {}, {}

    def bump(k):
        st[k] = st.get(k, 0) + 1

    for f in sorted(glob.glob(os.path.join(WB, "*.html"))):
        code, ts = os.path.basename(f)[:-5].split("_")
        t = open(f, encoding="utf8", errors="replace").read()
        R = _rows(t)
        title = next(
            (r[0] for r in R if re.search(r"(LTD|LIMITED)\.?$", r[0], re.I) and len(r) == 1), ""
        )
        for sym in code2.get(code, []):
            nm = names.get(sym, sym)
            if (
                title
                and difflib.SequenceMatcher(None, norm(title), norm(nm)).ratio() < 0.6
                and norm(title)[:6] != norm(nm)[:6]
            ):
                bump("name mismatch (held)")
                continue
            for r in R:
                if len(r) != 2:
                    continue
                lab = re.sub(
                    r"^\s*Quarter\s+Ended\s+", "", r[0], flags=re.I
                ).split()  # 2007 layout: 'Quarter Ended March 2007'
                if len(lab) != 2 or lab[0] not in MONQ or not lab[1].isdigit():
                    continue
                mo = MONQ[lab[0]]
                y = int(lab[1])
                qe = "%d-%02d-%02d" % (y, mo, 31 if mo in (3, 12) else 30)
                try:
                    dt = datetime.strptime(
                        re.sub(r"\s+", " ", r[1].replace("\xa0", " ")).strip(),
                        "%A, %B %d, %Y %I:%M:%S %p",
                    )
                except ValueError:
                    bump("unparsed time")
                    continue
                cell = (hist.get(sym) or {}).get(qe)
                if not cell or qe > "2016-03-31":
                    continue
                sub = str(cell[5])
                subi = int(sub.replace("-", "")) if re.match(r"\d{4}-\d\d-\d\d$", sub) else None
                conv = subi == int((date.fromisoformat(qe) + timedelta(days=21)).strftime("%Y%m%d"))
                key = "{}|{}".format(sym, qe.replace("-", ""))
                if not conv:
                    bump("stored date already measured — left")
                    continue
                if key in sub_led:
                    bump("sub_dates entry exists — left")
                    continue
                day = int(dt.strftime("%Y%m%d"))
                if day < int(qe.replace("-", "")):
                    bump("time before quarter-end (held)")
                    continue
                if key in P and P[key]["sub"] <= day:
                    bump("later capture, same or later date")
                    continue
                P[key] = {
                    "gated_1530": False,
                    "prov": "wayback: BSE shareholding/searchresult.asp capture {} ('{} | {}'); CALENDAR day (midnight rule §149); §164r 2026-09-28".format(
                        ts, r[0], r[1].replace("\xa0", " ")
                    ),
                    "src": "wayback-bse",
                    "sub": day,
                    "ts": dt.strftime("%Y-%m-%dT%H:%M:%S"),
                    "was": subi,
                    "rule": "midnight-2026-09-23",
                }
                bump("dated")
    # BSE's page shows a quarter's LATEST upload time (AMBALALSA Jun-2006 -> 9-Nov-2006 among on-time neighbours; BIOCON
    # Sep-2007 -> 4-Jan-2010). A page date is never earlier than the first publication, so an on-time date is safe;
    # one > qe+45 days (Clause 35 allowed 21) may be a re-upload and would hide the quarter for years -> held
    # (served undated as before) unless an earlier capture (wb-early) showed it on time.
    held = [
        k
        for k, v in P.items()
        if (
            date(v["sub"] // 10000, v["sub"] // 100 % 100, v["sub"] % 100)
            - date(int(k[-8:-4]), int(k[-4:-2]), int(k[-2:]))
        ).days
        > 45
    ]
    for k in held:
        del P[k]
    st["held: latest-upload date > qe+45 (possible re-upload)"] = len(held)
    json.dump(sorted(held), open(os.path.join(WB, "_held_late.json"), "w"))
    json.dump(P, open(out, "w"), indent=1, ensure_ascii=False)
    print("wb-decide:", st, "-> %d entries" % len(P))


def vstind(out):
    os.environ["DII_ROWFIX_WORK"] = os.path.join(C, "seamholes")
    import _shp_dii_rowfix as D

    hist = json.load(open(os.path.join(HERE, "shp_history.json")))
    sym, qe = "VSTIND", "2016-12-31"
    cur = hist[sym][qe]
    files = {}
    for d in [
        d for d in glob.glob(os.path.join(C, "**", "xbrl*"), recursive=True) if os.path.isdir(d)
    ] + [os.path.join(C, "ex_xbrl")]:
        try:
            for x in os.listdir(d):
                files.setdefault(x, os.path.join(d, x))
        except Exception:
            pass
    a = json.load(open(os.path.join(HERE, "_shp_164_audit.json"), encoding="utf-8"))
    a = a.get("cells", a)
    fn = (a.get("VSTIND|2016-12-31") or {}).get("src", "").replace("bsexbrl:", "")
    rows = [
        r
        for r in D.rows_of(open(files[fn], "rb").read())
        if r[0] == "OtherInstitutions"
        and re.search(r"foreign institutional investors", r[5] or "", re.I)
    ]
    if len(rows) != 1:
        print("row not unique", rows)
        return
    amt = round(rows[0][2], 4)
    new = list(cur)
    new[1] = round(cur[1] + amt, 4)
    new[2] = round(cur[2] - amt, 4)
    P = {
        "VSTIND|2016-12-31": {
            "was": cur,
            "cell": new,
            "src": "bsexbrl:" + fn,
            "why": (
                f"§164r (2026-09-28, Quantmac v4): the filer's institutional Other row labelled 'Foreign Institutional Investors' ({amt:.2f}%) "
                "is FII by its label, as in Sep-2016 and Mar-2017; R1 had dropped this quarter's evaluation on its overflow guard because "
                f"the filing also lists Matthews India Fund 7.68 on that axis while the block totals {amt:.2f} (the fund is in the FPI row). "
                f"fii {cur[1]:.4f} -> {new[1]:.4f}, dii {cur[2]:.4f} -> {new[2]:.4f}."
            ),
        }
    }
    json.dump(P, open(out, "w"), indent=1, ensure_ascii=False)
    print("vstind:", new[:3])


if __name__ == "__main__":
    st = sys.argv[1]
    if st == "zensar":
        zensar(sys.argv[2])
    elif st == "table3":
        table3(sys.argv[2])
    elif st == "nsefill":
        nsefill()
    elif st == "vstind":
        vstind(sys.argv[2])
    elif st == "wb-fetch":
        wb_fetch()
    elif st == "wb-decide":
        wb_decide(sys.argv[2])
    elif st == "wb-older":
        wb_older()
    elif st == "drrebase":
        drrebase(sys.argv[2])
    elif st == "d1gate":
        d1gate(sys.argv[2])
    elif st == "t3fix":
        t3fix(sys.argv[2].split(","), sys.argv[3])
    elif st == "undated-fetch":
        anndates_fetch(_undated_items())
    elif st == "undated-decide":
        undated_decide(sys.argv[2])
    elif st == "lag-revert":
        lag_revert(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "shp_lag_fix.json")
    elif st == "wb-early":
        wb_early(sys.argv[2])
    elif st == "lag-write":
        lag_write(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "shp_lag_fix.json")
    elif st == "table3-write":
        table3_write(sys.argv[2])
    elif st == "anndates-fetch":
        anndates_fetch()
    elif st == "anndates-decide":
        anndates_decide(sys.argv[2])
    else:
        sys.exit(__doc__)
