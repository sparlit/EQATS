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
"""Annual employee HEADCOUNT for Nifty-500 stocks, from each company's OWN annual report on BSE.

Why annual reports: India does not report employee *count* quarterly (quarterly XBRL carries only
EmployeeBenefitExpense, a rupee cost). The headcount lives in the annual report, in three places,
tried in this order of value:

  review  the multi-year "Financial Highlights / Ten-Year Review" table — one row of employee
          counts aligned to a row of fiscal-year headers → many FYs from ONE filing (best case).
  brsr    the BRSR "Employees and workers" table (Permanent D / Other-than-permanent E /
          Total D+E, split Male/Female) — SEBI-mandated for top-1000 by mcap from FY2023 →
          structured, exact, one FY per report.
  s197    the Board's-Report Section 197 line "number of permanent employees on the rolls" —
          one FY per report, covers the pre-BRSR years too.

Text layer first (PyMuPDF). A report with no text layer is a scan → flagged for the vision route
(not done here). Source of every number is recorded: filing FY, page, method. No guessing — a FY
we cannot read stays absent.

Fetch/list logic adapted from kpi_docs.py (the INSIGHTS-card BSE document ladder). Depends only on
scripts/bse_scrips.json (symbol→BSE code) + PyMuPDF.
"""
import gzip
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPS = os.path.join(HERE, "bse_scrips.json")
CACHE = os.environ.get("HC_DOC_CACHE") or os.path.join(os.path.expanduser("~"), ".cache", "kpi_docs")
LEDGER_DIR = os.path.join(HERE, "headcount")

HDR = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124 Safari/537.36",
    "Referer": "https://www.bseindia.com/",
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://www.bseindia.com",
}
PACE = {"last": 0.0}
MIN_GAP = 0.6


def _get(url, timeout=60, binary=False):
    wait = MIN_GAP - (time.time() - PACE["last"])
    if wait > 0:
        time.sleep(wait)
    PACE["last"] = time.time()
    req = urllib.request.Request(url, headers=HDR)
    r = urllib.request.urlopen(req, timeout=timeout)
    raw = r.read()
    if r.headers.get("Content-Encoding") == "gzip":
        raw = gzip.decompress(raw)
    return raw if binary else raw.decode("utf-8", "replace")


_SCRIPS = None


_MASTER = None


def scripcode(sym):
    """BSE scrip code: bse_scrips.json first, then _bse_master_all.json (delisted/merged names such
    as HDFC, MINDTREE, IDFC, PEL keep their code there and their FY20-23 reports still exist on BSE)."""
    global _SCRIPS, _MASTER
    if _SCRIPS is None:
        _SCRIPS = json.load(open(SCRIPS, encoding="utf-8")).get("by_id", {})
    v = _SCRIPS.get(sym)
    if v:
        return int(v)
    if _MASTER is None:
        mp = os.path.join(HERE, "_bse_master_all.json")
        _MASTER = {}
        if os.path.exists(mp):
            for x in json.load(open(mp, encoding="utf-8")):
                if x.get("scrip_id") and x.get("SCRIP_CD"):
                    _MASTER.setdefault(x["scrip_id"], x["SCRIP_CD"])
    v = _MASTER.get(sym)
    return int(v) if v else None


def annual_reports(sym):
    """[{fy:int(FY-end year), url, att}] newest first, from BSE AnnualReport_New."""
    code = scripcode(sym)
    if not code:
        return []
    j = None
    for attempt in range(3):  # the BSE list endpoint drops connections intermittently — retry
        try:
            j = json.loads(_get("https://api.bseindia.com/BseIndiaAPI/api/AnnualReport_New/w?scripcode=%d" % code))
            break
        except Exception as ex:
            if attempt == 2:
                print(f"  annual_reports {sym} ERR {str(ex)[:90]}", file=sys.stderr)
                return []
            time.sleep(1.5 * (attempt + 1))
    out, seen = [], set()
    for t in j.get("Table") or []:
        url = (t.get("PDFDownload") or "").replace("\\", "")
        yr = str(t.get("Year") or "")
        if not url.lower().endswith(".pdf") or not re.match(r"^\d{4}$", yr):
            continue
        att = url.rsplit("/", 1)[-1]
        if att in seen:
            continue
        seen.add(att)
        out.append({"fy": int(yr), "url": url, "att": att})
    out.sort(key=lambda d: d["fy"], reverse=True)
    # one report per FY (BSE lists duplicates / integrated-report variants for a year)
    byfy, dedup = set(), []
    for d in out:
        if d["fy"] in byfy:
            continue
        byfy.add(d["fy"])
        dedup.append(d)
    return dedup


BASES = (
    "https://www.bseindia.com/xml-data/corpfiling/AttachLive/",
    "https://www.bseindia.com/xml-data/corpfiling/AttachHis/",
)


def _valid_pdf(raw):
    return raw is not None and len(raw) > 2000 and raw[:5] == b"%PDF-"


def fetch(doc, sym="_"):
    att = doc["att"]
    d = os.path.join(CACHE, sym)
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, att)
    if os.path.exists(path) and os.path.getsize(path) > 2000:
        return path
    urls = [doc["url"]] if doc.get("url") else []
    urls += [b + att for b in BASES]
    urls.append("https://www.bseindia.com/stockinfo/AnnPdfOpen.aspx?Pname=" + att)
    for u in urls:
        try:
            raw = _get(u, timeout=180, binary=True)
        except urllib.error.HTTPError as ex:
            if ex.code not in (404, 400):
                print("  fetch %s HTTP %d" % (att, ex.code), file=sys.stderr)
            continue
        except Exception as ex:
            print(f"  fetch {att} ERR {str(ex)[:90]}", file=sys.stderr)
            continue
        if _valid_pdf(raw):
            with open(path, "wb") as fh:
                fh.write(raw)
            return path
    return None


def page_texts(path):
    import fitz

    doc = fitz.open(path)
    return [(i + 1, pg.get_text("text")) for i, pg in enumerate(doc)]


# ---------------------------------------------------------------------------- extraction


def _int(s):
    s = s.replace(",", "").replace(" ", "").strip()
    return int(s) if s.isdigit() else None


NUM = re.compile(r"\d[\d,]{1,}")
FY_WORD = re.compile(r"^\(?(20\d{2})[-–/](\d{2})\)?[#*^~$≠°+@]?$")  # one FY-token word: 2025-26 / 2019-20
LABEL_WORD = re.compile(r"employee|manpower|head\s?count|work\s?force|headcount", re.IGNORECASE)
# labels that name a NON-count employee metric — never a headcount row
LABEL_BAD = re.compile(
    r"cost|benefit|expense|welfare|remuneration|ratio|turnover|attrition|"
    r"per\s|productivity|revenue|profit|salar|wages|₹|crore|lakh|million|%|"
    r"trained|training|hours|added|hired|separation",
    re.IGNORECASE,
)


def _fy_of(word):
    m = FY_WORD.match(word.strip())
    if not m:
        return None
    return int(m.group(1)) + 1 if m.group(2) == "00" else int(m.group(1)[:2] + m.group(2))


def _numword(w):
    w = w.strip().rstrip(".*^~#$≠°+@")
    if re.fullmatch(r"\d[\d,]*", w):
        try:
            return int(w.replace(",", ""))
        except ValueError:
            return None
    return None


def extract_review(doc):
    """Multi-year 'Financial Highlights / N-Year Review' employee row, reconstructed from word
    geometry: find the FY-header row, find an employee-labelled row, align its numeric cells to the
    year columns by x-position. Returns ({fy:count}, page_no, label). One filing → many FYs."""
    from collections import defaultdict

    best = None
    for pno in range(len(doc)):
        words = doc[pno].get_text("words")  # (x0,y0,x1,y1, word, block, line, wordno)
        if len(words) < 8:
            continue
        rows = defaultdict(list)
        for w in words:
            rows[round((w[1] + w[3]) / 2.0 / 3.0)].append(w)  # bucket by y-centre (~3px)
        # FY header row = the row with the most FY-token words (>=4 → a review table, not prose)
        hdr = None
        for ws in rows.values():
            cols = [((w[0] + w[2]) / 2.0, _fy_of(w[4])) for w in ws]
            cols = [(x, fy) for x, fy in cols if fy and 2005 <= fy <= date.today().year + 1]
            if len(cols) >= 4 and (hdr is None or len(cols) > len(hdr)):
                hdr = sorted(cols)
        if not hdr:
            continue
        # employee-count rows: leftmost cells name an employee metric, numeric cells to the right
        for ws in rows.values():
            ws = sorted(ws, key=lambda w: w[0])
            label = " ".join(w[4] for w in ws[:5])
            if not LABEL_WORD.search(label) or LABEL_BAD.search(label):
                continue
            nums = [((w[0] + w[2]) / 2.0, _numword(w[4])) for w in ws]
            nums = [(x, n) for x, n in nums if n is not None and 20 <= n <= 8_000_000]
            if len(nums) < 3:
                continue
            got = {}
            for x, n in nums:
                fy = min(hdr, key=lambda c: abs(c[0] - x))[1]  # nearest year column by x
                got.setdefault(fy, n)  # first (leftmost) wins per column
            if len(got) >= 3 and (best is None or len(got) > len(best[0])):
                best = (got, pno + 1, re.sub(r"\s+", " ", label).strip()[:40])
    return best or ({}, None, "")


BRSR_ANCHOR = re.compile(r"Employees\s+and\s+workers", re.IGNORECASE)
# STRICT adjacency (Total-A  Male-No  Male-%  Female-No, optionally an Others col after) — only the
# real table row prints numbers right after the label, so this rejects layout-separated stray digits
# (years, question numbers). Column LETTER is flexible ([A-H]) because a filer with an "Others" gender
# column shifts D/E/(D+E) → E/F/(E+F) (HCLTech). A table whose text layout separates label from number
# won't match → that FY ships nothing and is queued for the LLM/vision reader, never guessed.
_L = r"[A-H]"
_N = r"(\d[\d,]*)"  # a count cell — 1+ digits (a holding company can have 6 employees: MFSL "10 6 60% 4 40%")
_ROW = _N + r"\s+" + _N + r"\s+[\d.]+\s*%?\s+" + _N
# (?<!than ) so the "Permanent" inside "Other than Permanent" never matches a permanent row — else a
# dash in "Permanent (F) -" lets the regex fall through to "Other than Permanent (G) 63,297" and read
# contractual workers as permanent, inflating on-roll (Bharti Airtel: 14,322 → 77,619).
BRSR_PERM = re.compile(r"(?<!than )Permanent\s*\(\s*" + _L + r"\s*\)\s+" + _ROW, re.IGNORECASE)
BRSR_OTHER = re.compile(r"Other\s+than\s+[Pp]ermanent\s*\(\s*" + _L + r"\s*\)\s+" + _N, re.IGNORECASE)
BRSR_TOTE = re.compile(r"Total\s+employees\s*\(\s*" + _L + r"\s*\+\s*" + _L + r"\s*\)\s+" + _ROW, re.IGNORECASE)
BRSR_WPERM = re.compile(r"(?<!than )Permanent\s*\(\s*" + _L + r"\s*\)\s+" + _N, re.IGNORECASE)
BRSR_WTOT = re.compile(r"Total\s+workers\s*\(\s*" + _L + r"\s*\+\s*" + _L + r"\s*\)\s+" + _N, re.IGNORECASE)


def _parse_brsr_zone(zone):
    """Parse one 'Employees and workers' table region → record, or None if the strict rows aren't there."""
    te = BRSR_TOTE.search(zone)
    pe = BRSR_PERM.search(zone[: te.start()] if te else zone)  # employee-permanent row (before total)
    if not (te or pe):
        return None
    rec = {}
    if pe:
        rec["emp_perm"] = _int(pe.group(1))
    om = BRSR_OTHER.search(zone[: te.start()] if te else zone)
    if om:
        rec["emp_other"] = _int(om.group(1))
    if te:
        rec["emp_total"] = _int(te.group(1))
        m, f = _int(te.group(2)), _int(te.group(3))
        if m and f and rec["emp_total"] and abs((m + f) - rec["emp_total"]) <= max(3, rec["emp_total"] * 0.02):
            rec["male"], rec["female"] = m, f
    elif rec.get("emp_perm") is not None:
        rec["emp_total"] = rec["emp_perm"] + (rec.get("emp_other") or 0)
    # workers section: the 6 Workers rows sit right after the total-employees row and BEFORE the
    # 'differently-abled employees and workers' sub-table (whose Permanent(D) would otherwise be
    # mis-read as permanent workers, inflating on-roll for pure-services filers). Bound tightly.
    wzone = zone[te.end() :] if te else ""
    cut = re.search(r"differently|disabilit|disabled", wzone, re.IGNORECASE)
    wzone = wzone[: cut.start()] if cut else wzone[:400]
    wt = BRSR_WTOT.search(wzone)
    if wt:
        rec["wrk_total"] = _int(wt.group(1))
    # permanent-workers only counts when the Workers section actually names it (else '-' / absent)
    wp = BRSR_WPERM.search(wzone[: wt.start()] if wt else wzone)
    if wp:
        rec["wrk_perm"] = _int(wp.group(1))
    if rec.get("emp_perm") is not None:
        rec["onroll_perm"] = rec["emp_perm"] + (rec.get("wrk_perm") or 0)
    # sanity: total >= permanent (total = permanent + other). Floor is tiny on purpose — a listed
    # holding company can genuinely run on a handful of staff (Max Financial: 10). The differently-abled
    # sub-table is kept out by extract_brsr's heading check, not by size.
    et, ep = rec.get("emp_total"), rec.get("emp_perm")
    if et and ep and et < ep:  # a half-parsed row → distrust
        return None
    if (et or 0) < 3 and (ep or 0) < 3:
        return None
    return rec


# The differently-abled sub-table's heading starts "Differently abled employees…"; the MAIN table's
# standard heading is "Employees and workers (including differently abled)" — so only a "differently"
# NOT preceded by "including " marks the sub-table.
_SUBTABLE = re.compile(r"(?<!including )(?<!including\n)differently|disabilit|disabled", re.IGNORECASE)


def extract_brsr(pages):
    """Best BRSR employees table across the report → (record, page). ANCHOR-FREE: the table is found by
    its own row signature ("Permanent (D) n n % n" / "Total employees (D+E) …"), because the heading
    varies — TCS writes "Employees (including differently abled)", never "Employees and workers", and
    the old anchor missed it entirely (perfect rows, zero matches). Among candidates (differently-abled
    sub-table excluded by its heading) the main workforce table has the largest total."""
    cands = []
    for pno, txt in pages:
        seeds = sorted({m.start() for m in BRSR_TOTE.finditer(txt)} | {m.start() for m in BRSR_PERM.finditer(txt)})
        last = -10_000
        for s in seeds:
            if s - last < 400:  # same table, already seeded
                continue
            last = s
            zone = txt[max(0, s - 900) : s + 1600]
            pm = BRSR_PERM.search(zone)
            head = zone[max(0, (pm.start() if pm else 0) - 260) : (pm.start() if pm else 0)]
            if _SUBTABLE.search(head):
                continue
            rec = _parse_brsr_zone(zone)
            if rec:
                cands.append((rec.get("emp_total") or rec.get("emp_perm") or 0, rec, pno))
    if not cands:
        return {}, None
    _, rec, pno = max(cands, key=lambda c: c[0])
    return rec, pno


# Pre-BRSR headcount phrasings (Directors'/Board's Report §197 Rule 5, and BRR Principle 3).
# Ordered most-specific → least; each yields ONE number for the report's own FY. Tight patterns
# only — a free-text miss must stay absent, never a guessed number (LABEL_BAD context rejects
# remuneration/ratio lines). The number is captured with its wording so basis stays transparent.
PRE2023 = [
    (
        "perm_rolls",
        re.compile(
            r"(\d[\d,]{2,})\s+permanent\s+employees\b[^.]{0,50}?(?:on\s+the\s+rolls|as\s+(?:on|at|of)|were|there\s+were)",
            re.IGNORECASE,
        ),
    ),
    (
        "perm_rolls",
        re.compile(r"(?:there\s+were|were|had|employed)\s+(\d[\d,]{2,})\s+permanent\s+employees", re.IGNORECASE),
    ),
    (
        "num_perm",
        re.compile(
            r"(?:number|no\.?|strength)\s+of\s+permanent\s+employees[^.\d]{0,45}?(?:was|were|is|are|stood\s+at|of|:)\s*(\d[\d,]{2,})",
            re.IGNORECASE,
        ),
    ),
    ("on_rolls", re.compile(r"(\d[\d,]{2,})\s+employees\s+(?:were\s+)?on\s+the\s+rolls", re.IGNORECASE)),
    (
        "on_rolls",
        re.compile(
            r"employees\s+on\s+the\s+rolls\s+of\s+the\s+company[^.\d]{0,45}?(?:was|were|is|are|stood\s+at|:)\s*(\d[\d,]{2,})",
            re.IGNORECASE,
        ),
    ),
    (
        "strength",
        re.compile(
            r"employee\s+strength[^.\d]{0,45}?(?:was|were|is|of|at|stood\s+at|:)\s*(\d[\d,]{2,})", re.IGNORECASE
        ),
    ),
    # NB: bare "total number of employees ... N" is NOT here — it hits demographic breakdown tables
    # ("… by age group (numbers) 2,941 …"); only sentence-form "permanent employees on the rolls".
]
# a pre-2023 text value is trusted only if it sits within this band of the nearest known FY value
PRE2023_BAND = (0.5, 2.0)


def extract_pre2023(pages):
    """First confident pre-BRSR headcount match → (count, page, method). Rejects money/ratio lines."""
    for method, rx in PRE2023:
        for pno, txt in pages:
            for m in rx.finditer(txt):
                ctx = txt[max(0, m.start() - 60) : m.end() + 20]
                if LABEL_BAD.search(ctx):  # ₹/crore/remuneration/ratio/%/median … not a headcount
                    continue
                n = _int(m.group(1))
                if n and 20 <= n <= 5_000_000:
                    return n, pno, method
    return None, None, None


def process(sym, want_fys, max_reports=3, verbose=True):
    """Fill headcount for want_fys (set of FY-end years). Returns ledger dict."""
    ars = annual_reports(sym)
    led = {"sym": sym, "bse": scripcode(sym), "fy": {}, "scanned": [], "reports_read": []}
    if not ars:
        led["note"] = "no annual reports on BSE"
        return led
    # newest reports first; the newest usually carries the multi-year review + BRSR
    for a in ars[:max_reports]:
        # stop early if every wanted FY is already covered
        if want_fys and all(y in led["fy"] for y in want_fys):
            break
        p = fetch(a, sym)
        if not p:
            continue
        try:
            import fitz

            doc = fitz.open(p)
            pages = [(i + 1, pg.get_text("text")) for i, pg in enumerate(doc)]
        except Exception as ex:
            if verbose:
                print("  {} FY{} pagetext ERR {}".format(sym, a["fy"], str(ex)[:60]))
            continue
        n_text = sum(1 for _, t in pages if t.strip())
        if n_text < max(3, len(pages) * 0.3):
            led["scanned"].append(a["fy"])
            led["reports_read"].append({"fy": a["fy"], "att": a["att"], "scan": True})
            doc.close()
            continue
        led["reports_read"].append({"fy": a["fy"], "att": a["att"], "pages": len(pages)})
        # 1) multi-year review — one filing → many FYs, BUT table orientation varies too much for a
        # safe geometric parse (transposed 20-yr tables misalign). Disabled until the LLM route reads
        # it; we never emit a guessed cell. Pre-2023 years come from the Board's-Report line (s197).
        rev, rpage, _note = ({}, None, "")  # extract_review(doc) — enable only behind the LLM reader
        doc.close()
        for fy, n in rev.items():
            if fy not in led["fy"]:
                led["fy"][fy] = {
                    "count": n,
                    "basis": "review",
                    "src": {"fy": a["fy"], "page": rpage, "method": "review"},
                }
        # 2) BRSR — structured breakdown for THIS report's own FY (attach, don't clobber a review cell)
        brsr, bpage = extract_brsr(pages)
        if brsr:
            total_incl = (brsr.get("emp_total") or 0) + (brsr.get("wrk_total") or 0)
            detail = {
                k: brsr.get(k)
                for k in (
                    "emp_perm",
                    "emp_other",
                    "emp_total",
                    "wrk_perm",
                    "wrk_total",
                    "onroll_perm",
                    "male",
                    "female",
                )
            }
            detail["total_incl_workers"] = total_incl or None
            cur = led["fy"].get(a["fy"])
            if cur and cur.get("basis") == "review":
                cur["brsr"] = detail  # keep consistent review series; record BRSR for reconciliation
            else:
                # headline = permanent on-roll (emp_perm+wrk_perm) — the basis that reconciles to the
                # company's own "Number of Employees"; total_workforce (incl contractual) is the toggle
                led["fy"][a["fy"]] = {
                    "count": brsr.get("onroll_perm") or brsr.get("emp_total") or brsr.get("emp_perm"),
                    "total_workforce": detail["total_incl_workers"],
                    "basis": "brsr",
                    "brsr": detail,
                    "src": {"fy": a["fy"], "page": bpage, "method": "brsr"},
                }
        # 3) pre-BRSR Board's-Report §197 text line — kept ONLY as an UNVERIFIED candidate in fy_text,
        # never in the shipped series. A single wrong-but-plausible sentence (HCLTech's regional
        # "119,035 employees on the rolls" vs the real 227,181 BRSR figure) must not reach the page;
        # these FYs are filled later by the LLM/vision reader. Recorded for that pass.
        if a["fy"] not in led["fy"] and a["fy"] not in led.get("fy_text", {}):
            n, spage, meth = extract_pre2023(pages)
            if n:
                led.setdefault("fy_text", {})[a["fy"]] = {
                    "count": n,
                    "basis": meth,
                    "src": {"fy": a["fy"], "page": spage, "method": meth},
                }
    return led


def n500_universe():
    """Survivorship-free Nifty-500 = union of members across _wb_n500_snaps.json snapshots >= 2020,
    minus DUMMY* placeholders, keeping only BSE-mapped symbols. Sorted."""
    snaps = json.load(open(os.path.join(HERE, "_wb_n500_snaps.json")))
    uni = set()
    for d, mem in snaps.items():
        if d >= "2020-01-01":
            uni |= set(mem)
    return sorted(s for s in uni if not s.startswith("DUMMY") and scripcode(s))


def main():
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("syms", nargs="*")
    ap.add_argument("--universe", action="store_true", help="sweep the whole survivorship-free N500")
    ap.add_argument("--skip-existing", action="store_true", help="skip symbols whose ledger already exists")
    ap.add_argument("--limit", type=int, default=0, help="cap number of symbols this run")
    ap.add_argument("--since-fy", type=int, default=2020, help="fill FY-end years >= this")
    ap.add_argument("--max-reports", type=int, default=3)
    ap.add_argument("--save", action="store_true", help="write scripts/headcount/<SYM>.json")
    a = ap.parse_args()
    want = set(range(a.since_fy, date.today().year + 1))
    if a.save or a.universe:
        os.makedirs(LEDGER_DIR, exist_ok=True)
    syms = list(a.syms)
    if a.universe:
        syms = n500_universe()
    if a.skip_existing:
        syms = [s for s in syms if not os.path.exists(os.path.join(LEDGER_DIR, s + ".json"))]
    if a.limit:
        syms = syms[: a.limit]
    print("processing %d symbols (max_reports=%d)" % (len(syms), a.max_reports), flush=True)
    for s in syms:
        led = process(s, want, max_reports=a.max_reports)
        got = sorted(led["fy"])
        cov = [y for y in sorted(want) if y in led["fy"]]
        print(
            "%-12s BSE %-7s  FYs got: %s  | 2020+ cov %d/%d %s%s"
            % (
                s,
                led.get("bse"),
                got,
                len(cov),
                len(want),
                "SCAN:{}".format(led["scanned"]) if led["scanned"] else "",
                "  " + led.get("note", ""),
            ),
            flush=True,
        )
        for y in got:
            c = led["fy"][y]
            extra = ""
            b = c.get("brsr") or (c if c.get("basis") == "brsr" else None)
            if b:
                extra = "  {{emp_perm={} +wrk_perm={} =onroll={} | emp_total={} +wrk={} M={} F={}}}".format(
                    b.get("emp_perm"),
                    b.get("wrk_perm"),
                    b.get("onroll_perm"),
                    b.get("emp_total"),
                    b.get("wrk_total"),
                    b.get("male"),
                    b.get("female"),
                )
            print("     FY%d: %-8s [%s%s p%s]%s" % (y, c["count"], c.get("basis"), "", c["src"]["page"], extra))
        if a.save or a.universe:
            json.dump(led, open(os.path.join(LEDGER_DIR, s + ".json"), "w"), indent=1, default=str)


if __name__ == "__main__":
    main()
