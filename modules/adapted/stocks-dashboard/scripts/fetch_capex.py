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
# -*- coding: utf-8 -*-
"""Capex Tracker feed -> docs/capex.json  (DATA_RUNBOOK section 138, page docs/capex.html)

Government capex
  A. Union Budget "Budget at a Glance" PDFs (indiabudget.gov.in): capital expenditure per FY as
     Actuals / Revised Estimates / Budget Estimates, plus Total Expenditure, Effective Capex, Fiscal
     Deficit and the GDP the budget assumed. Each FY's Actuals only appear in the budget TWO years
     later, so the series is chained across documents. The archive (2014-15 .. today) is parsed once
     into scripts/capex_budget_ledger.json (--seed-budget, provenance = URL + page per document); a
     normal run re-reads only the CURRENT bag1.pdf so a new budget (Feb 1) lands by itself.
  B. CGA monthly "Union Government Accounts at a Glance" HTML
     https://cga.nic.in/writereaddata/MonthAccount/{M}{YYYY}/DATA{yy}{yy+1}.htm  (Apr-2017 onward):
     cumulative actuals to date vs BE (RE from January; March = provisional full year). Cumulative
     merge; the newest 3 stored months are re-fetched so CGA revisions land.
Private capex
  C. Listed-company capex from our own XBRL cash-flow store (scripts/xbrl_extra.json.gz):
     PurchaseOfPropertyPlantAndEquipment as filed, per financial year, consolidated where filed else
     standalone; year-on-year on SAME-BASIS pairs only (a con->std switch would fake a fall).
     Universes: all filers ex Financial Services (BSE macro sector), Nifty 500 (latest snapshot in
     docs/stock_data.bin) ex financials, and a fixed Nifty-500 panel with all five FYs (the set the
     press compares). Also BSE macro-sector split, top spenders, count of >=1,000 cr spenders, H1.
  D. Official / press readings (scripts/capex_official.json): RBI bulletin envisaged-capex series,
     MoSPI capex-intentions survey rounds, MoSPI GFCF (GDP press notes), press figures used for the
     reality-check table. Hand-read with URL provenance; copied through verbatim.
  E. Nominal GDP: docs/macro.json series.gdpn (MoSPI, FY-end dated, lakh crore) for capex/GDP.

Run:  python3 scripts/fetch_capex.py               # CI: CGA top-up + current budget + filings
      python3 scripts/fetch_capex.py --seed-budget  # one-time: parse the whole budget archive
      python3 scripts/fetch_capex.py --no-fetch     # rebuild capex.json from ledgers + filings only
Stdlib only, except PyMuPDF (fitz) for the budget PDFs (CI installs pymupdf).
"""
import argparse
import datetime
import gzip
import html
import json
import os
import re
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DOCS = os.path.join(ROOT, "docs")
OUT = os.path.join(DOCS, "capex.json")
LEDGER = os.path.join(HERE, "capex_budget_ledger.json")
OFFICIAL = os.path.join(HERE, "capex_official.json")
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"

BAG_CURRENT = "https://www.indiabudget.gov.in/doc/Budget_at_Glance/bag1.pdf"
BAG_ARCHIVE = {  # document FY -> URL (verified 2026-09-07; 2016-17 is bag11.pdf on the archive site)
    "2025-26": "https://www.indiabudget.gov.in/budget2025-26/doc/Budget_at_Glance/bag1.pdf",
    "2024-25": "https://www.indiabudget.gov.in/budget2024-25/doc/Budget_at_Glance/bag1.pdf",
    "2023-24": "https://www.indiabudget.gov.in/budget2023-24/doc/Budget_at_Glance/bag1.pdf",
    "2022-23": "https://www.indiabudget.gov.in/budget2022-23/doc/Budget_at_Glance/bag1.pdf",
    "2021-22": "https://www.indiabudget.gov.in/budget2021-22/doc/Budget_at_Glance/bag1.pdf",
    "2020-21": "https://www.indiabudget.gov.in/budget2020-21/doc/Budget_at_Glance/bag1.pdf",
    "2019-20": "https://www.indiabudget.gov.in/budget2019-20/doc/Budget_at_Glance/bag1.pdf",
    "2018-19": "https://www.indiabudget.gov.in/budget2018-2019/ub2018-19/bag/bag1.pdf",
    "2017-18": "https://www.indiabudget.gov.in/budget2017-2018/ub2017-18/bag/bag1.pdf",
    "2016-17": "https://www.indiabudget.gov.in/budget2016-2017/ub2016-17/bag/bag11.pdf",
    "2015-16": "https://www.indiabudget.gov.in/budget2015-2016/ub2015-16/bag/bag1.pdf",
    "2014-15": "https://www.indiabudget.gov.in/budget2014-2015/ub2014-15/bag/bag1.pdf",
}
CGA_FIRST = (2017, 4)  # earliest month cga.nic.in serves (Apr-2016 and older 404, measured 2026-09-07)


def get(url, timeout=60, binary=False):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        b = r.read()
    return b if binary else b.decode("utf-8", "replace")


def fy_label(y):
    """2026 -> '2026-27' (FY starting April y)."""
    return "%d-%02d" % (y, (y + 1) % 100)


def fy_start(label):
    return int(label[:4])


# ----------------------------------------------------------------------------- A. Budget at a Glance
def _lines(page):
    return [l.strip() for l in page.get_text().split("\n") if l.strip()]


def _nums_after(lines, k, n):
    out = []
    for l in lines[k + 1 : k + 16]:
        s = l.replace(",", "").replace("`", "").replace("₹", "").strip()
        if re.fullmatch(r"-?\d{2,9}", s):
            out.append(int(s))
        elif out and re.match(r"^\d{1,2}\.\s*[A-Za-z]", l):
            break  # next labelled row started
        if len(out) >= n:
            break
    return out


ROW_PATTERNS = {  # first pattern that matches wins (older docs carry plan/non-plan sub-rows too)
    "capex": [r"^19\.\s*Capital Expenditure", r"On Capital Account\s*\(11\+15\)", r"^1[0-9]\.\s*On Capital\s*Account"],
    "rev": [r"^17\.\s*Revenue Expenditure", r"On Revenue Account\s*\(10\+13\)", r"^10\.\s*On Revenue Account"],
    "te": [r"Total Expenditure"],
    "eff": [r"Effective Capital"],
    "fd": [r"^\d+\.\s*Fiscal Deficit"],
}


def parse_bag(pdf_bytes, doc_fy=None):
    """Return {'doc': '2026-27', 'ncol': 4|5, 'cols': [[kind, fy], ...], 'rows': {capex: [...], ...}, 'gdp': {fy: crore}}."""
    import fitz

    d = fitz.open(stream=pdf_bytes, filetype="pdf")
    full = " ".join(" ".join(p.get_text().split()) for p in d)
    if not doc_fy:
        m = re.search(r"BUDGET AT A GLANCE\s+(\d{4})-(\d{4})", full, re.IGNORECASE) or re.search(
            r"Budget at a Glance\s+(\d{4})-(\d{4})", full
        )
        if m:
            doc_fy = fy_label(int(m.group(1)))
    if not doc_fy:
        msg = "could not read the document's FY from the PDF"
        raise RuntimeError(msg)
    page = None
    for p in d:
        ls = _lines(p)
        # join split labels like '13. On Capital' + 'Account'
        j = []
        for l in ls:
            if j and re.match(r"^\d{1,2}\.\s*On (Capital|Revenue)$", j[-1]) and re.match(r"^Account", l):
                j[-1] = j[-1] + " " + l
            else:
                j.append(l)
        ls = j
        if (
            any("Total Expenditure" in l for l in ls)
            and any(re.search(r"On Capital Account|Capital Expenditure", l) for l in ls)
            and any("Actuals" in l for l in ls[:80])
        ):
            page = ls
            break
    if page is None:
        msg_0 = f"no Budget-at-a-Glance table page found in {doc_fy}"
        raise RuntimeError(msg_0)
    ncol = 5 if sum(1 for l in page[:60] if "Actuals" in l) >= 2 else 4
    y = fy_start(doc_fy)
    cols = [["act", fy_label(y - 2)], ["be", fy_label(y - 1)], ["re", fy_label(y - 1)]]
    if ncol == 5:
        cols.append(["act_prov", fy_label(y - 1)])
    cols.append(["be", doc_fy])
    rows = {}
    for key, pats in ROW_PATTERNS.items():
        for pat in pats:
            hit = None
            for k, l in enumerate(page):
                if re.search(pat, l):
                    hit = k
                    break
            if hit is not None:
                vals = _nums_after(page, hit, ncol)
                if len(vals) == ncol:
                    rows[key] = vals
                    break
    gdp = {}
    for m in re.finditer(
        r"GDP for (?:BE|Budget FY|FY)\s*(\d{4})-(?:20)?\d{2}[^.]{0,40}?(?:projected|estimated) at\s*[`₹]?\s*([\d,]{6,})\s*crore",
        full,
    ):
        gdp[fy_label(int(m.group(1)))] = int(m.group(2).replace(",", ""))
    for m in re.finditer(
        r"(?:Advance|Provisional) Estimates (?:for|of) FY\s*(\d{4})-\d{2}\s*(?:of|at)\s*[₹`]?\s*([\d,]{6,})", full
    ):
        gdp.setdefault(fy_label(int(m.group(1))), int(m.group(2).replace(",", "")))
    return {"doc": doc_fy, "ncol": ncol, "cols": cols, "rows": rows, "gdp": gdp}


def load_ledger():
    try:
        return json.load(open(LEDGER, encoding="utf-8"))
    except Exception:
        return {
            "_readme": "Budget-at-a-Glance rows per document (crore). cols = column meaning per value; "
            "rows.capex = capital expenditure ('On Capital Account' / 'Capital Expenditure' total), "
            "rev = revenue expenditure, te = total expenditure, eff = effective capex (2022-23 docs on), "
            "fd = fiscal deficit, gdp = GDP the document quotes (crore). Seeded by fetch_capex.py --seed-budget.",
            "docs": {},
        }


def seed_budget(ledger, urls):
    for fy, url in urls.items():
        try:
            pdf = get(url, binary=True)
            rec = parse_bag(pdf, None if fy == "current" else fy)
        except Exception as e:
            print(f"  budget {fy}: FAILED {str(e)[:100]}")
            continue
        rec["url"] = url
        rec["fetched"] = datetime.date.today().isoformat()
        old = ledger["docs"].get(rec["doc"])
        if old and old.get("rows") == rec["rows"] and old.get("gdp") == rec["gdp"]:
            print("  budget {}: unchanged".format(rec["doc"]))
        else:
            ledger["docs"][rec["doc"]] = rec
            print(
                "  budget {}: {} cols={} capex={} te={} eff={} gdp={}".format(
                    rec["doc"],
                    rec["ncol"],
                    [c[0][:2] + c[1][2:4] for c in rec["cols"]],
                    rec["rows"].get("capex"),
                    rec["rows"].get("te"),
                    rec["rows"].get("eff"),
                    rec["gdp"],
                )
            )
    return ledger


def build_annual(ledger, cga_monthly):
    """Chain the documents into one row per FY: be (own doc), re (next doc), act (doc two later; else the
    provisional Actuals column of a 5-column doc; else CGA's March provisional)."""
    series = {}
    docs = sorted(ledger["docs"].values(), key=lambda r: r["doc"])
    for rec in docs:
        for i, (kind, fy) in enumerate(rec["cols"]):
            row = series.setdefault(fy, {"fy": fy})
            for key in ("capex", "te", "eff", "fd", "rev"):
                vals = rec["rows"].get(key)
                if not vals:
                    continue
                if kind == "act_prov":
                    if key + "_act" not in row:
                        row[key + "_act"] = vals[i]
                        row["act_src"] = "BaG {} (provisional)".format(rec["doc"])
                elif kind == "act":
                    row[key + "_act"] = vals[i]
                    row["act_src"] = "BaG {}".format(rec["doc"])
                else:
                    row[key + "_" + kind] = vals[i]
                    row[kind + "_src"] = "BaG {}".format(rec["doc"])
        for fy, g in rec.get("gdp", {}).items():
            series.setdefault(fy, {"fy": fy}).setdefault("gdp_budget", g)
    # CGA March provisional for the newest closed FY without Actuals
    for m in cga_monthly:
        if m["ym"].endswith("-03") and m.get("prov"):
            row = series.setdefault(m["fy"], {"fy": m["fy"]})
            if "capex_act" not in row:
                row["capex_prov"] = m["ce"]
                row["te_prov"] = m.get("te")
                row["prov_src"] = "CGA provisional accounts, March {}".format(m["ym"][:4])
    return [series[k] for k in sorted(series)]


# ----------------------------------------------------------------------------- B. CGA monthly
CGA_LABELS = {
    "Revenue Receipts": "rr",
    "Tax Revenue (Net)": "tax",
    "Non-Tax Revenue": "ntr",
    "Non-Debt Capital Receipts": "ndcr",
    "Total Receipts (1+4)": "tr",
    "Revenue Expenditure": "re",
    "of which Interest Payments": "int",
    "Capital Expenditure": "ce",
    "of which Loans disbursed": "loans",
    "Total Expenditure (8+10)": "te",
    "Fiscal Deficit (12-7)": "fd",
    "Revenue Deficit (8-1)": "rd",
    "Primary Deficit (13-9)": "pd",
}


def cga_url(y, m):
    fy = y if m >= 4 else y - 1
    return "https://cga.nic.in/writereaddata/MonthAccount/%d%d/DATA%02d%02d.htm" % (m, y, fy % 100, (fy + 1) % 100)


def _num(s):
    s = s.replace(",", "").replace(" ", "").replace("Rs.", "")
    m = re.fullmatch(r"\(?(-?\d+(?:\.\d+)?)\)?", s)
    return float(m.group(1)) if m else None


def parse_cga(text, y, m):
    rows = []
    for r in re.findall(r"<tr[^>]*>(.*?)</tr>", text, flags=re.DOTALL):
        cells = [
            re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", c))).strip()
            for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", r, flags=re.DOTALL)
        ]
        cells = [c for c in cells if c]
        if cells:
            rows.append(cells)
    hdr = next((c for c in rows if any("Estimates" in x for x in c)), None)
    if not hdr:
        msg = "no header row"
        raise RuntimeError(msg)
    est = "RE" if "Revised" in hdr[0] else "BE"
    prov = any("Provisional" in x for x in hdr)
    fy = y if m >= 4 else y - 1
    rec = {"ym": "%d-%02d" % (y, m), "fy": fy_label(fy), "est": est, "prov": prov, "src": cga_url(y, m)}
    n = 0
    for c in rows:
        if len(c) > 1 and re.fullmatch(r"\d+", c[0]) and c[1] in CGA_LABELS:
            vals = [x for x in c[2:] if x != "(Details)"]
            nums = [_num(x) for x in vals if "%" not in x and _num(x) is not None]
            if len(nums) >= 2:
                key = CGA_LABELS[c[1]]
                rec[key + "_be"] = nums[0]
                rec[key] = nums[1]
                n += 1
    if "ce" not in rec or "ce_be" not in rec:
        msg = "capital expenditure row missing"
        raise RuntimeError(msg)
    rec["n"] = n
    return rec


def update_cga(monthly, today):
    have = {m["ym"]: m for m in monthly}
    refetch = set(sorted(have)[-3:])
    y, m = CGA_FIRST
    fetched = 0
    while (y, m) <= (today.year, today.month):
        ym = "%d-%02d" % (y, m)
        if ym not in have or ym in refetch:
            try:
                rec = parse_cga(get(cga_url(y, m)), y, m)
                if ym in have and have[ym] != rec:
                    print(f"  CGA {ym}: revised")
                elif ym not in have:
                    print(
                        "  CGA {}: new ({} {} ce={:.0f} of {:.0f})".format(
                            ym, rec["est"], rec["fy"], rec["ce"], rec["ce_be"]
                        )
                    )
                have[ym] = rec
                fetched += 1
            except urllib.error.HTTPError as e:
                if e.code != 404:
                    print(f"  CGA {ym}: HTTP {e.code}")
            except Exception as e:
                print(f"  CGA {ym}: {str(e)[:80]}")
        m += 1
        if m > 12:
            m, y = 1, y + 1
    return [have[k] for k in sorted(have)], fetched


# ----------------------------------------------------------------------------- C. listed-company filings
FIN_MACRO = "Financial Services"


def load_filings():
    X = json.load(gzip.open(os.path.join(HERE, "xbrl_extra.json.gz"), "rt", encoding="utf-8"))
    cls = json.load(open(os.path.join(DOCS, "sector_classification.json"), encoding="utf-8"))
    names = {}
    try:
        for r in json.load(open(os.path.join(DOCS, "search_index.json"), encoding="utf-8")).get("s", []):
            names[r[0]] = r[1]
    except Exception:
        pass
    n500, n500_date, IH = set(), None, {}
    try:
        D = json.loads(gzip.decompress(open(os.path.join(DOCS, "stock_data.bin"), "rb").read()))
        IH = D["indicesHistory"]
        snaps = sorted(IH["Nifty 500"], key=lambda s: s["effectiveDate"])
        s = snaps[-1]
        n500 = {x for x in s["symbols"] if not str(x).upper().startswith("DUMMY")}
        n500_date = s["effectiveDate"]
    except Exception as e:
        print(f"  (Nifty 500 snapshot unavailable: {str(e)[:60]})")
    return X, cls, names, n500, n500_date, IH


def members_asof(IH, idx, asof):
    """Members of index `idx` per the newest snapshot at or before ISO date `asof`."""
    snaps = sorted(IH.get(idx, []), key=lambda s: s["effectiveDate"])
    best = [s for s in snaps if s["effectiveDate"] <= asof]
    if not best:
        return None, set()
    s = best[-1]
    return s["effectiveDate"], {x for x in s["symbols"] if not str(x).upper().startswith("DUMMY")}


GROUPS = {  # listed companies of a promoter group, for the reality-check table (hand list, 2026-09-07)
    "Adani": [
        "ADANIENT",
        "ADANIPORTS",
        "ADANIGREEN",
        "ADANIPOWER",
        "ADANIENSOL",
        "ATGL",
        "AWL",
        "ACC",
        "AMBUJACEM",
        "NDTV",
        "SANGHIIND",
    ],
}


def fy_cell(qs, fy, basis):
    """Capex (and cfo) for financial year `fy` (Apr fy-1 .. Mar fy): the March quarter's cash-flow column, or a
    Dec/Sep/Jun year-end filing with >=300 cash-flow days for non-March year-ends. Returns dict or None."""
    x = (qs.get("%d0331" % fy) or {}).get(basis) or {}
    if x.get("capex") is not None:
        return x
    for qe in ("%d1231" % (fy - 1), "%d0930" % (fy - 1), "%d0630" % (fy - 1)):
        x = (qs.get(qe) or {}).get(basis) or {}
        if x.get("capex") is not None and (x.get("cf_d") or 0) >= 300:
            return x
    return None


def build_filings(FYS=(2021, 2022, 2023, 2024, 2025, 2026)):
    X, cls, names, n500, n500_date, IH = load_filings()

    def macro(s):
        return (cls.get(s + ".NS") or cls.get(s) or {}).get("macro") or "Unclassified"

    nonfin = [s for s in X if macro(s) != FIN_MACRO]

    def best(s, fy):
        for b in ("c", "s"):
            x = fy_cell(X[s], fy, b)
            if x:
                return x, b
        return None, None

    def pair(s, fy):  # same-basis (fy, fy-1)
        for b in ("c", "s"):
            a, p = fy_cell(X[s], fy, b), fy_cell(X[s], fy - 1, b)
            if a and p:
                return a, p, b
        return None, None, None

    def universe_series(syms):
        out = {
            "n": [],
            "capex": [],
            "cfo": [],
            "cfo_n": [],
            "gt1000": [],
            "panel_n": [],
            "panel_cur": [],
            "panel_prev": [],
        }
        for fy in FYS:
            n = cap = cfo = cfo_n = gt = 0
            pn = pc = pp = 0
            for s in syms:
                x, _ = best(s, fy)
                if x:
                    n += 1
                    cap += x["capex"]
                    if x["capex"] >= 1000:
                        gt += 1
                    if x.get("cfo") is not None:
                        cfo += x["cfo"]
                        cfo_n += 1
                a, p, _ = pair(s, fy)
                if a:
                    pn += 1
                    pc += a["capex"]
                    pp += p["capex"]
            out["n"].append(n)
            out["capex"].append(round(cap))
            out["cfo"].append(round(cfo))
            out["cfo_n"].append(cfo_n)
            out["gt1000"].append(gt)
            out["panel_n"].append(pn)
            out["panel_cur"].append(round(pc))
            out["panel_prev"].append(round(pp))
        return out

    def fixed_panel(syms, fys):
        members = [s for s in syms if all(best(s, fy)[0] for fy in fys)]
        return {
            "fys": list(fys),
            "n": len(members),
            "capex": [round(sum(best(s, fy)[0]["capex"] for s in members)) for fy in fys],
            "cfo": [round(sum((best(s, fy)[0].get("cfo") or 0) for s in members)) for fy in fys],
            "cfo_n": [sum(1 for s in members if best(s, fy)[0].get("cfo") is not None) for fy in fys],
        }

    n500_nonfin = [s for s in nonfin if s in n500]
    res = {
        "fys": list(FYS),
        "def": "Purchase of property, plant & equipment from the year-end cash-flow statement as filed (XBRL), "
        "consolidated where filed else standalone, crore. Excludes intangibles, acquisitions and financial-services companies. "
        "Year-on-year 'panel' figures use only companies with the SAME basis in both years.",
        "all": universe_series(nonfin),
        "n500": universe_series(n500_nonfin),
        "n500_meta": {"snapshot": n500_date, "members": len(n500), "nonfin": len(n500_nonfin)},
        "fixed_all": fixed_panel(nonfin, (2022, 2023, 2024, 2025, 2026)),
        "fixed_n500": fixed_panel(n500_nonfin, (2022, 2023, 2024, 2025, 2026)),
    }
    # H1 (April-September half-year cash flows, cf_d 85..230) same-basis pairs, latest two Septembers
    h1 = []
    for y in range(FYS[-1] - 3, FYS[-1] + 1):
        n = cur = prev = 0
        for s in nonfin:
            for b in ("c", "s"):
                a = (X[s].get("%d0930" % y) or {}).get(b) or {}
                p = (X[s].get("%d0930" % (y - 1)) or {}).get(b) or {}
                if (
                    a.get("capex") is not None
                    and p.get("capex") is not None
                    and 85 <= (a.get("cf_d") or 0) <= 230
                    and 85 <= (p.get("cf_d") or 0) <= 230
                ):
                    n += 1
                    cur += a["capex"]
                    prev += p["capex"]
                    break
        if n:
            h1.append({"h1_fy": fy_label(y), "n": n, "cur": round(cur), "prev": round(prev)})
    res["h1"] = h1
    # sector split (BSE macro) for the last three FYs, all non-financial filers
    sectors = {}
    for fy in FYS[-3:]:
        agg = {}
        for s in nonfin:
            x, _ = best(s, fy)
            if x:
                agg[macro(s)] = agg.get(macro(s), 0) + x["capex"]
        sectors[str(fy)] = {k: round(v) for k, v in sorted(agg.items(), key=lambda kv: -kv[1])}
    res["sectors"] = sectors
    # top spenders in the latest FY with same-basis previous year
    top = []
    fy = FYS[-1]
    for s in nonfin:
        x, b = best(s, fy)
        if not x:
            continue
        p = fy_cell(X[s], fy - 1, b)
        top.append(
            {
                "sym": s,
                "name": names.get(s, s),
                "macro": macro(s),
                "basis": b,
                "capex": round(x["capex"]),
                "prev": round(p["capex"]) if p else None,
                "cfo": round(x["cfo"]) if x.get("cfo") is not None else None,
                "n500": s in n500,
            }
        )
    top.sort(key=lambda r: -r["capex"])
    res["top"] = top[:40]
    res["top_fy"] = fy
    # Nifty 50 point-in-time (members as of each FY end), same-basis y/y — the press's "Nifty 50 capex" set
    n50 = []
    for fy in FYS[1:]:
        asof, mem = members_asof(IH, "Nifty 50", "%d-03-31" % fy)
        if not mem:
            continue
        n = cur = prev = 0
        for s in mem:
            if s not in X or macro(s) == FIN_MACRO:
                continue
            a, p, _ = pair(s, fy)
            if a:
                n += 1
                cur += a["capex"]
                prev += p["capex"]
        n50.append({"fy": fy, "asof": asof, "n": n, "capex": round(cur), "prev": round(prev)})
    res["n50_pit"] = n50
    groups = {}
    for gname, syms in GROUPS.items():
        have = [s for s in syms if s in X]
        groups[gname] = {
            "syms": have,
            "capex": {str(fy): round(sum((best(s, fy)[0] or {}).get("capex") or 0 for s in have)) for fy in FYS},
            "n": {str(fy): sum(1 for s in have if best(s, fy)[0]) for fy in FYS},
        }
    res["groups"] = groups
    return res


# ----------------------------------------------------------------------------- E. GDP
def load_gdp():
    out = {}
    try:
        g = json.load(open(os.path.join(DOCS, "macro.json"), encoding="utf-8"))["series"]["gdpn"]
        if isinstance(g, dict) and isinstance(g.get("d"), dict):
            g = g["d"]
        for d, v in g.items():
            out[fy_label(int(d[:4]) - 1)] = v  # '2026-03-31' -> FY 2025-26, lakh crore
    except Exception as e:
        print(f"  (macro.json gdpn unavailable: {str(e)[:60]})")
    return out


# ----------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--seed-budget", action="store_true", help="parse the whole Budget-at-a-Glance archive into the ledger"
    )
    ap.add_argument("--no-fetch", action="store_true", help="no network: rebuild from ledgers + filings")
    ap.add_argument("--no-filings", action="store_true")
    a = ap.parse_args()
    today = datetime.date.today()

    try:
        prev = json.load(open(OUT, encoding="utf-8"))
    except Exception:
        prev = {}
    ledger = load_ledger()
    monthly = (prev.get("govt") or {}).get("monthly") or []
    log = []

    if not a.no_fetch:
        if a.seed_budget:
            print("Seeding budget archive ...")
            ledger = seed_budget(ledger, dict(BAG_ARCHIVE, current=BAG_CURRENT))
        else:
            print("Current budget document ...")
            ledger = seed_budget(ledger, {"current": BAG_CURRENT})
        json.dump(ledger, open(LEDGER, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
        print("CGA monthly accounts ...")
        monthly, nfetch = update_cga(monthly, today)
        log.append("cga fetched %d, stored %d months" % (nfetch, len(monthly)))
    annual = build_annual(ledger, monthly)

    official = {}
    try:
        official = json.load(open(OFFICIAL, encoding="utf-8"))
    except Exception as e:
        print(f"  (official ledger unavailable: {str(e)[:60]})")

    filings = (prev.get("private") or {}).get("filings")
    if not a.no_filings:
        print("Listed-company filings ...")
        filings = build_filings()
        log.append("filings: all n={} capex={}".format(filings["all"]["n"], filings["all"]["capex"]))

    ist = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=5, minutes=30)))  # CI runners are UTC
    out = {
        "updated": ist.strftime("%Y-%m-%dT%H:%M IST"),
        "govt": {
            "annual": annual,
            "monthly": monthly,
            "src": {
                "budget": "indiabudget.gov.in Budget at a Glance (per-document provenance in scripts/capex_budget_ledger.json)",
                "monthly": "cga.nic.in Union Government Accounts at a Glance (unaudited provisional, cumulative from April)",
            },
        },
        "private": {"filings": filings, "official": official},
        "gdp": load_gdp(),
    }
    # never publish a shrunken feed
    if prev.get("govt", {}).get("monthly") and len(monthly) < len(prev["govt"]["monthly"]):
        print("ABORT: monthly series would shrink %d -> %d" % (len(prev["govt"]["monthly"]), len(monthly)))
        sys.exit(1)
    json.dump(out, open(OUT, "w", encoding="utf-8"), separators=(",", ":"), ensure_ascii=False)
    print(
        "Wrote %s: %d annual rows, %d months, filings %s; %s"
        % (OUT, len(annual), len(monthly), "yes" if filings else "no", "; ".join(log))
    )


if __name__ == "__main__":
    main()
