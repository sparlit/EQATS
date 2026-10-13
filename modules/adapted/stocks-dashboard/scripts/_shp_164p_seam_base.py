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
"""§164p — two store defects found while closing the Quantmac reply-#4 open items (2026-09-27).

(1) SEAM-QUARTER BASE. BSE's Dec-2015 / Mar-2016 pages (qtrid 88/89) re-render the SEBI-2015 filing in the Clause-35
    table and, for some companies, leave the depository-receipt / employee-trust shares (block C) out of the total, so
    every percentage on the page is of a smaller base (DRREDDY Dec-15: 139,758,553 printed vs 170,588,515 on the
    Sep-2015 page -> FII 46.16 where the company's own full-count basis gives 37.82). A cell is re-based only when:
      * the company is on the FULL-count basis (not in the §164a A+B(+C2) set),
      * the stored cell IS the page reading (stored promoter == the page's promoter % within 0.011),
      * the documented full count N = Sep-2015 page total + the change in paid-up equity capital between the
        company's ORIGINAL NSE results filings for Sep-2015 and the seam quarter (same unit; a constant offset such as
        forfeited-share money cancels) exceeds the page total by more than max(2 x the filings' rounding, 0.1%).
    Then every slot x -> x * page_total / N (sub date and holder count kept).
(2) WRONG-COMPANY CELLS. shp_fill_hist_2010_2016 (Wayback captures of a third-party page) carries Prism Cement's
    (PRSMJOHNSN) own quarterly pattern under 13 other companies whose captured page had redirected (exact 4-slot match
    to PRSMJOHNSN's BSE/Trendlyne cell of the same quarter). Where BSE lists no filing for that company-quarter the cell
    is DROPPED; where it does, the cell is replaced by the company's own page read by fetch_shp_bse_aspx.cell_of (Dec-15/
    Mar-16 pages: fii from the §160 seam reconstruction with §164l's completeness + neighbour gates); a page that cannot
    be read inside those gates is dropped too — never estimated.

Stages (caches under ~/stocks-cache/shp/seambase; BSE via scripts/bse_headers.py, NSE archives with a plain UA):
  rebase  <out.json>     classify every stored seam cell, write re-base proposals + seam_audit.json
  wrongco <out.json> <drops.json>   the Prism family: replacement proposals + drop entries
  fix164l <out.json> <drops.json>   repair the §164l seam fills (dii kept the block moved to fii) with seam_correct
  drops   <drops.json>   merge drop entries into scripts/shp_cell_fix.json (only while the store still equals `was`)
Proposals are written to the ledger by scripts/_shp_164_write.py."""
import collections
import glob
import gzip
import html
import json
import math
import os
import re
import shutil
import sys
import time
import urllib.request
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
C = os.path.expanduser("~/stocks-cache/shp")
W = os.path.join(C, "seambase")
PAGE_DIRS = [
    os.path.join(C, d) for d in ("dii_session/aspx_pages", "w164n/aspx_pages", "w164o/aspx_pages")
] + [os.path.join(W, "pages")]
NSE_CACHES = [
    os.path.expanduser("~/stocks-wt/eps-block/scripts/_nsearch_cache"),
    os.path.join(HERE, "_nsearch_cache"),
]
NSE_OWN = os.path.join(W, "nse")
LISTS = os.path.join(C, "bse_all")
QE = {83: "2014-09-30", 86: "2015-06-30", 87: "2015-09-30", 88: "2015-12-31", 89: "2016-03-31"}
UNITS = [1e5, 1e7, 1e6, 1e3, 1.0, 1e4, 1e2]
UA = {
    "User-Agent": "stocks-dashboard-research/1.0",
    "Accept": "text/html,*/*",
    "Accept-Language": "en-US,en;q=0.9",
}


def qtrid(qe):
    y = int(qe[:4])
    m = int(qe[5:7])
    return (y - 2001) * 4 + {3: 29, 6: 30, 9: 31, 12: 32}[m]


# ---------- BSE page (Clause-35 layout incl. the 88/89 re-render) ----------
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


def _num(x):
    try:
        return float(x.replace(",", ""))
    except Exception:
        return None


def page(code, q):
    for d in PAGE_DIRS:
        p = os.path.join(d, "%s_%d.html.gz" % (code, q))
        if os.path.exists(p):
            return gzip.open(p).read().decode("utf8", "replace")


def totals(code, q):
    t = page(code, q)
    if t is None:
        return None
    out = {"AB": None, "ABC": None, "C": None, "prom_pct": None}
    inC = False
    for r in _rows(t):
        h = r[0]
        if h.startswith("(C)"):
            inC = True
        if h.startswith("Total (A)+(B)+(C)") and len(r) > 2:
            out["ABC"] = _num(r[2])
        elif h.startswith("Total (A)+(B)") and len(r) > 2:
            out["AB"] = _num(r[2])
        elif inC and h.startswith("Sub Total") and len(r) > 2 and out["C"] is None:
            out["C"] = _num(r[2])
        elif h.startswith("Total shareholding of Promoter") and len(r) > 5:
            out["prom_pct"] = _num(r[5])
    return out


# ---------- NSE original results filing: paid-up equity capital, face value ----------
def _nse_list(sym):
    for d in NSE_CACHES:
        p = os.path.join(d, f"list_{sym}.json")
        if os.path.exists(p):
            return json.load(open(p))


def _nse_detail(url):
    f = url.rsplit("/", 1)[1]
    for d in NSE_CACHES + [NSE_OWN]:
        p = os.path.join(d, f)
        if os.path.exists(p):
            return open(p, encoding="utf8", errors="replace").read()
    try:
        b = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60).read()
        time.sleep(1.0)
    except Exception:
        return None
    os.makedirs(NSE_OWN, exist_ok=True)
    open(os.path.join(NSE_OWN, f), "wb").write(b)
    return b.decode("utf8", "replace")


def _val(t, k):
    m = re.search(re.escape(k) + r"\s*</t[dh]>\s*<t[dh][^>]*>(.*?)</t[dh]>", t, re.S | re.I)
    return _num(html.unescape(re.sub(r"<[^>]+>", "", m.group(1))).strip()) if m else None


def puc_first(sym, qe):
    """The ORIGINAL filing for period end qe (earliest broadcast; standalone first on ties). Later Ind-AS comparatives
    print the CURRENT capital against old periods (DRREDDY Jun-15: original 8528, 2016 comparative 8530), so never them."""
    L = _nse_list(sym)
    if not L:
        return None
    d = datetime.strptime(qe, "%Y-%m-%d").strftime("%d-%b-%Y")
    rows = [
        r
        for r in L
        if r.get("toDate") == d
        and r.get("period") == "Quarterly"
        and r.get("resultDetailedDataLink")
    ]

    def bt(r):
        try:
            return datetime.strptime(r["broadCastDate"], "%d-%b-%Y %H:%M:%S")
        except Exception:
            return datetime(2100, 1, 1)

    for r in sorted(rows, key=lambda r: (bt(r), r.get("consolidated") != "Non-Consolidated")):
        t = _nse_detail(r["resultDetailedDataLink"])
        if not t:
            continue
        p, fv = _val(t, "Paid-up equity share capital"), _val(t, "Face Value (in Rs.)")
        if p and fv:
            return {
                "seq": r.get("seqNumber"),
                "bcast": r.get("broadCastDate"),
                "puc": p,
                "fv": fv,
                "url": r["resultDetailedDataLink"],
            }
    return None


def _gran(v):
    k = 0
    while v and v % (10 ** (k + 1)) == 0:
        k += 1
    return 10**k


def _codes():
    s2c = {}
    for fn in glob.glob(os.path.join(LISTS, "*.json")):
        s = os.path.basename(fn)[:-5]
        try:
            T = json.load(open(fn))["Table"]
        except Exception:
            continue
        for r in T:
            x = r.get("XbrlFile") or ""
            if x:
                s2c[s] = x.split("_")[0]
                break
        else:
            m = re.search(r"/(\d{6})/", " ".join(str(r.get("navigateurl", "")) for r in T))
            if m:
                s2c[s] = m.group(1)
    return s2c


def _s164a(fix):
    return {s for s, qs in fix.items() for e in qs.values() if "164a" in json.dumps(e)}


def rebase(out):
    hist = json.load(open(os.path.join(HERE, "shp_history.json")))
    fix = json.load(open(os.path.join(HERE, "shp_cell_fix.json")))["fix"]
    S164A = _s164a(fix)
    s2c = _codes()
    res = collections.defaultdict(list)
    props = {}
    for sym in sorted(s for s in hist if not s.startswith("_") and isinstance(hist[s], dict)):
        c = hist[sym]
        for q in (88, 89):
            qe = QE[q]
            if qe not in c:
                continue
            code = s2c.get(sym)
            if sym in S164A:
                res["skip: §164a A+B(+C2) basis"].append((sym, qe))
                continue
            t, a = (totals(code, q), totals(code, 87)) if code else (None, None)
            if not t or not t["ABC"]:
                res["no seam page cached (Sep-2015 page shows no C, or no page)"].append((sym, qe))
                continue
            if not a or not a["ABC"]:
                res["hold: no Sep-2015 page"].append((sym, qe))
                continue
            T, Ta = t["ABC"], a["ABC"]
            drop = (Ta - T) / Ta
            rec = {
                "sym": sym,
                "qe": qe,
                "code": code,
                "page_total": T,
                "sep15_total": Ta,
                "sep15_C": a["C"],
                "page_C": t["C"],
                "page_prom_pct": t["prom_pct"],
                "stored": c[qe],
            }
            fa, fq = puc_first(sym, QE[87]), puc_first(sym, qe)
            if not fa or not fq:
                (
                    res["hold: page total below Sep-2015, no NSE paid-up capital"]
                    if drop > 0.001
                    else res["ok: no PUC, page total not below Sep-2015"]
                ).append(rec)
                continue
            if fa["fv"] != fq["fv"]:
                (
                    res["hold: face value changed"]
                    if drop > 0.001
                    else res["ok: face value changed, page total not below Sep-2015"]
                ).append(rec)
                continue
            u = min(UNITS, key=lambda u: abs(math.log(fa["puc"] * u / fa["fv"] / Ta)))
            if abs(fa["puc"] * u / fa["fv"] / Ta - 1) > 0.02:
                (
                    res["hold: paid-up capital is not a share count here"]
                    if drop > 0.001
                    else res[
                        "ok: PUC not a share count (2nd class / offset), page total not below Sep-2015"
                    ]
                ).append(rec)
                continue
            uq = min(UNITS, key=lambda v: abs(math.log(max(fq["puc"] * v, 1) / (fa["puc"] * u))))
            dRs = fq["puc"] * uq - fa["puc"] * u
            tol = (0.5 * _gran(round(fa["puc"] * u)) + 0.5 * _gran(round(fq["puc"] * uq))) / fq[
                "fv"
            ]
            N = Ta + dRs / fq["fv"]
            if abs(dRs / fq["fv"]) <= tol:
                N = Ta
            rec.update(
                {
                    "N": round(N),
                    "N_tol": round(tol),
                    "nse_sep15": fa,
                    "nse_q": fq,
                    "unit_rupees": [u, uq],
                }
            )
            if max(2 * tol, 0.001 * N) >= (N - T):
                res[
                    "ok: page total = documented count"
                    if max(2 * tol, 0.001 * N) >= (T - N)
                    else "note: page total ABOVE documented count (not a C omission)"
                ].append(rec)
                continue
            st = c[qe]
            if t["prom_pct"] is None or abs(st[0] - t["prom_pct"]) > 0.011:
                rec["why"] = (
                    "stored promoter {} is not this page's {} — the stored cell is another source's reading".format(
                        st[0], t["prom_pct"]
                    )
                )
                res["skip: stored cell is not the page reading"].append(rec)
                continue
            k = T / N
            new = [round(v * k, 4) if isinstance(v, (int, float)) else v for v in st[:5]] + list(
                st[5:]
            )
            why = (
                "§164p seam-quarter base (2026-09-27): BSE's %s page (qtrid %d) prints percentages of %s shares — it leaves "
                "out %s shares that the Sep-2015 page (%s, block C %s) and the company's paid-up capital still count (NSE "
                "original results filings: Sep-2015 #%s paid-up %s, %s #%s paid-up %s, face value %s). The company is on the "
                "FULL-count basis (D2 / §164a) and its stored Sep-2015 and Jun-2016 cells are on it, so every slot is "
                "re-expressed on the documented count %s (± %s shares, the filings' rounding): x %.6f."
            ) % (
                "Dec-2015" if q == 88 else "Mar-2016",
                q,
                f"{T:,.0f}",
                f"{N - T:,.0f}",
                f"{Ta:,.0f}",
                f"{(a['C'] or 0):,.0f}",
                fa["seq"],
                fa["puc"],
                qe,
                fq["seq"],
                fq["puc"],
                fq["fv"],
                f"{N:,.0f}",
                f"{round(tol):,}",
                k,
            )
            props[f"{sym}|{qe}"] = {
                "was": st,
                "cell": new,
                "src": "bseaspx:%s:%d+nseresults:%s" % (code, q, fq["seq"]),
                "why": why,
                "page_total": T,
                "N": round(N),
                "N_tol": round(tol),
            }
            res["FIX: page omitted shares"].append(rec)
    json.dump(props, open(out, "w"), indent=1, ensure_ascii=False)
    json.dump(res, open(os.path.join(W, "seam_audit.json"), "w"), indent=0, default=str)
    for k, v in res.items():
        print("%-90s %d" % (k, len(v)))
    print("proposals:", len(props))


def seam_correct(cell, r, main_html):
    """fetch_shp_bse_aspx.cell_of + _shp_aspx_rowfix.reconstruct on a Dec-2015/Mar-2016 page -> the cell with fii from the
    reconstruction and the SAME shares taken out of dii. cell_of's dii = mutual funds + banks + insurance (+VCF) and, when the
    institutions sub-total reconciles, the page's unlabelled institutional 'Any Others' block; the reconstruction puts that block
    (or FII holders inside it) into fii, so leaving dii alone counts those shares twice (§164l ASTRAL Mar-16: fii 11.31 + dii
    16.88 on an institutions total of 16.88). FIIs are institutions, so the fii added can never exceed that block: a second
    'lump-fii' row beyond a category row that already equals the whole block is a fund listed inside its own category
    (ADANIENT Dec-15 'Emerging India Focus Funds (Foreign Institutional Investor)' 2.84 inside 'Foreign Institutional Investor'
    10.89) and is not added again. A category row with no institutional block to sit in (SBT Dec-15: 0.88 equal to the
    Financial Institutions / Banks row) contradicts the page -> None (held, never decided). Returns (cell|None, note)."""
    import _shp_aspx_rowfix as A

    b = A.parse(main_html)
    si, _ = A.classify_rows(b["inst"], "inst")
    other = si.get("other", 0.0)
    dom = sum(si.get(k, 0.0) for k in ("mf", "bank", "ins", "vcf"))
    add = r["t_fii"] - r["base_fii"]
    note = []
    cats = [e for e in r["ev"] if e[0] == "lump-fii"]
    if add > other + 0.01:
        full = [e for e in cats if abs(e[2] - other) <= 0.01]
        if full:
            note.append(
                "fii add {:.4f} > institutional block {:.2f}: kept the category row {!r} = the block; {} listed inside it".format(
                    add,
                    other,
                    full[0][1],
                    ", ".join(f"{e[1]!r} {e[2]:.4f}" for e in r["ev"] if e is not full[0]),
                )
            )
            add = full[0][2]
        else:
            return (
                None,
                f"fii add {add:.4f} exceeds the page's institutional Any-Others block {other:.2f} and no category row equals the block",
            )
    if add > 0.005 and other < 0.005:
        return (
            None,
            f"the >1% table's FII row(s) {add:.4f} have no institutional Any-Others block to sit in on the page",
        )
    new = list(cell)
    new[1] = round(r["base_fii"] + add, 4)
    if add > 0.005 and cell[2] is not None and abs(cell[2] - (dom + other)) <= 0.02:
        new[2] = round(cell[2] - add, 4)
        note.append(f"dii {cell[2]:.4f} - {add:.4f} moved to fii")
    else:
        note.append(f"dii {cell[2]} = mf+banks+ins(+vcf) {dom:.2f} without the block: unchanged")
    return new, "; ".join(note)


# ---------- (2) wrong-company cells ----------
def wrongco_cells(hist):
    """Every non-trivial cell (fii >= 0.5 and dii >= 0.5) of a Wayback fill that equals, slot for slot at 2dp, another
    company's cell of the same quarter taken from a BSE/Trendlyne reading, the two companies sharing no rename link."""
    led = json.load(gzip.open(os.path.join(HERE, "shp_fill_hist_2010_2016.json.gz")))["fills"]
    ren = json.load(open(os.path.join(HERE, "_rename_map.json")))

    def linked(a, b):
        return ren.get(a) == b or ren.get(b) == a

    idx = collections.defaultdict(list)
    for s, c in hist.items():
        if s.startswith("_") or not isinstance(c, dict):
            continue
        for q, v in c.items():
            if v[1] is None or v[2] is None or v[1] < 0.5 or v[2] < 0.5:
                continue
            idx[
                (q, round(v[0] or 0, 2), round(v[1], 2), round(v[2], 2), round(v[3] or 0, 2))
            ].append(s)
    out = []
    for k, syms in idx.items():
        if len(syms) < 2:
            continue
        wb = [
            s
            for s in syms
            if str(((led.get(s) or {}).get(k[0]) or [None] * 8)[7]).startswith("wb:")
        ]
        own = [s for s in syms if s not in wb]
        for s in wb:
            for o in own:
                if not linked(s, o):
                    out.append((s, k[0], o, hist[s][k[0]]))
                    break
    return out


def _read_page_cell(sym, qe, code, hist, verdicts):
    import _shp_aspx_rowfix as A
    import _shp_dii_rowfix as D
    import fetch_shp_bse_aspx as FA

    q = qtrid(qe)
    st, cell, det = FA.cell_of(
        {"sym": sym, "qe": qe, "code": int(code), "qtrid": q, "bname": "", "lname": ""},
        os.path.join(W, "fa"),
        None,
    )
    if st != "ok":
        return None, f"page not readable: {st} {det}"
    cell = list(cell)
    if q in (88, 89):
        src = os.path.join(W, "fa", "cache", "%s_%d_New.html.gz" % (code, q))
        dst = os.path.join(W, "fa", "aspx_pages", "%s_%d.html.gz" % (code, q))
        if os.path.exists(src) and not os.path.exists(dst):
            shutil.copy2(src, dst)
        lp = os.path.join(LISTS, sym + ".json")
        rows = []
        if os.path.exists(lp):
            t = json.load(open(lp))
            rows = t.get("Table") if isinstance(t, dict) else t
        ctx = D.SymCtx(sym, rows, verdicts)
        try:
            r, why = A.reconstruct(
                sym, int(code), q, ctx, verdicts, known_foreign=A.sibling_foreign_names(int(code))
            )
        except Exception as e:
            r, why = None, f"reconstruct error {e!r}"
        if r is None:
            return None, f"no seam reconstruction: {why}"
        kinds = {e[0] for e in r["ev"]}
        if not (r["lumps"] < 0.05 or "lump-fii" in kinds or r.get("whole_block")):
            return (
                None,
                "seam page lump {:.2f} with no FII category row (named holders alone under-count)".format(
                    r["lumps"]
                ),
            )
        cell, why = seam_correct(cell, r, gzip.open(dst, "rt", encoding="utf-8").read())
        if cell is None:
            return None, why
    c = hist.get(sym) or {}
    qs = sorted(c)
    nb = [
        c[x][1]
        for x in [x for x in qs if x < qe][-1:] + [x for x in qs if x > qe][:1]
        if c[x][1] is not None
    ]
    if len(nb) >= 2 and not (min(nb) - 3 <= cell[1] <= max(nb) + 3):
        return (
            None,
            f"page fii {cell[1]:.2f} outside the neighbours {min(nb):.2f}..{max(nb):.2f} +-3",
        )
    return cell, "page read"


def wrongco(out, drops_out):
    hist = json.load(open(os.path.join(HERE, "shp_history.json")))
    s2c = _codes()
    cells = wrongco_cells(hist)
    os.makedirs(os.path.join(W, "fa", "cache"), exist_ok=True)
    for d in ("aspx_pages", "shpperent"):
        os.makedirs(os.path.join(W, "fa", d), exist_ok=True)
    if not os.path.exists(os.path.join(W, "fa", "generic_rows.json")):
        json.dump([], open(os.path.join(W, "fa", "generic_rows.json"), "w"))
    os.environ["DII_ROWFIX_WORK"] = os.path.join(W, "fa")
    os.environ.setdefault("DII_ROWFIX_LISTS", LISTS)
    import _shp_dii_rowfix as D

    verdicts = D.load_verdicts()
    props, drops, log = {}, {}, []
    WB = json.load(gzip.open(os.path.join(HERE, "shp_fill_hist_2010_2016.json.gz")))["fills"]
    MON = {"03": "March", "06": "June", "09": "September", "12": "December"}
    for sym, qe, owner, cur in sorted(cells):
        code = s2c.get(sym)
        lab = f"{MON[qe[5:7]]} {qe[:4]}"
        T = json.load(open(os.path.join(LISTS, sym + ".json")))["Table"] if code else []
        filed = any((r.get("qtr") or "") == lab for r in T)
        base = (
            "§164p wrong-company cell (2026-09-27): this Wayback-sourced value ({}) equals {}'s own {} pattern slot for "
            "slot ({}) — the captured page had redirected to that company. ".format(
                str(((WB.get(sym) or {}).get(qe) or [""] * 8)[7])[:60], owner, qe, cur[:4]
            )
        )
        if not filed:
            drops.setdefault(sym, {})[qe] = {
                "was": cur,
                "why": base
                + f"BSE lists no shareholding filing for {sym} (code {code}) for this quarter, so the cell is retracted.",
            }
            log.append((sym, qe, "drop: no BSE filing"))
            continue
        q = qtrid(qe)
        # main page into the reader's cache (fetch_shp_bse_aspx layout; cell_of fetches it with bse_headers when absent)
        src = [
            p
            for p in (os.path.join(d, "%s_%d.html.gz" % (code, q)) for d in PAGE_DIRS)
            if os.path.exists(p)
        ]
        dst = os.path.join(W, "fa", "cache", "%s_%d_New.html.gz" % (code, q))
        if src and not os.path.exists(dst):
            shutil.copy2(src[0], dst)
        if q in (88, 89):
            for qq in (88, 89):
                p = os.path.join(W, "fa", "shpperent", "%s_%d.html.gz" % (code, qq))
                if os.path.exists(p):
                    continue
                u = (
                    "https://www.bseindia.com/corporates/shpperent.aspx?scripcd=%s&qtrid=%d&CompName=X&QtrName=X"
                    % (code, qq)
                )
                try:
                    body = urllib.request.urlopen(urllib.request.Request(u), timeout=60).read()
                except Exception:
                    body = b""
                time.sleep(1.0)
                if len(body) > 2000:
                    with gzip.open(p, "wt", encoding="utf-8") as fh:
                        fh.write(body.decode("utf-8", "ignore"))
        cell, why = _read_page_cell(sym, qe, code, hist, verdicts)
        if cell is None:
            drops.setdefault(sym, {})[qe] = {
                "was": cur,
                "why": base
                + f"BSE has a filing for this quarter but its page could not be read inside the gates ({why}), so the wrong value is retracted, not estimated.",
            }
            log.append((sym, qe, "drop: " + why))
            continue
        new = cell[:7] if len(cell) > 6 and cell[6] is not None else cell[:6]
        new[5] = cur[5]  # keep the quarter's stored date convention
        props[f"{sym}|{qe}"] = {
            "was": cur,
            "cell": new,
            "src": "bseaspx:%s:%d" % (code, q),
            "why": base
            + "Replaced by the company's own BSE page (qtrid %d) read by fetch_shp_bse_aspx.cell_of%s."
            % (
                q,
                " with fii from the §160 seam reconstruction (§164l gates)"
                if q in (88, 89)
                else "",
            ),
        }
        log.append((sym, qe, f"replace: {cur[:3]} -> {new[:3]}"))
    json.dump(props, open(out, "w"), indent=1, ensure_ascii=False)
    json.dump(drops, open(drops_out, "w"), indent=1, ensure_ascii=False)
    for x in log:
        print("  %-11s %s  %s" % x)
    print("replacements %d, drops %d" % (len(props), sum(len(v) for v in drops.values())))


def fix164l(out, drops_out):
    """Re-read every §164l seam fill with seam_correct (the §164l parse left dii holding the block it moved to fii)."""
    hist = json.load(open(os.path.join(HERE, "shp_history.json")))
    led = json.load(gzip.open(os.path.join(HERE, "shp_fill_seam_aspx.json.gz")))["fills"]
    work = os.path.join(C, "seamholes")
    os.chdir(work)
    os.environ["DII_ROWFIX_WORK"] = work
    os.environ.setdefault("DII_ROWFIX_LISTS", LISTS)
    import _shp_aspx_rowfix as A
    import _shp_dii_rowfix as D

    verdicts = D.load_verdicts()
    props, drops = {}, {}
    for s, qs in sorted(led.items()):
        for qe, v in sorted(qs.items()):
            if "164l" not in str(v[-1]):
                continue
            cur = (hist.get(s) or {}).get(qe)
            if cur is None:
                continue
            fillcell = v[:7] if v[6] is not None else v[:6]
            import fetch_shareholding as F

            if not F._cell_eq(cur, fillcell):
                print("  %-11s %s store moved off the §164l fill — skipped" % (s, qe))
                continue
            code = int(str(v[-1]).split(":")[1])
            q = qtrid(qe)
            lp = os.path.join(LISTS, s + ".json")
            rows = []
            if os.path.exists(lp):
                t = json.load(open(lp))
                rows = t.get("Table") if isinstance(t, dict) else t
            r, why = A.reconstruct(
                s,
                code,
                q,
                D.SymCtx(s, rows, verdicts),
                verdicts,
                known_foreign=A.sibling_foreign_names(code),
            )
            if r is None or abs(r["t_fii"] - cur[1]) > 0.0001:
                print(
                    "  %-11s %s reconstruction now %s (stored fii %s) — skipped"
                    % (s, qe, r and r["t_fii"], cur[1])
                )
                continue
            main = gzip.open(
                os.path.join(work, "aspx_pages", "%d_%d.html.gz" % (code, q)),
                "rt",
                encoding="utf-8",
            ).read()
            new, note = seam_correct(list(cur), r, main)
            base = "§164p repair of a §164l seam fill (2026-09-27): "
            if new is None:
                drops.setdefault(s, {})[qe] = {
                    "was": cur,
                    "why": base
                    + note
                    + " — the fill is retracted (held), the quarter stays unread.",
                }
                print("  %-11s %s RETRACT: %s" % (s, qe, note))
                continue
            if F._cell_eq(new, cur) and new[1] == cur[1] and new[2] == cur[2]:
                print("  %-11s %s unchanged (%s)" % (s, qe, note))
                continue
            props[f"{s}|{qe}"] = {
                "was": cur,
                "cell": new,
                "src": str(v[-1]),
                "why": base
                + note
                + " (page institutions: mf/banks/ins in dii, the FII block in fii, never both).",
            }
            print(
                "  %-11s %s fii %s->%s dii %s->%s | %s"
                % (s, qe, cur[1], new[1], cur[2], new[2], note)
            )
    json.dump(props, open(out, "w"), indent=1, ensure_ascii=False)
    json.dump(drops, open(drops_out, "w"), indent=1, ensure_ascii=False)
    print("repairs %d, retractions %d" % (len(props), sum(len(x) for x in drops.values())))


def write_drops(path):
    import fetch_shareholding as F

    D = json.load(open(path))
    p = os.path.join(HERE, "shp_cell_fix.json")
    raw = open(p, encoding="utf-8").read()
    led = json.loads(raw)
    hist = json.load(open(os.path.join(HERE, "shp_history.json")))
    dr = led.setdefault("drop", {})
    n = skip = 0
    for s, qs in D.items():
        for qe, ent in qs.items():
            cur = (hist.get(s) or {}).get(qe)
            if cur is None or not F._cell_eq(cur, ent["was"]) or qe in (dr.get(s) or {}):
                skip += 1
                continue
            dr.setdefault(s, {})[qe] = ent
            n += 1
    json.dump(led, open(p, "w", encoding="utf-8"), indent=1, ensure_ascii=("\\u00" in raw))
    print("drops written %d, skipped %d" % (n, skip))


if __name__ == "__main__":
    st = sys.argv[1]
    if st == "rebase":
        rebase(sys.argv[2])
    elif st == "wrongco":
        wrongco(sys.argv[2], sys.argv[3])
    elif st == "fix164l":
        fix164l(sys.argv[2], sys.argv[3])
    elif st == "drops":
        write_drops(sys.argv[2])
    else:
        sys.exit(__doc__)
