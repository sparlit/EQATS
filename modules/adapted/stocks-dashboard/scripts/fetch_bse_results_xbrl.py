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
"""Quarterly-results XBRL from BSE → fill-only numbers for BSE-only stocks AND for NSE stocks whose quarter NSE never
served (runbook §178). Replaces Claude-vision reads wherever the company filed XBRL on BSE (Jun-2018 onward).

ROUTE (measured 2026-09-26, memory reference-bse-results-xbrl-route):
  list   api.bseindia.com/BseIndiaAPI/api/Result_Arch_ng/w?scrip_cd=<code>  → {"Table":[{stand_xbrl_link | conso_xbrl_link,
         Filing_Date_Time, Quarter, qtr, Status, …}]}
  file   www.bseindia.com + link  (/XBRLFILES/FourOneUploadDocument/… to Dec-2024, /XBRLFILES/IFIndasUploadDocument/… 2025+)
Plain urllib with the full standard browser header set (bse_fetch.HEADERS, §181), one request at a time. When the api
answers 403 the run prints BSE-REFUSED and writes nothing.

IDENTITY comes from the FILE, not the listing: the XML's ScripCode must equal the requested scrip; its OneD context gives
the period of a main-board filing (3-month = quarter); NatureOfReport gives the basis. Values: build_fundamentals.
xbrl_profit (PAT) + build_revop.xbrl_revop (revenue/op/ebit) + build_xbrl_extra.parse_file (detail) — the same parsers
every NSE filing goes through.

SME BOARD (groups M/MT/MS, runbook §194): the period comes from the ARITHMETIC of the year's two filings, never from a
label. BSE SME half-year files label OneD Jul-Sep (Yearly files Jan-Mar) while the money can be the 6-month half, an
all-zero placeholder, or the whole year (SUPERSHAKT Sep-22 OneD = FourD = 359.29 = its H1; DHARNI Sep-23 OneD 0.00 /
FourD 4.79; MAIDEN Mar-24 OneD = FourD = 236.1 = the year). H1 = the Sep filing's Apr-Sep figure (OneD or FourD), FY =
the Mar filing's FourD, H2 = its OneD when H1 + H2 == FY closes to the filing's rounding, else FY - H1 when that OneD
repeats the year. Proven halves are stored with h=1 and their proof ("pf") and carry no P&L detail unless the file's
OneD IS that half; a Sep filing that reports a separate Jul-Sep quarter makes that year quarterly; everything else is
HELD (printed, never stored) until the year closes — the §181d rule for NSE SME half-years.

TARGETS
  • scripts/bse_xbrl_nse_targets.json {NSE_SYM: {"code": scrip, "q": [qe…]}} — NSE main-board point-in-time quarters NSE
    never listed (built by the §175 coverage tool; ISIN-joined to the BSE scrip).
  • every BSE-only scrip in docs/bse_universe.json: quarters 2020-03-31 → latest due missing from bse_fundamentals.
State: scripts/_bse_xbrl_state.json {code: last YYYYMMDD listed} — a scrip is re-listed at most every 20 days.

Two stages so an unattended CI push can never clobber a concurrent writer (the minified-JSON rule):
  --fetch [--budget N] [--out FILLS] [--codes C1,C2]   list + download + parse → FILLS json (touches no store)
  --apply FILLS                        fill-only merge into docs/bse_fundamentals.json, docs/sf_fundamentals.json,
                                       docs/sf_revop.json, scripts/revop_fundamentals.json, scripts/xbrl_extra.json.gz
  --from-dir DIR                       offline test: treat DIR's *.xml as downloaded files (listing dates from DIR's
                                       list_<scrip>.json when present, else the file-name stamp alone)
  --heal-sme DIR [--dry]               re-decide every stored bse-xbrl cell of an SME scrip from DIR's files (§194):
                                       h=1 + proof on proven halves; a value is replaced only when the proof shows the
                                       stored one is not the half (placeholder zeros, the whole year) — old kept in "was"
"""
import contextlib
import datetime
import gzip
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DOCS = os.path.join(ROOT, "docs")
sys.path.insert(0, HERE)

LIST = "https://api.bseindia.com/BseIndiaAPI/api/Result_Arch_ng/w?scrip_cd=%s"
WWW = "https://www.bseindia.com"
STATE = os.path.join(HERE, "_bse_xbrl_state.json")
NSE_T = os.path.join(HERE, "bse_xbrl_nse_targets.json")
FLOOR = 20200331
RELIST_DAYS = 20
MAX_FILES = int(os.environ.get("BSE_XBRL_MAX_FILES") or 600)  # downloads per run, all scrips together
DL = [0]
RE_CTX = re.compile(
    r'<xbrli:context id="OneD">.*?<xbrli:startDate>([\d-]+)</xbrli:startDate>\s*<xbrli:endDate>([\d-]+)<', re.DOTALL
)
RE_SCRIP = re.compile(r"<in-(?:capmkt|bse-fin):ScripCode[^>]*>\s*([^<\s]+)\s*<")
RE_NAT = re.compile(r"NatureOfReportStandaloneConsolidated[^>]*>\s*([^<]+)<")
RE_ISIN = re.compile(r"<in-(?:capmkt|bse-fin):ISIN[^>]*>\s*([A-Z0-9]{12})\s*<")
RE_END4 = re.compile(r'<xbrli:context id="FourD">.*?<xbrli:endDate>([\d-]+)<', re.DOTALL)
SME_GROUPS = ("M", "MT", "MS")  # BSE SME board groups (docs/bse_universe.json col 4)


class Refused(RuntimeError):
    pass


def get(url, want_json=False):
    import bse_fetch as B  # the shared, full standard header set (§179)

    h = dict(B.HEADERS)
    h["Accept"] = "application/json, text/plain, */*" if want_json else "*/*"
    req = urllib.request.Request(url, headers=h)
    try:
        r = urllib.request.urlopen(req, timeout=60)
        b = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            import gzip as _gz

            b = _gz.decompress(b)
    except urllib.error.HTTPError as e:
        if e.code in (401, 403, 429):
            raise Refused("HTTP %d %s" % (e.code, url))
        raise
    if b[:200].lstrip().lower().startswith((b"<!doctype", b"<html")) or b"Access Denied" in b[:2000]:
        msg = f"HTML/denied body for {url}"
        raise Refused(msg)
    return b


def ymd(d):
    return int(d.strftime("%Y%m%d"))


def due_quarters(today):
    """Quarter ends from FLOOR whose results are due (qe + 45 d, Mar + 60 d)."""
    out, y = [], FLOOR // 10000
    while True:
        for md in (331, 630, 930, 1231):
            q = y * 10000 + md
            if q < FLOOR:
                continue
            lag = 60 if md == 331 else 45
            if datetime.date(y, md // 100, md % 100) + datetime.timedelta(days=lag) > today:
                return out
            out.append(q)
        y += 1


def ann_of(s):
    """Filing_Date_Time → YYYYMMDD calendar day (midnight rule, §149). Unparseable → 0 (unknown, never guessed)."""
    s = (s or "").strip()
    for fmt in (
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%d/%m/%Y %H:%M:%S",
        "%d-%m-%Y %H:%M:%S",
        "%d %b %Y %H:%M:%S",
        "%d-%b-%Y %H:%M:%S",
        "%d/%m/%Y",
        "%Y-%m-%d",
    ):
        try:
            return ymd(
                datetime.datetime.strptime(
                    s[: len(datetime.datetime.now().strftime(fmt))] if "%f" not in fmt else s, fmt
                )
            )
        except ValueError:
            continue
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    return int("".join(m.groups())) if m else 0


def ann_from_name(fname, qe, fdt):
    """Announce date for a BSE XBRL = BSE's upload stamp in the file name (Main_Ind_As_<scrip>_<DMYYYYHMMSS>.xml, digits
    NOT zero-padded), cross-checked with the listing's Filing_Date_Time. Measured 2026-09-26 (§179): the listing re-stamps
    older rows (360ONE Sep-2019: Filing_Date_Time 2020-08-28, file uploaded 22-10-2019), so the listing date alone is not
    the publication day. Rule: the listing date wins when it agrees with a valid reading of the name (±1 day); else the
    ONE name reading that falls inside (qe, qe+400 d]; else 0 = unknown, never guessed."""
    m = re.search(r"_(\d{11,14})\.xml$", fname, re.IGNORECASE)
    qd = datetime.date(qe // 10000, qe // 100 % 100, qe % 100)
    cands = set()
    if m:
        digits = m.group(1)
        for dl in (1, 2):
            for ml in (1, 2):
                d_, m_, y_ = digits[:dl], digits[dl : dl + ml], digits[dl + ml : dl + ml + 4]
                if len(y_) == 4 and d_.isdigit() and m_.isdigit():
                    try:
                        c = datetime.date(int(y_), int(m_), int(d_))
                    except ValueError:
                        continue
                    if qd < c <= qd + datetime.timedelta(days=400):
                        cands.add(c)
    lst = ann_of(fdt)
    if lst:
        ld = datetime.date(lst // 10000, lst // 100 % 100, lst % 100)
        if any(abs((ld - c).days) <= 1 for c in cands) or (not m and qd < ld <= qd + datetime.timedelta(days=400)):
            return lst
    return ymd(min(cands)) if len(cands) == 1 else 0


MON = {
    m: i for i, m in enumerate(("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"), 1)
}
QEND = {3: 31, 6: 30, 9: 30, 12: 31}


def label_qe(label):
    """Listing row 'Standalone-Sep-19;SQ2019-2020;103.00;D' → 20190930 (period end), else None. Used ONLY to decide
    which files to download — identity and period are re-read from the file itself before anything is kept."""
    m = re.match(r"\s*(?:Standalone|Consolidated)-([A-Za-z]{3})-(\d{2})\b", label or "")
    if not m or m.group(1).title() not in MON:
        return None
    mo = MON[m.group(1).title()]
    if mo not in QEND:
        return None
    return (2000 + int(m.group(2))) * 10000 + mo * 100 + QEND[mo]


def partner_qe(q):
    """The other filing of an SME fiscal year: Sep y → Mar y+1, Mar y → Sep y-1 (Jun / Dec have none)."""
    return {930: (q // 10000 + 1) * 10000 + 331, 331: (q // 10000 - 1) * 10000 + 930}.get(q % 10000)


def sme_codes():
    """Scrip codes on BSE's SME board (groups M / MT / MS in docs/bse_universe.json)."""
    try:
        rows = json.load(open(os.path.join(DOCS, "bse_universe.json"), encoding="utf-8"))["rows"]
    except (OSError, ValueError, KeyError):
        return set()
    return {str(r[0]) for r in rows if (r[4] or "") in SME_GROUPS}


def listing_dates(d, code):
    """{file name: Filing_Date_Time} from a cached Result_Arch_ng listing d/list_<code>.json (offline modes)."""
    try:
        rows = json.load(open(os.path.join(d, f"list_{code}.json"))).get("Table") or []
    except (OSError, ValueError, AttributeError):
        return {}
    out = {}
    for r in rows:
        for k in ("stand_xbrl_link", "conso_xbrl_link"):
            link = (r.get(k) or "").strip()
            if link.lower().endswith(".xml"):
                out.setdefault(link.rsplit("/", 1)[-1], r.get("Filing_Date_Time") or "")
    return out


def read_file(xml, code):
    """(qe, days, basis 'S'|'C', isin) from the file itself, or None when it is not this scrip's periodic result."""
    sc = RE_SCRIP.search(xml)
    if not sc or sc.group(1).strip() != str(code):
        return None
    m = RE_CTX.search(xml)
    if not m:
        return None
    s, e = (datetime.date.fromisoformat(x) for x in m.groups())
    nat = RE_NAT.search(xml) or [None, ""]
    nat = nat.group(1).strip().lower() if hasattr(nat, "group") else ""
    basis = "C" if nat.startswith("consol") else "S"
    isin = RE_ISIN.search(xml)
    return ymd(e), (e - s).days + 1, basis, (isin.group(1) if isin else "")


def parse_values(xml, basis):
    import build_fundamentals as B
    from build_revop import xbrl_revop

    hint = "Consolidated" if basis == "C" else "Standalone"
    try:
        std, con = B.xbrl_profit(xml, basis_hint=hint)
    except Exception:
        std = con = None
    try:
        rs, os_, es, rc, oc, ec, fin = xbrl_revop(xml, basis_hint=hint)
    except Exception:
        rs = os_ = es = rc = oc = ec = None
        fin = 0
    return {
        "pat_s": std,
        "pat_c": con,
        "rev_s": rs,
        "rev_c": rc,
        "op_s": os_,
        "op_c": oc,
        "ebit_s": es,
        "ebit_c": ec,
        "fin": fin,
    }


def detail(path, fname, sym, pnl=True):
    """Detail cell from build_xbrl_extra.parse_file. pnl=False drops the period money it read from OneD (P&L, EPS,
    ratios, segments) and keeps the balance sheet (an instant) and the cash flow (which carries its own length, cf_d):
    for an SME half-year row whose OneD is not that half (§194)."""
    import build_xbrl_extra as X

    try:
        r = X.parse_file(path, fname, sym_override=sym)
    except Exception:
        return None
    if not r or not (r.get("s") or r.get("c")):
        return None
    out = {"s": r.get("s") or {}, "c": r.get("c") or {}}
    if not pnl:
        out = {b: {k: v for k, v in out[b].items() if k not in pnl_keys()} for b in out}
        if not (out["s"] or out["c"]):
            return None
    return out


def pnl_keys():
    """Detail fields read from the filing's OneD period (build_xbrl_extra PNL / EPS / RATIO tables + segments)."""
    import build_xbrl_extra as X

    return set(X.PNL) | set(X.EPS) | set(X.RATIO) | {"seg"}


# ---- SME half-years: the period from the year's arithmetic (runbook §194) ------------------------------------------
def _fact(xml, name, cid):
    m = re.search(rf'<in-(?:capmkt|bse-fin):{name} contextRef="{cid}"[^>]*>\s*([-0-9.eE+]+)\s*<', xml)
    try:
        return float(m.group(1)) if m else None
    except ValueError:
        return None


def sme_column(xml, cid, basis):
    """One column (OneD / FourD) of an SME results file in RUPEES, unrounded: {"rev", "pat"} read by the nightly's own
    build_revop.metrics_for (consolidated PAT = owners, the total when that tag is missing or 0 — xbrl_profit's rule), or
    None when the column is absent or EMPTY: no revenue, no income, no expenses. A period always carries expenses; the
    DHARNI / ASARFI / SISL / EARKART / SVJ Sep files file an all-zero OneD (only ScripCode non-zero) beside the real
    half-year in FourD (measured 2026-09-27)."""
    from build_revop import metrics_for

    try:
        rev, _op, _ebit, pat_t, pat_o = metrics_for(xml, cid)
    except Exception:
        return None
    inc = _fact(xml, "Income", cid)
    if inc is None:
        inc = _fact(xml, "Revenue", cid)  # non-Ind-AS (NonBanking) spelling of total income
    if not rev and not inc and not _fact(xml, "Expenses", cid):
        return None
    pat = (pat_o or pat_t) if basis == "C" else pat_t

    def rup(v):
        return None if v is None else round(v * 1e7)  # metrics_for works in crore

    return {"rev": rup(rev), "pat": rup(pat)}


def sme_read(xml, code):
    """Both columns of an SME results file: {qe, basis, one, four} (one / four = sme_column, None = absent or empty), or
    None when it is not this scrip's periodic result. The END date of OneD names the period end — its START is what the
    SME files misstate (Jul-Sep for an Apr-Sep half); FourD, when present, must end on the same day."""
    sc = RE_SCRIP.search(xml)
    if not sc or sc.group(1).strip() != str(code):
        return None
    m = RE_CTX.search(xml)
    if not m:
        return None
    e4 = RE_END4.search(xml)
    if e4 and e4.group(1) != m.group(2):
        return None
    qe = int(m.group(2).replace("-", ""))
    if qe % 10000 not in (930, 331):
        return None
    nat = RE_NAT.search(xml)
    basis = "C" if nat and nat.group(1).strip().lower().startswith("consol") else "S"
    return {"qe": qe, "basis": basis, "one": sme_column(xml, "OneD", basis), "four": sme_column(xml, "FourD", basis)}


def _unit(v):
    """The coarsest rounding a rupee figure shows (₹1 … ₹1 lakh): SME filers round to lakhs, thousands or rupees."""
    n = abs(int(v))
    if not n:
        return 0
    for u in (100000, 10000, 1000, 100, 10):
        if n % u == 0:
            return u
    return 1


def closes(a, b, total):
    """a + b == total to within the filings' own rounding (three independently rounded figures: 1.5 units). Measured on
    the 126 cached SME files (2026-09-27): 75 same-basis years close to <= ₹1,000; EARKART FY26 to ₹43,000 against a Mar
    file rounded to ₹1 lakh (₹1.5 lakh allowed); combinations that are not a year miss by >= ₹2.9 lakh (MRP std H1 + con
    H2), most by crores."""
    if a is None or b is None or total is None:
        return False
    return abs(a + b - total) <= 1.5 * max(_unit(a), _unit(b), _unit(total), 1)


def differs(a, b):
    """Both known and unequal beyond their rounding."""
    return a is not None and b is not None and abs(a - b) > max(_unit(a), _unit(b), 1)


def sep_split(s):
    """A Sep filing whose two columns carry DIFFERENT figures (revenue; PAT when both revenues are zero — MANAS sells
    nothing), so its Apr-Sep figure is ambiguous until something closes it. Not split: OneD empty (DHARNI), OneD == FourD
    (SUPERSHAKT, MAIDEN), or one column only (the NonBanking half-year files)."""
    o, f = s["one"], s["four"]
    return bool(o and f) and (
        differs(o["rev"], f["rev"]) or (not o["rev"] and not f["rev"] and differs(o["pat"], f["pat"]))
    )


def sep_quarter(s, stored):
    """A Sep filing proven to report the Jul-Sep QUARTER in OneD: its columns split and the June quarter on file (same
    basis, any route) closes Q1 + OneD == FourD (SUDARSHAN Sep-25: 145.26 + 168.87 = 314.13; MRP 21.1 + 10.11 = 31.21).
    A split without that proof is NOT a quarter: SISL Sep-23 OneD carries ₹7,600 of expenses and nothing else."""
    q1 = stored.get(((s["qe"] // 10000) * 10000 + 630, s["basis"]))
    return sep_split(s) and q1 is not None and closes(q1, s["one"]["rev"], s["four"]["rev"])


def year_proof(s, m):
    """Prove one fiscal year from a Sep filing s and the next Mar filing m → (s's column holding the Apr-Sep figure, how)
    or None.
      'pair' H1 + H2 == FY: s's OneD or FourD revenue + m's OneD revenue == m's FourD revenue, closing to the rounding.
             A closure on a zero half (AAYUSHBULL FY23: 0 + 13.23 = 13.23) proves nothing by itself — then PAT must close
             too with all three figures non-zero (0.06 + 0.20 = 0.26). FourD is tried first (the year-to-date column).
      'fy'   m repeats the whole year in OneD (OneD == FourD) or leaves it empty, while s (same basis, not split) has one
             unambiguous Apr-Sep figure with 0 < H1 < FY: H2 = FY - H1 (MAIDEN FY24: 236.1 - 115.5 = 120.6)."""
    mo, mf = m["one"], m["four"]
    if not mf or mf["rev"] is None:
        return None
    if mo and mo["rev"] is not None:
        for c in ("four", "one"):
            h = s[c]
            if not h or not closes(h["rev"], mo["rev"], mf["rev"]):
                continue
            if (h["rev"] and mo["rev"]) or (
                h["pat"] and mo["pat"] and mf["pat"] and closes(h["pat"], mo["pat"], mf["pat"])
            ):
                return c, "pair"
    if (
        s["basis"] == m["basis"]
        and not sep_split(s)
        and (mo is None or not (differs(mo["rev"], mf["rev"]) or differs(mo["pat"], mf["pat"])))
    ):
        c = "four" if s["four"] else "one"
        h = s[c]
        if h and h["rev"] and h["rev"] > 0 and differs(mf["rev"], h["rev"]) and mf["rev"] > h["rev"]:
            return c, "fy"
    return None


def proof(s, c, m, how):
    """The arithmetic a proven half-year row carries ("pf"), in ₹ crore to 4 dp (₹1,000 — the finest rounding SME filers
    use), so build_row_periods can re-check it without the files: h1 + h2 == fy on revenue; "pat" the same identity on
    PAT (what proves a year whose revenue closure is degenerate — AAYUSHBULL FY23, MANAS FY21); "m1" the Mar filing's own
    OneD when it repeated the year ('fy'); "f" the Sep and Mar filings."""

    def c4(v):
        return None if v is None else round(v / 1e7, 4)

    h1, fy, p1, pfy = s[c]["rev"], m["four"]["rev"], s[c]["pat"], m["four"]["pat"]
    if how == "pair":
        h2, p2 = m["one"]["rev"], m["one"]["pat"]
    else:
        h2, p2 = fy - h1, (None if p1 is None or pfy is None else pfy - p1)
    pf = {
        "h1": c4(h1),
        "h2": c4(h2),
        "fy": c4(fy),
        "pat": [c4(p1), c4(p2), c4(pfy)],
        "how": how,
        "f": [s["fname"], m["fname"]],
    }
    if how == "fy":
        pf["m1"] = c4(m["one"]["rev"]) if m["one"] else None
    return pf


def stored_rows(cells):
    """{(qe, basis): revenue in rupees} of one scrip's stored bse_fundamentals cells (any route) — sep_quarter's June."""
    out = {}
    for q, c in (cells or {}).items():
        if str(q).isdigit() and isinstance(c, dict) and c.get("rev") is not None:
            out[(int(q), c.get("basis") or "S")] = round(c["rev"] * 1e7)
    return out


def sme_decide(files, stored=None):
    """Every Sep / Mar row one SME scrip's results files decide (runbook §194). files: sme_read() dicts + fname / ann;
    stored: stored_rows() of the scrip (the June quarter that proves a quarterly year).
    → [{qe, basis, how, rev, pat (rupees), src (the filing whose date the row carries), one_is_row, pf, why}]
      how 'half'    the Apr-Sep (Sep row) or Oct-Mar (Mar row) half, proven by year_proof → stored with h=1 and pf
          'quarter' a Jul-Sep / Jan-Mar quarter of a year the company reported quarterly (sep_quarter) → stored as
                    before, no h
          'hold'    nothing proves the period (reason in why) → never stored
    one_is_row: the filing's OneD holds exactly this row's figures, so the P&L detail parse_file reads from OneD is this
    row's. One decision per (qe, basis): the earliest filing that decides it (the original, not a re-filing)."""
    stored = stored or {}

    def cr(v):
        return None if v is None else round(v / 1e7, 2)

    order = sorted(files, key=lambda f: (f.get("ann") or 99999999, f.get("fname") or ""))
    seps = [f for f in order if f["qe"] % 10000 == 930]
    mars = [f for f in order if f["qe"] % 10000 == 331]
    rows = []
    for s in seps:
        y = s["qe"] // 10000 + 1
        ms = sorted((m for m in mars if m["qe"] == y * 10000 + 331), key=lambda m: m["basis"] != s["basis"])
        d = {"qe": s["qe"], "basis": s["basis"], "src": s}
        if sep_quarter(s, stored):
            d.update(how="quarter", rev=s["one"]["rev"], pat=s["one"]["pat"], one_is_row=True)
        else:
            pr = next(((m, *p) for m in ms for p in [year_proof(s, m)] if p), None)
            if pr:
                m, c, how = pr
                h1 = s[c]["rev"]
                d.update(
                    how="half",
                    rev=h1,
                    pat=s[c]["pat"],
                    pf=proof(s, c, m, how),
                    one_is_row=bool(s["one"])
                    and not (differs(s["one"]["rev"], h1) or differs(s["one"]["pat"], s[c]["pat"])),
                )
            else:
                d.update(
                    how="hold",
                    why="no Mar %d filing to close H1 + H2 = FY" % y
                    if not ms
                    else "no Mar %d filing closes H1 + H2 = FY" % y
                    + (
                        " (OneD {} ≠ FourD {})".format(cr(s["one"]["rev"]), cr(s["four"]["rev"]))
                        if sep_split(s)
                        else ""
                    ),
                )
        rows.append(d)
    for m in mars:
        y = m["qe"] // 10000
        ss = sorted((s for s in seps if s["qe"] == (y - 1) * 10000 + 930), key=lambda s: s["basis"] != m["basis"])
        d = {"qe": m["qe"], "basis": m["basis"], "src": m}
        pr = next(((s, *p) for s in ss for p in [year_proof(s, m)] if p), None)
        if any(sep_quarter(s, stored) for s in ss):
            # a quarterly year: the Mar row is the Jan-Mar quarter — never the Oct-Mar half a Yearly file may print
            mo, mf = m["one"], m["four"]
            if pr and pr[2] == "pair":
                d.update(how="hold", why="quarterly year: this Mar filing's OneD is the Oct-Mar half, not the quarter")
            elif mo and mf and mo["rev"] and mf["rev"] and differs(mf["rev"], mo["rev"]) and mo["rev"] < mf["rev"]:
                d.update(how="quarter", rev=mo["rev"], pat=mo["pat"], one_is_row=True)
            else:
                d.update(how="hold", why="quarterly year: no Jan-Mar quarter in this Mar filing")
        elif pr:
            s, c, how = pr
            h1, fy = s[c]["rev"], m["four"]["rev"]
            if how == "pair":
                d.update(how="half", rev=m["one"]["rev"], pat=m["one"]["pat"], one_is_row=True)
            else:
                p1, pfy = s[c]["pat"], m["four"]["pat"]
                d.update(how="half", rev=fy - h1, pat=None if p1 is None or pfy is None else pfy - p1, one_is_row=False)
            d["pf"] = proof(s, c, m, how)
        else:
            d.update(
                how="hold",
                why="no Sep %d filing to close H1 + H2 = FY" % (y - 1)
                if not ss
                else "no Sep %d filing closes H1 + H2 = FY" % (y - 1),
            )
        rows.append(d)
    best = {}
    for d in rows:  # earliest deciding filing wins; a hold only fills a gap
        k = (d["qe"], d["basis"])
        if k not in best or (best[k]["how"] == "hold" and d["how"] != "hold"):
            best[k] = d
    return [best[k] for k in sorted(best)]


def load_detail_keys():
    """(xbrl_extra ledger, NSE tape keys) — the detail store and the clash guard's key set."""
    xl, tape = {}, set()
    with contextlib.suppress(OSError, ValueError):
        xl = json.loads(gzip.decompress(open(os.path.join(HERE, "xbrl_extra.json.gz"), "rb").read()))
    try:
        b = gzip.decompress(open(os.path.join(DOCS, "sf_stock_data.bin"), "rb").read())
        tape = set(json.JSONDecoder().raw_decode(b[b.rfind(b'"meta":') + 7 :].decode())[0])
    except (OSError, ValueError):
        pass
    return xl, tape


def targets(today):
    """[(code, target_sym or None, kind, sme, [missing qe])] — NSE targets first, then BSE-only by mcap."""
    bf_out = os.path.join(DOCS, "bse_fundamentals.json")  # (no fetch_bse_fund import: it pulls in PyMuPDF)
    out = []
    xl, tape = load_detail_keys()
    if os.path.exists(NSE_T):
        # NSE targets shrink as they fill (2026-09-27): a listed quarter stays only while the NSE symbol still lacks its
        # profit, revenue or detail — the static list alone re-listed all 1,107 names every run after the §181c state change.
        sf = json.load(open(os.path.join(DOCS, "sf_fundamentals.json")))
        rvp = json.load(open(os.path.join(DOCS, "sf_revop.json")))
        for sym, t in sorted(json.load(open(NSE_T)).items()):
            pat = {r[0] for r in sf.get(sym, []) if r[1] is not None or r[3] is not None}
            rev = {int(q) for q, r in (rvp.get(sym) or {}).items() if r[0] is not None or r[1] is not None}
            det = {int(q) for q in (xl.get(sym) or {}) if str(q).isdigit()}
            q = sorted(int(x) for x in t["q"] if not (int(x) in pat and int(x) in rev and int(x) in det))
            if q:
                out.append((str(t["code"]), sym, "nse", False, q))
    univ = json.load(open(os.path.join(DOCS, "bse_universe.json")))["rows"]
    univ.sort(key=lambda r: r[6] or 0, reverse=True)
    px = json.load(open(bf_out, encoding="utf-8")).get("px", {}) if os.path.exists(bf_out) else {}
    # A quarter is also MISSING when its results exist but its financial DETAIL does not (2026-09-27): the older BSE
    # routes (history / vision) stored rev+PAT without detail, so the page lacked detail for those quarters and the
    # px-only test never targeted them (BSE-only detail at the latest Jun quarter: 7 of 2,159). Detail is keyed by the
    # BSE ticker; a ticker that is also an NSE tape key never takes BSE detail (apply's clash guard), so it is not chased.
    code2tk = {str(v): k for k, v in json.load(open(os.path.join(HERE, "bse_scrips.json")))["by_id"].items()}
    due = due_quarters(today)
    for r in univ:
        code = str(r[0])
        sme = (r[4] or "") in SME_GROUPS
        have = {int(q) for q in (px.get(code) or {}) if str(q).isdigit()}
        tk = code2tk.get(code)
        if tk and tk.upper() not in tape and not sme:  # SME half-year files carry no quarterly detail
            dq = {int(q) for q in (xl.get(tk) or {}) if str(q).isdigit()}
            have = {q for q in have if q in dq}
        miss = [q for q in due if q not in have and not (sme and q % 10000 in (630, 1231))]
        if miss:
            out.append((code, None, "bse", sme, miss))
    return out


def fetch(budget, fills_path, from_dir=None, codes=None):
    import xbrl_symbol

    today = datetime.date.today()
    state = json.load(open(STATE)) if os.path.exists(STATE) else {}
    bs = json.load(open(os.path.join(HERE, "bse_scrips.json")))
    code2tk = {str(v): k for k, v in bs["by_id"].items()}
    fills = []
    tmpd = os.path.join(os.environ.get("RUNNER_TEMP") or "/tmp", "bse_xbrl_dl")
    os.makedirs(tmpd, exist_ok=True)
    try:
        px_all = json.load(open(os.path.join(DOCS, "bse_fundamentals.json"), encoding="utf-8")).get("px", {})
    except (OSError, ValueError):
        px_all = {}
    tlist = targets(today)
    if codes:  # --codes: only these scrips (a manual / test run)
        tlist = [t for t in tlist if t[0] in codes]
    print(
        "targets: %d scrips (%d NSE-quarter targets, %d BSE-only)"
        % (len(tlist), sum(1 for t in tlist if t[2] == "nse"), sum(1 for t in tlist if t[2] == "bse"))
    )
    listed = files_ok = 0
    smes = sme_codes()
    if from_dir:  # offline test: every xml in the dir, code from the file
        jobs = {}
        for f in sorted(os.listdir(from_dir)):
            if f.endswith(".xml"):
                x = open(os.path.join(from_dir, f), errors="replace").read()
                sc = RE_SCRIP.search(x)
                if sc:
                    jobs.setdefault(sc.group(1).strip(), []).append((os.path.join(from_dir, f), f, ""))
        tmap = {c: (s, k, sme, q) for c, s, k, sme, q in tlist}
        for code, files in sorted(jobs.items()):
            fdt = listing_dates(from_dir, code)  # the CI path's Filing_Date_Time, when the listing is cached
            files = [(p, f, fdt.get(f, "")) for p, f, _ in files]
            s, _k, sme, q = tmap.get(code, (None, "bse", code in smes, None))
            fills += handle(code, s, sme, q, files, code2tk, xbrl_symbol)
        json.dump(fills, open(fills_path, "w"))
        print("fills (offline):", len(fills))
        return
    for code, sym, kind, sme, miss in tlist:
        if listed >= budget or DL[0] >= MAX_FILES:
            break
        st = state.get(code)  # {"d": YYYYMMDD, "q": [quarters asked]} (old form: int)
        last = int((st.get("d") if isinstance(st, dict) else st) or 0)
        asked = set(st.get("q") or []) if isinstance(st, dict) else (set(miss) if kind == "nse" else None)
        # (old int entries: an NSE target's quarters are the ones it was already asked for; a BSE-only scrip may now
        # want detail quarters it was never asked for, so it is listed again)
        if (
            last
            and (today - datetime.date(last // 10000, last // 100 % 100, last % 100)).days < RELIST_DAYS
            and asked is not None
            and set(miss) <= asked
        ):
            continue  # listed recently for these same quarters — nothing new
        try:
            body = get(LIST % code, want_json=True)
        except Refused as e:
            print("BSE-REFUSED: %s — nothing fetched this run (%d scrips listed before the refusal)" % (e, listed))
            break
        except Exception as e:
            print(f"  {code} list error {str(e)[:80]}")
            continue
        listed += 1
        try:
            rows = json.loads(body).get("Table") or []
        except ValueError:
            print(f"  {code} listing not JSON")
            continue
        want = set(miss)
        files = []
        for row in rows:
            for key in ("stand_xbrl_link", "conso_xbrl_link"):
                link = (row.get(key) or "").strip()
                if not link.lower().endswith(".xml"):
                    continue  # empty, or the bare /XBRLFILES/…/ directory (= no file)
                files.append((link, row.get("Filing_Date_Time") or "", row.get("Quarter") or ""))
        need, held_was = set(want), {}
        if sme:
            # an SME year is decided from its Sep AND Mar filings together (§194): fetch each missing quarter's partner
            # too — unless the quarter was held last time and neither filing's link set has changed since
            held_was = (st.get("held") or {}) if isinstance(st, dict) else {}

            def links(q):
                return sorted({l for l, _f, ql in files if label_qe(ql) in (q, partner_qe(q))})

            need = set()
            for q in want:
                if held_was.get(str(q)) != links(q):
                    need |= {q, partner_qe(q)}
            held_was = {k: v for k, v in held_was.items() if int(k) in want and v == links(int(k))}
        # DOWNLOAD ONLY WHAT IS MISSING (2026-09-26): the first CI run fetched every listed file (60-200 per scrip)
        # before checking the quarter — thousands of requests for a 30-scrip budget, the kind of burst BSE rate-limits.
        seen, dl, skipped = set(), [], 0
        for link, fdt, qlabel in files:
            if link in seen:
                continue
            seen.add(link)
            lq = label_qe(qlabel)
            if lq is None or lq not in need:
                skipped += 1
                continue
            if DL[0] >= MAX_FILES:
                break  # hard per-run cap on downloads (politeness, §181a)
            fname = link.rsplit("/", 1)[-1]
            p = os.path.join(tmpd, fname)
            if not os.path.exists(p):
                try:
                    open(p, "wb").write(get(WWW + link))
                except Refused as e:
                    print(f"  BSE-REFUSED file {fname}: {e}")
                    break
                except Exception:
                    continue
                time.sleep(0.5)
                DL[0] += 1
            dl.append((p, fname, fdt))
        held = {}
        if sme and not sym:
            got, held = handle_sme(code, miss, dl, code2tk, xbrl_symbol, stored_rows(px_all.get(code)))
        else:
            got = handle(code, sym, sme, miss, dl, code2tk, xbrl_symbol)
        if DL[0] < MAX_FILES:  # a scrip cut short by the per-run cap is listed again next run
            state[code] = {"d": ymd(today), "q": sorted(miss)}
            held = {**held_was, **{str(q): links(q) for q in held}}
            if held:  # held SME quarters: re-read only when a filing changes
                state[code]["held"] = held
        fills += got
        files_ok += len(dl)
        print(
            "  %s %s: %d listed files, %d downloaded for %d missing quarters, %d fills"
            % (code, sym or "", len(seen), len(dl), len(want), len(got)),
            flush=True,
        )
        time.sleep(0.8)
    json.dump(state, open(STATE, "w"), separators=(",", ":"), sort_keys=True)
    json.dump(fills, open(fills_path, "w"))
    print(
        "listed %d scrips, %d files downloaded (cap %d), %d fills → %s"
        % (listed, DL[0], MAX_FILES, len(fills), fills_path)
    )


def handle(code, sym, sme, miss, dl, code2tk, xbrl_symbol):
    """Parse downloaded files for one scrip → fill records for missing quarters only."""
    if sme and not sym:
        return handle_sme(code, miss, dl, code2tk, xbrl_symbol)[0]
    out = []
    want = set(miss) if miss else None
    for p, fname, fdt in dl:
        xml = open(p, encoding="utf-8", errors="replace").read()
        info = read_file(xml, code)
        if not info:
            continue
        qe, days, basis, _isin = info
        half = 170 <= days <= 190
        if not (80 <= days <= 100 or (half and sme)):
            continue  # FY / nine-month / YTD, or a half-year of a quarterly filer
        if want is not None and qe not in want:
            continue
        tgt = sym or xbrl_symbol.resolve("NOTLISTED", xml)  # an NSE listing of the same ISIN owns the page
        kind = "nse" if tgt else "bse"
        vals = parse_values(xml, basis)
        rec = {
            "code": code,
            "qe": qe,
            "basis": basis,
            "half": half,
            "ann": ann_from_name(fname, qe, fdt),
            "file": fname,
            "kind": kind,
            "sym": tgt or code2tk.get(code),
            **vals,
        }
        if not half and rec["sym"]:
            rec["detail"] = detail(p, fname, rec["sym"])
        out.append(rec)
    return out


def sme_files(code, dl):
    """sme_read() every downloaded file of one SME scrip (+ fname, path, xml, ann)."""
    files = []
    for p, fname, fdt in dl:
        xml = open(p, encoding="utf-8", errors="replace").read()
        f = sme_read(xml, code)
        if f:
            f.update(p=p, fname=fname, xml=xml, ann=ann_from_name(fname, f["qe"], fdt))
            files.append(f)
    return files


def handle_sme(code, miss, dl, code2tk, xbrl_symbol, stored=None):
    """SME scrip (runbook §194): the Sep and Mar filings of each year are decided TOGETHER (sme_decide), so dl carries
    the partner filing of every missing quarter; stored = stored_rows() of the scrip. → (fill records for missing
    quarters, {qe: why} held)."""
    out, held = [], {}
    want = set(miss) if miss else None

    def cr(v):
        return None if v is None else round(v / 1e7, 2)

    if stored is None:
        try:
            stored = stored_rows(
                json.load(open(os.path.join(DOCS, "bse_fundamentals.json"), encoding="utf-8"))
                .get("px", {})
                .get(str(code))
            )
        except (OSError, ValueError):
            stored = {}
    for d in sme_decide(sme_files(code, dl), stored):
        qe, basis, src = d["qe"], d["basis"], d["src"]
        if want is not None and qe not in want:
            continue
        if d["how"] == "hold":
            held.setdefault(qe, d["why"])
            continue
        tgt = xbrl_symbol.resolve("NOTLISTED", src["xml"])  # an NSE listing of the same ISIN owns the page
        if tgt and d["how"] == "half":
            held.setdefault(qe, f"half-year of NSE listing {tgt} — the NSE stores have no row-length flag")
            continue
        kind = "nse" if tgt else "bse"
        if d["how"] == "quarter":
            vals = parse_values(src["xml"], basis)  # the OneD quarter, exactly as a main-board filing
        else:
            vals = {
                "pat_s": None,
                "pat_c": None,
                "rev_s": None,
                "rev_c": None,
                "op_s": None,
                "op_c": None,
                "ebit_s": None,
                "ebit_c": None,
                "fin": 0,
            }
            b = "c" if basis == "C" else "s"
            vals["pat_" + b], vals["rev_" + b] = cr(d["pat"]), cr(d["rev"])
        rec = {
            "code": code,
            "qe": qe,
            "basis": basis,
            "half": d["how"] == "half",
            "ann": src["ann"],
            "file": src["fname"],
            "kind": kind,
            "sym": tgt or code2tk.get(code),
            **vals,
        }
        if d.get("pf"):
            rec["pf"] = d["pf"]
        if rec["sym"]:
            rec["detail"] = detail(src["p"], src["fname"], rec["sym"], pnl=d["one_is_row"])
        out.append(rec)
    for qe, why in sorted(held.items()):
        if not any(r["qe"] == qe for r in out):
            print(f"  {code} {qe} held: {why}")
    return out, {q: w for q, w in held.items() if not any(r["qe"] == q for r in out)}


def apply(fills_path):
    from build_revop import strip_lender_ebit

    fills = json.load(open(fills_path))
    P = {
        "bf": os.path.join(DOCS, "bse_fundamentals.json"),
        "sf": os.path.join(DOCS, "sf_fundamentals.json"),
        "rv": os.path.join(DOCS, "sf_revop.json"),
        "rl": os.path.join(HERE, "revop_fundamentals.json"),
        "x": os.path.join(HERE, "xbrl_extra.json.gz"),
    }
    bfd = json.load(open(P["bf"], encoding="utf-8"))
    px = bfd.setdefault("px", {})
    sf = json.load(open(P["sf"]))
    rv = json.load(open(P["rv"]))
    rl = json.load(open(P["rl"]))
    xl = json.loads(gzip.decompress(open(P["x"], "rb").read()))
    tape_keys = set()
    try:
        b = gzip.decompress(open(os.path.join(DOCS, "sf_stock_data.bin"), "rb").read())
        tape_keys = set(json.JSONDecoder().raw_decode(b[b.rfind(b'"meta":') + 7 :].decode())[0])
    except (OSError, ValueError):
        pass
    C = {"bse q": 0, "nse pat": 0, "nse rev": 0, "detail q": 0, "detail f": 0, "skip ticker clash": 0}
    for f in fills:
        qe, basis = f["qe"], f["basis"]
        pat = f["pat_c"] if basis == "C" else f["pat_s"]
        rev = f["rev_c"] if basis == "C" else f["rev_s"]
        if f["kind"] == "bse":
            cur = px.setdefault(str(f["code"]), {})
            old = cur.get(str(qe))
            if (pat is not None or rev is not None) and (
                old is None or (old.get("basis") == "S" and basis == "C" and old.get("src") == "bse-xbrl")
            ):
                if (
                    old is None or old.get("src") == "bse-xbrl"
                ):  # consolidated outranks standalone within this route only
                    rec = {"pat": pat, "ann": f["ann"] or 0, "basis": basis, "src": "bse-xbrl"}
                    if rev is not None:
                        rec["rev"] = rev
                    if f["half"]:
                        rec["h"] = 1
                        if f.get("pf"):
                            rec["pf"] = f["pf"]  # the arithmetic that proved it (§194)
                    cur[str(qe)] = rec
                    C["bse q"] += 1
        else:
            sym = f["sym"]
            ann = f["ann"] or None
            rows = sf.setdefault(sym, [])
            row = next((r for r in rows if r[0] == qe), None)
            s_, c_ = f["pat_s"], f["pat_c"]
            if row is None and (s_ is not None or c_ is not None):
                rows.append([qe, s_, ann if s_ is not None else None, c_, ann if c_ is not None else None])
                rows.sort(key=lambda r: r[0])
                C["nse pat"] += 1
            elif row is not None:
                # fill-only INCLUDING the announce slot: a stored date is never replaced (A2ZINFRA Dec-2021 carried
                # annCon 20220209 with an empty con value — the 2026-09-26 live test overwrote it with the file's 20220210)
                if s_ is not None and row[1] is None:
                    row[1] = s_
                    row[2] = row[2] or ann
                    C["nse pat"] += 1
                if c_ is not None and row[3] is None:
                    row[3] = c_
                    row[4] = row[4] or ann
                    C["nse pat"] += 1
            for store in (rv, rl):
                d = store.setdefault(sym, {})
                rr = list(d.get(str(qe)) or [None, None, None, None, None, None, 0, None, None])
                rr += [None] * (9 - len(rr))
                before = list(rr)
                for i, v in (
                    (0, f["rev_s"]),
                    (1, f["rev_c"]),
                    (2, f["op_s"]),
                    (3, f["op_c"]),
                    (4, s_),
                    (5, c_),
                    (7, f["ebit_s"]),
                    (8, f["ebit_c"]),
                ):
                    if rr[i] is None and v is not None:
                        rr[i] = v
                if f["fin"]:
                    rr[6] = 1
                strip_lender_ebit(sym, rr)
                if rr != before:
                    d[str(qe)] = rr
                    if store is rv:
                        C["nse rev"] += 1
        dt = f.get("detail")
        if dt and f["sym"]:
            if f["kind"] == "bse" and f["sym"].upper() in tape_keys:
                C["skip ticker clash"] += 1
                continue  # a BSE ticker that is also an NSE key (§76) — never mix
            cell = xl.setdefault(f["sym"], {}).setdefault(str(qe), {})
            new_q = not cell
            for b in ("s", "c"):
                for k, v in (dt.get(b) or {}).items():
                    if v is not None and k not in cell.get(b, {}):
                        cell.setdefault(b, {})[k] = v
                        C["detail f"] += 1  # FILL-ONLY: an NSE XBRL value always wins
            if not cell:
                del xl[f["sym"]][str(qe)]
            elif new_q:
                C["detail q"] += 1
    bfd["updated"] = (datetime.datetime.utcnow() + datetime.timedelta(hours=5, minutes=30)).strftime(
        "%Y-%m-%d %H:%M IST"
    )
    json.dump(bfd, open(P["bf"], "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    json.dump(sf, open(P["sf"], "w"), separators=(",", ":"))
    json.dump(rv, open(P["rv"], "w"), separators=(",", ":"))
    json.dump(rl, open(P["rl"], "w"), separators=(",", ":"))
    open(P["x"], "wb").write(gzip.compress(json.dumps(xl, separators=(",", ":")).encode(), 9))
    print("apply:", C)


def heal_sme(src_dir, dry=False):
    """Re-decide every stored bse-xbrl cell of an SME scrip (runbook §194) from the results files in src_dir (+ their
    cached list_<scrip>.json listings). Per cell, from sme_decide():
      half           proven half-year holding the proven figure → h=1 + pf (value untouched)
      half-fixed     proven half-year, and the stored figure is PROVEN not to be it: the Sep file's OneD is empty (the
                     stored 0.00 / 0.00 is that placeholder) or the Mar file's OneD repeats the year ('fy' proof) → the
                     proven figure + h=1 + pf, the old one kept in "was"; the announce date is never touched
      quarter        a quarter of a year the company reported quarterly — unchanged
      undecided      no proof either way (reason printed) — unchanged
      mismatch       decided, but the stored figure is neither the proven one nor an explained placeholder — unchanged
      (a stored 0.00 / 0.00 read off an EMPTY OneD whose own basis proves nothing is replaced by the OTHER basis's
      proven half of that quarter — DRONACHRYA Mar-24: consolidated placeholder → standalone H2 = FY - H1; "was" keeps
      the old basis too)
    Detail (scripts/xbrl_extra.json.gz, keyed by the BSE ticker): on a healed half-year row, the P&L / EPS / ratio /
    segment fields parse_file read from OneD are removed on each basis whose OneD is NOT that half or is empty in every
    filing of the quarter (balance sheet and cash flow stay)."""
    import collections

    bf_p, x_p = os.path.join(DOCS, "bse_fundamentals.json"), os.path.join(HERE, "xbrl_extra.json.gz")
    bfd = json.load(open(bf_p, encoding="utf-8"))
    px = bfd.get("px", {})
    xl = json.loads(gzip.decompress(open(x_p, "rb").read()))
    smes = sme_codes()
    code2tk = {str(v): k for k, v in json.load(open(os.path.join(HERE, "bse_scrips.json")))["by_id"].items()}
    pop = {
        c: sorted(q for q, cell in px[c].items() if isinstance(cell, dict) and cell.get("src") == "bse-xbrl")
        for c in px
        if c in smes
    }
    pop = {c: q for c, q in pop.items() if q}
    byc = collections.defaultdict(list)
    for f in sorted(os.listdir(src_dir)):
        if f.endswith(".xml"):
            sc = RE_SCRIP.search(open(os.path.join(src_dir, f), errors="replace").read())
            if sc and sc.group(1).strip() in pop:
                byc[sc.group(1).strip()].append(f)

    def cr(v):
        return None if v is None else round(v / 1e7, 2)

    def eq(a, b):
        return (a is None and b is None) or (a is not None and b is not None and abs(a - b) <= 0.011)

    pnl = pnl_keys()
    C = collections.Counter()
    xs = 0
    print(
        "SME scrips with bse-xbrl cells: %d, cells: %d, filings read from %s: %d"
        % (len(pop), sum(len(q) for q in pop.values()), src_dir, sum(len(v) for v in byc.values()))
    )
    for code in sorted(pop):
        fdt = listing_dates(src_dir, code)
        files = sme_files(code, [(os.path.join(src_dir, f), f, fdt.get(f, "")) for f in byc.get(code, [])])
        dec = {(d["qe"], d["basis"]): d for d in sme_decide(files, stored_rows(px[code]))}
        tk = code2tk.get(code)
        for qe in pop[code]:
            cell = px[code][qe]
            d = dec.get((int(qe), cell.get("basis")))
            r0, p0 = cell.get("rev"), cell.get("pat")
            same_q = [f for f in files if f["qe"] == int(qe) and f["basis"] == cell.get("basis")]
            placeholder = (
                eq(r0, 0.0) and eq(p0, 0.0) and any(f["one"] is None for f in same_q)
            )  # 0 / 0 off an EMPTY OneD
            other = dec.get((int(qe), "S" if cell.get("basis") == "C" else "C"))
            if (d is None or d["how"] == "hold") and placeholder and other and other["how"] == "half":
                d, v = other, "half-fixed"  # the other basis's proven half replaces the placeholder
                note = "stored {} {} / {} = the empty OneD placeholder → the proven {} half {} / {}".format(
                    cell.get("basis"), r0, p0, d["basis"], cr(d["rev"]), cr(d["pat"])
                )
            elif d is None or d["how"] == "hold":
                v, note = (
                    "undecided",
                    (d["why"] if d else "no {} filing of this quarter in the directory".format(cell.get("basis"))),
                )
            elif d["how"] == "quarter":
                v, note = (
                    ("quarter", "")
                    if eq(r0, cr(d["rev"])) and eq(p0, cr(d["pat"]))
                    else ("mismatch", "quarter {} / {}".format(cr(d["rev"]), cr(d["pat"])))
                )
            elif eq(r0, cr(d["rev"])) and (eq(p0, cr(d["pat"])) or d["pat"] is None):
                v, note = "half", ""
            else:
                whole_year = d["pf"]["how"] == "fy" and any(f["four"] and eq(r0, cr(f["four"]["rev"])) for f in same_q)
                v = "half-fixed" if placeholder or whole_year else "mismatch"
                note = (
                    "stored {} / {} = the {} → {} / {}".format(
                        r0, p0, "empty OneD placeholder" if placeholder else "whole year", cr(d["rev"]), cr(d["pat"])
                    )
                    if v == "half-fixed"
                    else "proven half {} / {}".format(cr(d["rev"]), cr(d["pat"]))
                )
            C[v] += 1
            print(
                "  %-6s %-10s %s %s rev %s pat %s → %-10s %s%s"
                % (
                    code,
                    tk or "",
                    qe,
                    cell.get("basis"),
                    r0,
                    p0,
                    v,
                    note,
                    ("  [{}: {} + {} = {}]".format(d["pf"]["how"], d["pf"]["h1"], d["pf"]["h2"], d["pf"]["fy"]))
                    if v.startswith("half")
                    else "",
                )
            )
            if v in ("half", "half-fixed"):
                if v == "half-fixed":
                    cell["was"] = {"rev": r0, "pat": p0}
                    if d["basis"] != cell.get("basis"):
                        cell["was"]["basis"] = cell.get("basis")
                        cell["basis"] = d["basis"]
                    cell["rev"], cell["pat"] = cr(d["rev"]), cr(d["pat"])
                cell["h"] = 1
                cell["pf"] = d["pf"]
                for b in ("s", "c"):  # the detail parse_file read from OneD, on both bases
                    xc = (xl.get(tk) or {}).get(qe, {}).get(b)
                    db = dec.get((int(qe), b.upper()))
                    fb = [f for f in files if f["qe"] == int(qe) and f["basis"] == b.upper()]
                    if xc and (
                        (db and db["how"] == "half" and not db["one_is_row"])
                        or (fb and all(f["one"] is None for f in fb))
                    ):  # OneD empty in every such filing
                        gone = [k for k in xc if k in pnl]
                        for k in gone:
                            del xc[k]
                        xs += len(gone)
    print(
        "heal_sme:", dict(C), "| xbrl_extra P&L fields removed from half-year rows whose OneD is not the half: %d" % xs
    )
    if dry:
        print("(dry run — nothing written)")
        return
    json.dump(bfd, open(bf_p, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    open(x_p, "wb").write(gzip.compress(json.dumps(xl, separators=(",", ":")).encode(), 9))
    print("wrote", os.path.relpath(bf_p, ROOT), os.path.relpath(x_p, ROOT))


if __name__ == "__main__":
    a = sys.argv[1:]

    def arg(k, d=None):
        return a[a.index(k) + 1] if k in a else d

    if "--fetch" in a:
        fetch(
            int(arg("--budget", 300)),
            arg("--out", os.path.join(os.environ.get("RUNNER_TEMP") or "/tmp", "bse_xbrl_fills.json")),
            arg("--from-dir"),
            set((arg("--codes") or "").split(",")) - {""} or None,
        )
    elif "--apply" in a:
        apply(arg("--apply"))
    elif "--heal-sme" in a:
        heal_sme(arg("--heal-sme"), dry="--dry" in a)
    else:
        print(__doc__)
