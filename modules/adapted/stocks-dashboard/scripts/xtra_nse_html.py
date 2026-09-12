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
"""Per-quarter LINE ITEMS (EPS, other income, interest, depreciation, tax, exceptional, PBT,
employee cost, materials, bank ratios, audited flag) for PRE-2018 quarters, read from NSE's
ARCHIVED financial-results HTML and written into the SAME ledger the XBRL re-parse feeds
(scripts/xbrl_extra.json[.gz], served as docs/fin/<sym>.json 'x').

WHY THIS ROUTE (measured 2026-09-05, runbook §130):
  * The results-list API (`corporates-financial-results?symbol=X&period=Quarterly`) carries a real
    XBRL URL only from the Mar-2018 quarter on (2018: 4,784 of 5,712 cached rows; 2017: 374; 2016: 2).
    Every 2005-2017 row instead carries `resultDetailedDataLink` -> the archived HTML detail page,
    which prints the whole filed P&L as a label/value table INCLUDING the EPS rows, the paid-up
    capital and the face value. So "XBRL only" == "2018 only", and the block before 2018 has to come
    from these pages (memory: feedback-nse-archive-first).
  * Over the PIT Nifty-500 member-quarters with a stored PAT, 24,529 of the 29,390 pre-2018 holes
    have such a page (2005-2017 at 86-99% per year); the archive starts 2005, so 2002-2004 (3,126
    cells) need the Moneycontrol route (xtra_mc.py) and a few hundred index holes stay for it too.

LABEL TEMPLATES (census over 9,609 cached pages — three P&L templates plus the bank one):
  2005-2012   "Interest", "Depreciation", "Tax Expense", "Exceptional items", "Employees Cost",
              "Consumption of Raw Materials", "Other Income", "Profit(+)/Loss(-) from Ordinary
              Activities before tax", "Basic/Diluted EPS before|after Extraordinary items (in Rs.)"
  2013-2016   "Finance costs", "(e) Depreciation and amortisation expense", "Tax expense",
              "(d) Employee benefits expense", "(a) Cost of materials consumed", "Other income",
              "Profit / (Loss) from ordinary activities before tax", same EPS rows
  Ind-AS 16-17  no "Other income" row (derive: Total Income − Total income from operations),
              "(f) Finance costs", EPS rows "Basic EPS for continuing operations" and
              "... for continued and discontinued operations" — the latter is a 0.00 PLACEHOLDER on
              321 of 378 pages while the continuing-ops row carries the figure.
  Banking     "Interest Expended" (int_exp), "Employees cost", "Other Income", "Tax Expense",
              "% of Gross/Net NPA" (TWO numbers after one label), "Return on Assets",
              "Capital Adequacy Ratio"; no finance-cost / depreciation / materials rows.
  Footer traps: a segment block prints "INTEREST 0.00" and "Total Profit Before Tax" after the
  P&L — every regex here is anchored and tried in row order so the body row wins.

GATES (nothing lands without all of them):
  identity   page Symbol == the symbol asked (or one of its era names); Period Ended == qe;
             "Non-Cumulative" (a Cumulative page is YTD, refused); declared basis -> s|c.
  anchor     the page's PAT (owners row / period row / signed template / consolidated-net row)
             must reproduce the STORED PAT of that basis within max(2.0 cr, 3%) — the same anchor
             _nse_archive_revop.py uses. It proves page, quarter, basis and the declared unit at
             once; a page with no stored PAT on that basis is refused (`no-stored-anchor`), never
             read blind.
  eps        the basic-EPS row is cross-checked against PAT via paid-up equity / face value
             (PAT == eps × eqcap / fv within 6%, §53e GATE E). A miss refuses the EPS fields
             only; missing inputs are journalled as unchecked, not refused.
  zero       an all-zero P&L (blank template) is refused; an Ind-AS "continued and discontinued"
             EPS of 0.00 next to a non-zero continuing-ops row is a placeholder, not a value.

PRECEDENCE in the ledger (per basis-cell): XBRL (no `src` key) > this route (`src: nse-html:…`)
> Moneycontrol (`src: mc:…`). A basis-cell already XBRL-backed is never touched; an nse-html cell
is re-asserted (idempotent); an mc cell is replaced whole. build_xbrl_extra.py's full rebuild
seeds itself from every `src`-carrying cell so a --fresh re-parse cannot drop these.

Run:  python3 scripts/xtra_nse_html.py [--universe n500|all] [--years 2005-2017]
        [--targets FILE] [--only SYM,SYM] [--shard I/N] [--limit N] [--no-fetch] [--apply]
      Without --apply: journal only (scripts/_xtra_html_reads.json + _xtra_html_skips.json).
      --apply merges the journalled reads into scripts/xbrl_extra.json and re-gzips it.
"""
import collections
import gzip
import html as html_lib
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import contextlib

import _n500_member_bin as MB  # PIT Nifty-500 membership, rename-folded
import _nse_archive_revop as NAR  # list_rows / get_detail / aliases / cache / close()

FUND = os.path.join(ROOT, "docs", "sf_fundamentals.json")
LEDGER = os.path.join(HERE, "xbrl_extra.json")
LEDGER_GZ = LEDGER + ".gz"
READS = os.path.join(HERE, "_xtra_html_reads.json")
SKIPS = os.path.join(HERE, "_xtra_html_skips.json")
CACHE = NAR.CACHE

MON = NAR.MON
NUM = re.compile(r"^-?[\d,]+\.?\d*$")
EPS_TOL = 0.06


# ---- row regexes: anchored, case-insensitive; tried in the listed order, first row in page order ----
def rx(*pats):
    return [re.compile(p, re.IGNORECASE) for p in pats]


R = {
    "oi": rx(r"^other income$"),
    "fc": rx(r"^finance costs?$", r"^\(?[a-z]?\)?\s*finance costs?$", r"^interest$"),
    "dep": rx(r"^depreciation and amortisation expenses?$", r"^depreciation$", r"^less:?\s*depreciation$"),
    "tax": rx(r"^tax expenses?$"),
    "exc": rx(r"^exceptional items?$"),
    "pbt": rx(r"from ordinary activities before tax$", r"^profit\s*/?\s*\(?loss\)?\s*before tax$"),
    "emp": rx(r"^employees? costs?$", r"^employee benefits? expenses?$"),
    "mat": rx(r"^cost of materials consumed$", r"^consumption of raw materials$"),
    "int_exp": rx(r"^interest expended$"),
    "roa": rx(r"^return on assets"),
    "car": rx(r"^capital adequacy ratio"),
}
R_EPS = {
    "eps_b": {
        "after": rx(r"^basic eps after extra\s?ordinary items"),
        "before": rx(r"^basic eps before extra\s?ordinary items"),
        "all": rx(r"^basic eps for continued and discontinued operations"),
        "cont": rx(r"^basic eps for continuing operations"),
    },
    "eps_d": {
        "after": rx(r"^diluted eps after extra\s?ordinary items"),
        "before": rx(r"^diluted eps before extra\s?ordinary items"),
        "all": rx(r"^diluted eps for continued and discontinued operations"),
        "cont": rx(r"^diluted eps for continuing operations"),
    },
}
R_NPA = re.compile(r"^%\s*of gross\s*/\s*net npa", re.IGNORECASE)
R_TOTINC = re.compile(r"^total income$", re.IGNORECASE)
R_TOTOPS = re.compile(r"^total income from operations", re.IGNORECASE)
R_EQCAP = re.compile(r"paid-?up equity share capital", re.IGNORECASE)
R_FV = re.compile(r"^face value", re.IGNORECASE)
ROWNUM = NAR.ROWNUM
MONEY_FIELDS = ("oi", "fc", "dep", "tax", "exc", "pbt", "emp", "mat", "int_exp")


def cells_of(page):
    t = re.sub(r"<[^>]+>", "|", page)
    t = re.sub(r"&nbsp;?", " ", t)
    return [html_lib.unescape(c).strip() for c in t.split("|") if c.strip()]


def parse_page(page):
    """-> (meta, rows) with rows = [(label, RAW value, [second numeric if the label is followed by
    two numbers])]. Values are NOT scaled here — money rows are divided by the declared unit at use,
    per-share rows never are (parse_detail() in _nse_archive_revop scales everything, which turned a
    Face Value of 2 into 0.02 under lakhs)."""
    cells = cells_of(page)
    meta, rows = {}, []
    for i, c in enumerate(cells):
        nxt = cells[i + 1] if i + 1 < len(cells) else ""
        if c in (
            "Consolidated / Non-Consolidated",
            "Period Ended",
            "Symbol",
            "Audited / Un-Audited",
            "Cumulative / Non-Cumulative",
        ):
            meta[c] = nxt
        if c in ("Banking", "Non Banking"):
            meta["fmt"] = c
        m = re.match(r"Amount\s*\(\s*Rs\.?\s*in\s*(lakhs?|crores?|thousands?|millions?)", c, re.IGNORECASE)
        if m:
            meta["unit"] = m.group(1).lower()
        if not NUM.match(c) and NUM.match(nxt):
            try:
                v = float(nxt.replace(",", ""))
            except ValueError:
                continue
            nxt2 = cells[i + 2] if i + 2 < len(cells) else ""
            v2 = None
            if NUM.match(nxt2):
                with contextlib.suppress(ValueError):
                    v2 = float(nxt2.replace(",", ""))
            rows.append((re.sub(r"\s+", " ", c), v, v2))
    div = {
        "lakh": 100.0,
        "lakhs": 100.0,
        "crore": 1.0,
        "crores": 1.0,
        "thousand": 10000.0,
        "thousands": 10000.0,
        "million": 10.0,
        "millions": 10.0,
    }
    meta["div"] = div.get(meta.get("unit", "lakhs"), 100.0)
    meta["_cells"] = cells
    return meta, rows


def pick_row(rows, pats):
    """(label, value) of the first row matching the first pattern that matches anything."""
    for p in pats:
        for lab, v, _ in rows:
            if p.search(lab) or p.search(ROWNUM.sub("", lab)):
                return lab, v
    return None, None


def iso_qe(s):
    return NAR.iso_qe(s)


R_EPS_HDR = re.compile(r"^earnings? per share.*\((before|after) extra\s?ordinary items\)", re.IGNORECASE)
R_SUB_B = re.compile(r"^\(?a\)?\s*basic\b", re.IGNORECASE)
R_SUB_D = re.compile(r"^\(?b\)?\s*diluted\b", re.IGNORECASE)


def section_eps(cells):
    """{eps_b: (label, value), eps_d: (...)} from the header + "(a) Basic"/"(b) Diluted" layout.
    Walks the raw CELLS (the header carries no number, so it never appears in `rows`). The 'after
    extraordinary items' section wins (same preference as the explicit-label templates and the
    XBRL tag order); 'before' is the fallback."""
    found = {}
    sec = None
    for i, lab in enumerate(cells):
        m = R_EPS_HDR.search(lab)
        if m:
            sec = m.group(1).lower()
            continue
        if sec is None or NUM.match(lab):
            continue
        nxt = cells[i + 1] if i + 1 < len(cells) else ""
        v = None
        if NUM.match(nxt):
            try:
                v = float(nxt.replace(",", ""))
            except ValueError:
                v = None
        if R_SUB_B.search(lab) and v is not None:
            found.setdefault(("eps_b", sec), (lab + f" [{sec} extraordinary]", v))
        elif R_SUB_D.search(lab) and v is not None:
            found.setdefault(("eps_d", sec), (lab + f" [{sec} extraordinary]", v))
        elif not lab.lower().startswith("("):
            sec = None  # any other labelled row ends the section
    out = {}
    for f in ("eps_b", "eps_d"):
        if (f, "after") in found:
            out[f] = found[(f, "after")]
        elif (f, "before") in found:
            out[f] = found[(f, "before")]
    return out


def page_pat(rows, basis, isbank):
    """PAT candidates in the order _nse_archive_revop tries them, scaled by the caller."""
    r2 = [(lab, v) for lab, v, _ in rows]

    def pick(*pats):
        for p in pats:
            for lab, v in r2:
                if p.search(lab) or p.search(ROWNUM.sub("", lab)):
                    return v
        return None

    cands = []
    if not isbank:
        cands.append(pick(NAR.R_PAT_OWN))
    cands.append(pick(NAR.R_PAT_ANY))
    cands.append(pick(NAR.R_PAT_SIGNED))
    if basis == "c":
        cands.append(pick(NAR.R_PAT_CONNET))
    if isbank:
        cands.append(pick(NAR.R_PAT_OWN))
    return [c for c in cands if c is not None]


def read_page(page, sym, qe, stored_pat_by_basis):
    """-> (basis, fields, note) or (None, None, refusal). fields carry only what the page proves."""
    meta, rows = parse_page(page)
    psym = (meta.get("Symbol") or "").strip().upper()
    ok_syms = {sym.upper()} | {a.upper() for a in NAR.aliases(sym)}
    if not psym:
        return None, None, "empty-shell(no meta, %d bytes)" % len(page)
    if psym not in ok_syms:
        return None, None, f"symbol-mismatch(page {psym})"
    pq = iso_qe(meta.get("Period Ended"))
    if pq != qe:
        return None, None, f"period-mismatch(page {pq})"
    cum = (meta.get("Cumulative / Non-Cumulative") or "").strip().lower()
    if cum and not cum.startswith("non"):
        return None, None, "cumulative-page(YTD not quarter)"
    basis = "c" if "Non" not in (meta.get("Consolidated / Non-Consolidated") or "Non") else "s"
    isbank = meta.get("fmt") == "Banking"
    div = meta["div"]
    stored = stored_pat_by_basis.get(basis)
    if stored is None:
        return basis, None, f"no-stored-anchor({basis})"
    cands = [c / div for c in page_pat(rows, basis, isbank)]
    hit = next((c for c in cands if NAR.close(c, stored)), None)
    if hit is None:
        return basis, None, f"pat-anchor {[round(c, 2) for c in cands[:3]] if cands else None} vs stored {stored}"
    money_vals = [v for lab, v, _ in rows if any(p.search(lab) for f in MONEY_FIELDS for p in R[f])]
    if abs(hit) < 1e-9 and money_vals and all(abs(v) < 1e-9 for v in money_vals):
        return basis, None, "blank-template(all-zero page)"

    out, jn = {}, {}
    for f in MONEY_FIELDS:
        if isbank and f in ("fc", "dep", "mat"):
            continue  # a bank page has no such rows; its footer "INTEREST 0.00" must not land
        if not isbank and f == "int_exp":
            continue
        lab, v = pick_row(rows, R[f])
        if v is not None:
            out[f] = round(v / div, 2)
            jn[f] = lab[:50]
    if "oi" not in out:
        # Ind-AS 2016-17 template: no Other income row; Total Income − Total income from operations
        _, ti = pick_row(rows, [R_TOTINC])
        _, to = pick_row(rows, [R_TOTOPS])
        if ti is not None and to is not None and ti - to >= 0:
            out["oi"] = round((ti - to) / div, 2)
            jn["oi"] = "derived: Total Income - Total income from operations"
    # ---- EPS: template-aware choice, then the PAT recon check ------------------------------
    # 2012-2014 template: a HEADER row "Earnings per share (before|after extraordinary items)
    # (not annualised):" followed by "(a) Basic" / "(b) Diluted" sub-rows — the label alone says
    # nothing, the section does. 3,188 of the first cached pass's 7,881 cells had no EPS read for
    # exactly this reason (2012: 893/1,193 pages, 2013: 1,069/1,080, 2014: 1,025/1,035).
    sec = section_eps(meta["_cells"])
    eps_note = {}
    for f in ("eps_b", "eps_d"):
        pats = R_EPS[f]
        lab, v = pick_row(rows, pats["after"])
        if v is None:
            lab, v = pick_row(rows, pats["before"])
        if v is None and sec.get(f):
            lab, v = sec[f]
        if v is None:
            lab_all, v_all = pick_row(rows, pats["all"])
            lab_c, v_c = pick_row(rows, pats["cont"])
            if v_all is not None and abs(v_all) > 1e-9:
                lab, v = lab_all, v_all
            elif v_c is not None:
                lab, v = lab_c, v_c  # the combined row is the 0.00 placeholder
                if v_all is not None and abs(v_all) < 1e-9 and abs(v_c) > 1e-9:
                    eps_note[f + "_pick"] = "continuing-ops (combined row = 0.00 placeholder)"
            elif v_all is not None:
                lab, v = lab_all, v_all
        if v is None:
            continue
        if abs(v) < 1e-9 and abs(hit) > 0.5:
            # the preferred row is a 0.00 placeholder (ATLASCYCLE Mar-2005: "Basic EPS after
            # Extraordinary items 0.00" beside "Diluted … 2.12"); try the other rows of the
            # same template before refusing — refuse only when every candidate prints 0.00
            alt = None
            for key in ("before", "all", "cont"):
                lab2, v2 = pick_row(rows, pats[key])
                if v2 is not None and abs(v2) > 1e-9:
                    alt = (lab2, v2)
                    break
            if alt is None and sec.get(f) and abs(sec[f][1]) > 1e-9:
                alt = sec[f]
            if alt is None:
                eps_note[f] = f"refused: 0.00 EPS against PAT {hit:.2f} (placeholder)"
                continue
            lab, v = alt
            eps_note[f + "_pick"] = "fallback row (preferred row printed 0.00)"
        out[f] = round(v, 2)
        jn[f] = (lab or "")[:50]
    # GATE E: eps × paid-up equity / face value == PAT (the unit divisor cancels: both in the page's
    # declared unit). Refuses the EPS fields only.
    if "eps_b" in out and abs(hit) > 1e-9:
        _, eq = pick_row(rows, [R_EQCAP])
        _, fv = pick_row(rows, [R_FV])
        if eq and fv:
            recon = out["eps_b"] * (eq / div) / fv
            err = abs(recon - hit) / abs(hit)
            if err <= EPS_TOL:
                eps_note["eps_chk"] = "ok %.1f%%" % (err * 100)
            else:
                eps_note["eps_chk"] = f"refused {err * 100:.1f}% (recon {recon:.2f} vs {hit:.2f})"
                out.pop("eps_b", None)
                out.pop("eps_d", None)
        else:
            eps_note["eps_chk"] = "no-inputs"
    # ---- bank ratios (non-zero only, same rule as the XBRL builder) ---------------------------
    if isbank:
        for lab, v, v2 in rows:
            if R_NPA.search(lab):
                if v and abs(v) > 1e-9:
                    out["gnpa_pct"] = round(v, 2)
                if v2 is not None and abs(v2) > 1e-9:
                    out["nnpa_pct"] = round(v2, 2)
                break
        for f in ("roa", "car"):
            _, v = pick_row(rows, R[f])
            if v is not None and abs(v) > 1e-9:
                out[f] = round(v, 2)
    aud = (meta.get("Audited / Un-Audited") or "").strip().lower()
    if aud:
        out["aud"] = "U" if aud.startswith("un") else "A"
    if not out:
        return basis, None, "no-rows-read"
    return (
        basis,
        out,
        {
            "unit": meta.get("unit", "lakhs"),
            "fmt": meta.get("fmt", "?"),
            "anchor": round(hit, 2),
            "labels": jn,
            **eps_note,
        },
    )


# ---------------------------------------------------------------------------------- targets ----


def build_targets(universe, y0, y1, ledger, refresh=False):
    """{sym: {qe: {basis: stored_pat}}} — quarters with a stored PAT, in the year window, that the
    ledger does not already hold as an XBRL cell for that basis. `refresh` re-reads cells this
    route already wrote (a parser improvement re-journals every cached page; --no-fetch keeps
    it free)."""
    fund = json.load(open(FUND))
    tg = {}
    for sym, rows in fund.items():
        ns = MB.norm(sym)
        for r in rows:
            qe = int(r[0])
            y = qe // 10000
            if y < y0 or y > y1:
                continue
            bases = {}
            if r[1] is not None:
                bases["s"] = r[1]
            if len(r) > 3 and r[3] is not None:
                bases["c"] = r[3]
            if not bases:
                continue
            if universe == "n500" and ns not in MB.membership(qe):
                continue
            have = (ledger.get(sym) or {}).get(str(qe)) or {}
            for b in list(bases):
                cell = have.get(b)
                if cell and "src" not in cell:  # XBRL-backed: nothing to do
                    bases.pop(b)
                elif cell and str(cell.get("src", "")).startswith("nse-html") and not refresh:
                    bases.pop(b)  # already read from this route
            if bases:
                tg.setdefault(sym, {})[qe] = bases
    return tg


def load_ledger():
    if os.path.exists(LEDGER):
        return json.load(open(LEDGER))
    return json.loads(gzip.decompress(open(LEDGER_GZ, "rb").read()))


def apply_reads(reads, ledger):
    n = 0
    for sym, qs in reads.items():
        for qe, per_basis in qs.items():
            for b, ent in per_basis.items():
                cell = ledger.setdefault(sym, {}).setdefault(str(qe), {})
                cur = cell.get(b)
                if cur and "src" not in cur:
                    continue  # XBRL outranks this route
                new = dict(ent["fields"])
                new["src"] = ent["src"]
                if cur and cur.get("src_mc"):
                    # fields Moneycontrol added to the earlier nse-html cell stay unless this
                    # read now carries them (xtra_mc.apply_reads keeps the per-field provenance)
                    keep = [f for f in cur["src_mc"] if f not in new and cur.get(f) is not None]
                    for f in keep:
                        new[f] = cur[f]
                    if keep:
                        new["src_mc"] = keep
                cell[b] = new
                n += 1
    return n


def main():
    argv = sys.argv

    def opt(name, default=None):
        return argv[argv.index(name) + 1] if name in argv else default

    universe = opt("--universe", "n500")
    yrs = opt("--years", "2005-2017")
    y0, y1 = (int(x) for x in yrs.split("-"))
    only = set(opt("--only", "").split(",")) - {""}
    shard = opt("--shard")
    limit = int(opt("--limit", 0) or 0)
    no_fetch = "--no-fetch" in argv
    do_apply = "--apply" in argv
    refresh = "--refresh" in argv
    suffix = opt("--out-suffix", "")

    ledger = load_ledger()
    reads_p = READS.replace(".json", suffix + ".json")
    skips_p = SKIPS.replace(".json", suffix + ".json")
    reads = json.load(open(reads_p)) if os.path.exists(reads_p) else {}
    skips = json.load(open(skips_p)) if os.path.exists(skips_p) else {}

    if do_apply and "--targets" not in argv and "--only" not in argv:
        # merge every shard's journal, then write the ledger
        merged = {}
        for f in sorted(os.listdir(HERE)):
            if f.startswith("_xtra_html_reads") and f.endswith(".json"):
                for s, v in json.load(open(os.path.join(HERE, f))).items():
                    for q, pb in v.items():
                        merged.setdefault(s, {}).setdefault(q, {}).update(pb)
        n = apply_reads(merged, ledger)
        json.dump(ledger, open(LEDGER, "w"), separators=(",", ":"))
        open(LEDGER_GZ, "wb").write(gzip.compress(open(LEDGER, "rb").read(), 9))
        print("applied %d basis-cells from %d symbols -> %s (+gz)" % (n, len(merged), os.path.basename(LEDGER)))
        return

    if "--targets" in argv:
        targets = {s: {int(q): b for q, b in v.items()} for s, v in json.load(open(opt("--targets"))).items()}
    else:
        targets = build_targets(universe, y0, y1, ledger, refresh=refresh)
    if refresh:
        reads = {}  # re-journal every target from the page again
    syms = sorted(targets)
    if only:
        syms = [s for s in syms if s in only]
    if shard:
        i, n = (int(x) for x in shard.split("/"))
        syms = [s for k, s in enumerate(syms) if k % n == i]
    if limit:
        syms = syms[:limit]
    ncell = sum(len(targets[s]) for s in syms)
    print(
        "targets: %d symbols, %d quarter-cells (universe=%s years=%s)" % (len(syms), ncell, universe, yrs), flush=True
    )

    NAR.JAR = None

    def jar():
        if NAR.JAR is None:
            import build_fundamentals as BF

            NAR.JAR = BF.nse_jar()
        return NAR.JAR

    landed = 0
    t0 = time.time()
    for si, sym in enumerate(syms, 1):
        want = targets[sym]
        done = reads.get(sym, {})
        pending = {q: b for q, b in want.items() if not all(bb in done.get(str(q), {}) for bb in b)}
        if not pending:
            continue
        lists = [
            os.path.join(CACHE, "list_{}.json".format(re.sub(r"[^A-Z0-9]", "_", s.upper())))
            for s in [sym, *NAR.aliases(sym)]
        ]
        if not any(os.path.exists(p) for p in lists) and no_fetch:
            skips[f"{sym}|list"] = "no-cached-list(no-fetch)"
            continue
        jar()
        rows = NAR.list_rows(sym)
        if not rows:
            skips[f"{sym}|list"] = "no-nse-filings-any-era"
            continue
        for r in rows:
            qe = iso_qe(r.get("toDate"))
            if qe not in pending:
                continue
            link = (r.get("resultDetailedDataLink") or "").strip()
            if not link:
                continue
            row_basis = "c" if str(r.get("consolidated", "")).strip().lower() == "consolidated" else "s"
            if row_basis not in pending[qe] or row_basis in done.get(str(qe), {}):
                continue
            dp = os.path.join(CACHE, re.sub(r"[^A-Za-z0-9_.]", "_", link.rsplit("/", 1)[-1]))
            if no_fetch and not os.path.exists(dp):
                skips["%s|%d|%s" % (sym, qe, row_basis)] = "not-cached(no-fetch)"
                continue
            try:
                page = NAR.get_detail(link, sym, dp)
            except Exception as e:
                skips["%s|%d|%s" % (sym, qe, row_basis)] = f"fetch:{type(e).__name__}"
                continue
            basis, fields, note = read_page(page, sym, qe, pending[qe])
            key = "%s|%d|%s" % (sym, qe, basis or row_basis)
            if fields is None:
                skips[key] = note
                continue
            skips.pop(key, None)
            src = "nse-html:{}".format(link.rsplit("/", 1)[-1])
            reads.setdefault(sym, {}).setdefault(str(qe), {})[basis] = {"fields": fields, "src": src, "chk": note}
            done = reads[sym]
            landed += 1
        if si % 10 == 0 or si == len(syms):
            json.dump(reads, open(reads_p, "w"), separators=(",", ":"))
            json.dump(skips, open(skips_p, "w"), indent=0, sort_keys=True)
            print(
                "  [%d/%d] %d landed, %d skips, %.0fs" % (si, len(syms), landed, len(skips), time.time() - t0),
                flush=True,
            )
        if not no_fetch:
            time.sleep(0.2)
    json.dump(reads, open(reads_p, "w"), separators=(",", ":"))
    json.dump(skips, open(skips_p, "w"), indent=0, sort_keys=True)
    print(
        "DONE: %d basis-cells landed this run -> %s; %d skips -> %s"
        % (landed, os.path.basename(reads_p), len(skips), os.path.basename(skips_p))
    )
    if do_apply:
        n = apply_reads(reads, ledger)
        json.dump(ledger, open(LEDGER, "w"), separators=(",", ":"))
        open(LEDGER_GZ, "wb").write(gzip.compress(open(LEDGER, "rb").read(), 9))
        print("applied %d basis-cells -> %s (+gz)" % (n, os.path.basename(LEDGER)))


if __name__ == "__main__":
    main()
