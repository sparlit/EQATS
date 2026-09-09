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
"""Backfill Revenue + Operating Profit (sf_revop) for companies whose PAT exists in
sf_fundamentals but whose rev/op cells are blank on the quarterly-results page.

WHY these gaps exist: sf_revop is parsed from NSE XBRL (scripts/_xbrl_cache + the daily
integrated-filing cron). ~330 NSE-listed names (MCX, ABBOTINDIA, BAYERCROP, ...) are simply
never served an XBRL by NSE — their PAT was filled by the BSE-PDF vision routine, which
reads ONLY net profit. So Rev/OPM columns sit blank while PAT shows. (Diagnosed 2026-07-21:
MCX has PAT w/ announce dates for every quarter yet zero files in the 102k-file XBRL cache.)

METHOD (text-layer, free, anchor-verified — no vision API):
  1. Gap = (sym, qe) in the page's 13-quarter window where PAT (std or con) is stored but
     sf_revop has no rev on either basis. Non-financial names only by default (banks/insurers
     have different P&L rows; --fin adds the NBFC-format attempt).
  2. For each gap quarter: query BSE announcements in a ±5-day window around the STORED
     announce date (we know when it filed — that's the point), take result filings,
     fetch the attachment PDF (announcement API route — immune to the FinancialResult-API
     entity poisoning; the PAT anchor below is the identity guard anyway).
  3. From the P&L page's word layout, rebuild the table: label rows (revenue from operations,
     other income, finance costs, depreciation, profit before exceptional items & tax, tax,
     PAT, owners-PAT) x right-aligned numeric columns.
  4. ANCHOR before writing (never output an unanchored value — SKIP instead):
     the column whose PAT equals the STORED PAT for that (sym,qe,basis) under one scale
     (crore=1 / lakh=100 / million=10), CONFIRMED by a second anchor: another column matching
     the stored prev-quarter or year-ago PAT, OR the in-column identity PBT - tax = PAT.
     For consolidated tables the anchor row is owners-attributable when printed (our stored
     con basis), else total PAT.
  5. op = PBET + FinanceCosts + Depreciation - OtherIncome (= Trendlyne 'Oper Profit', the
     same formula build_revop uses on XBRL); ebit = op - Depreciation. rev = RevenueFromOps.
  6. The SAME PDF's comparative columns (prev quarter / year-ago) fill those gap cells too
     when they anchor — roughly halves the PDF fetches.
  7. Fill-only merge into docs/sf_revop.json AND scripts/revop_fundamentals.json.
     Ledgers: scripts/_revgap_done.json (fills + provenance), _revgap_skips.json (reasons).

Run:  python -X utf8 scripts/backfill_revop_gaps.py [--only SYM,SYM] [--limit N] [--dry]
      [--fin] [--all-quarters]   (default: the 13 QEs quarterly_results.json displays)
Resumable: skips cells already filled; ledgers accumulate.
"""
import datetime
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import contextlib

import fetch_insurers as FI  # bse session/datebound/fetch_pdf/_tv — proven helpers
import fitz  # PyMuPDF — text-layer only here (scanned pages -> skip+flag)
from build_revop import strip_lender_ebit  # adjudicated no-ebit filers (2026-08-16 alignment)

REVOP_DOCS = os.path.join(ROOT, "docs", "sf_revop.json")
REVOP_SCR = os.path.join(HERE, "revop_fundamentals.json")
FUND = os.path.join(ROOT, "docs", "sf_fundamentals.json")
QR = os.path.join(ROOT, "docs", "quarterly_results.json")
SCRIPS = os.path.join(HERE, "bse_scrips.json")
DONE = os.path.join(HERE, "_revgap_done.json")
SKIPS = os.path.join(HERE, "_revgap_skips.json")
PNL = os.path.join(HERE, "sf_pnl_full.json")  # full P&L line-items harvested per (sym,qe,basis)
# (raw/best-effort — kept out of docs/, not served)
PDFCACHE = os.path.join(HERE, "_revgap_pdfcache")  # fetch each BSE attachment once, reuse forever


def cached_pdf(sess, att):
    """Fetch a BSE attachment PDF, caching the bytes on disk so we never re-download it (this run's
    resume + any future parameter harvest). Returns (bytes|None, from_cache)."""
    with contextlib.suppress(Exception):
        os.makedirs(PDFCACHE, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", att)[-120:]
    p = os.path.join(PDFCACHE, safe if safe.lower().endswith(".pdf") else safe + ".pdf")
    if os.path.exists(p):
        try:
            b = open(p, "rb").read()
            if b[:4] == b"%PDF":
                return b, True
        except Exception:
            pass
    raw = FI.fetch_pdf(sess, att)
    if raw and raw[:4] == b"%PDF":
        with contextlib.suppress(Exception):
            open(p, "wb").write(raw)
    return raw, False


# ---- P&L row labels (Schedule III wording varies a little across filers) ----------------
ROW_PATS = {
    "rev": re.compile(r"(?:total\s+)?(?:revenue|income)\s+from\s+operations?", re.IGNORECASE),
    "oi": re.compile(r"^other\s+income", re.IGNORECASE),
    "fc": re.compile(r"finance\s+costs?", re.IGNORECASE),
    "dep": re.compile(
        r"depreciation(?:\s*(?:,|and|&)?\s*(?:depletion\s*(?:and|&)?\s*)?amorti[sz]ation)?", re.IGNORECASE
    ),
    "pbet": re.compile(
        r"profit\s*/?\s*\(?\s*loss\s*\)?\s*(?:from\s+\w+\s+activities\s+)?before\s+exceptional"
        r"|profit\s+before\s+exceptional",
        re.IGNORECASE,
    ),
    "pbt": re.compile(
        r"profit\s*/?\s*\(?\s*loss\s*\)?\s*(?:from\s+\w+\s+activities\s+)?before\s+tax"
        r"|profit\s+before\s+tax",
        re.IGNORECASE,
    ),
    "tax": re.compile(r"^(?:total\s+)?tax\s+expenses?", re.IGNORECASE),
    # NOTE '(?:/?\s*\(?\s*loss\s*\)?)?' is OPTIONAL: plain 'Profit for the period' (Eternal/Zomato
    # style) must match too — requiring the literal 'loss' silently skipped every such filer.
    "pat": re.compile(
        r"(?:net\s+)?profit\s*(?:/?\s*\(?\s*loss\s*\)?)?\s*(?:after\s+tax\s*)?for\s+the\s+"
        r"(?:period|quarter|year)|profit\s+after\s+tax",
        re.IGNORECASE,
    ),
    "own": re.compile(r"attributable\s+to\s*:?\s*(?:the\s+)?(?:owners?|equity\s+holders|shareholders)", re.IGNORECASE),
    # 'Total Income' (= rev + other income) — validation row only, NOT 'Total income from operations'
    "ti": re.compile(r"^total\s+income(?!\s+from)", re.IGNORECASE),
}
PL_PAGE = re.compile(r"revenue\s+from\s+operations?|income\s+from\s+operations?", re.IGNORECASE)
CON_HDR = re.compile(r"consolidated", re.IGNORECASE)
STD_HDR = re.compile(r"standalone|stand\s*alone", re.IGNORECASE)
BANKISH = re.compile(r"interest\s+earned|premium.{0,12}earned|net\s+premium", re.IGNORECASE)

TOL_ABS = 0.06  # crore — vision fills were rounded to 2dp; PDFs print 2dp
SCALES = (100.0, 1.0, 10.0)  # lakh (commonest for these small/mid caps), crore, million


def close(a, b):
    if a is None or b is None:
        return False
    return abs(a - b) <= max(TOL_ABS, 0.004 * max(abs(a), abs(b)))


def prevq(qe):
    return FI.prevq(qe)


def nextq(qe):
    """Next standard quarter-end: 0331→0630→0930→1231→next-year 0331."""
    y, mmdd = qe // 10000, qe % 10000
    nxt = {331: 630, 630: 930, 930: 1231, 1231: 331}[mmdd]
    return (y + 1) * 10000 + nxt if mmdd == 1231 else y * 10000 + nxt


def yago(qe):
    return qe - 10000


# ---- table reconstruction from the word layer -------------------------------------------
def page_lines(page):
    """Group get_text('words') into y-lines: [(y, text, [(x1, val), ...numeric cells...])]."""
    words = page.get_text("words")
    if not words:
        return []
    ws = sorted(words, key=lambda w: (round(w[3] / 4), w[0]))  # cluster by baseline
    lines, cur, cury = [], [], None
    for w in ws:
        y = (w[1] + w[3]) / 2
        if cury is None or abs(y - cury) <= 4:
            cur.append(w)
            cury = y if cury is None else (cury + y) / 2
        else:
            lines.append((cury, cur))
            cur, cury = [w], y
    if cur:
        lines.append((cury, cur))
    out = []
    for y, lw in lines:
        lw.sort(key=lambda w: w[0])
        txt = " ".join(w[4] for w in lw)
        nums = []
        for w in lw:
            v = FI._tv(w[4])
            if v is not None and re.search(r"\d", w[4]) and not re.fullmatch(r"[0-9]{1,2}[\.\)]?", w[4]):
                nums.append((w[2], v))  # right edge x — results columns are right-aligned
        out.append((y, txt, nums))
    return out


def merge_wrapped(lines):
    """A label wraps onto 2-3 lines while its numbers sit on the LAST wrapped line (or the first).
    Merge a numeric-less line into the following line's label so ROW_PATS still match."""
    merged, carry = [], ""
    for y, txt, nums in lines:
        if not nums and len(txt) > 3 and not re.search(r"\d{3}", txt):
            carry = (carry + " " + txt).strip()
            if len(carry) > 160:  # paragraph text, not a wrapped label
                carry = ""
            continue
        merged.append((y, (carry + " " + txt).strip(), nums))
        carry = ""
    return merged


def extract_rows(page):
    """{rowkey: [(x, val), ...]} for the first match of each ROW_PATS on the page."""
    rows = {}
    for _y, txt, nums in merge_wrapped(page_lines(page)):
        low = txt.strip()
        for key, pat in ROW_PATS.items():
            if key in rows or not nums:
                continue
            # component rows must be the EXPENSE/INCOME line itself, never a profit sub-header
            # like "Profit from operations before other income, finance costs and exceptional
            # items" — which contains 'finance costs'/'other income' and would hijack the row.
            if key in ("oi", "fc", "dep", "tax", "ti") and re.search(r"profit|loss", low, re.IGNORECASE):
                continue
            if key in ("oi", "tax", "ti"):
                # anchored at label start — 'other income' inside e.g. 'total income' lines,
                # and 'tax' must not match 'profit before tax'
                if pat.match(re.sub(r"^[0-9ivxIVX\.\)\(\s]+", "", low)):
                    rows[key] = nums
            elif pat.search(low):
                # 'pat' regex also matches the owners line's neighbourhood — keep first only
                if key == "pat" and ROW_PATS["own"].search(low):
                    continue
                rows[key] = nums
        # owners split rows: label line often carries no number; the 'Owners of the Company'
        # sub-line holds them
        if "own" not in rows and nums and re.search(r"owners?\s+of\s+the\s+(company|parent)", low, re.IGNORECASE):
            rows["own"] = nums
    return rows


def columns_of(row):
    return [x for x, _ in row]


def val_at(row, x, tol=18.0):
    """Value in `row` whose right edge is nearest x (within tol), else None."""
    best, bv = None, None
    for xx, v in row:
        d = abs(xx - x)
        if d <= tol and (best is None or d < best):
            best, bv = d, v
    return bv


def anchor_columns(rows, stored, basis):
    """Find (scale, {qe: x_column}) by matching the PAT row against stored PAT values.
    stored = {qe: pat_value} for this basis (current + prev + yago where known).
    Returns (scale, colmap, anchor_qe) or None. Requires the current qe match PLUS a second
    proof: a neighbour-quarter column match, or PBT-tax==PAT inside the anchored column."""
    pat_row = rows.get("own") if (basis == "con" and rows.get("own")) else rows.get("pat")
    if not pat_row:
        return None
    for scale in SCALES:
        colmap = {}
        for qe in sorted(stored, reverse=True):  # newest first: the current quarter claims its column
            pv = stored[qe]
            if pv is None:
                continue
            for x, raw in pat_row:
                if close(raw / scale, pv) and qe not in colmap:
                    # one column must not serve two quarters
                    if x not in colmap.values():
                        colmap[qe] = x
        if not colmap:
            continue
        # second anchor: another quarter matched in a DIFFERENT column
        if len(colmap) >= 2:
            return scale, colmap
        # or in-column identity PBT - tax = PAT (proves a coherent column, not a fluke)
        ((qe, x),) = colmap.items()
        pbt = val_at(rows.get("pbt", []), x)
        tax = val_at(rows.get("tax", []), x)
        pv = val_at(pat_row, x)
        if pbt is not None and tax is not None and pv is not None and close((pbt - tax), pv):
            return scale, colmap
    return None


def metrics_at(rows, x, scale):
    """(rev, op, ebit) at column x, or None when the essentials are missing or fail validation."""
    rev = val_at(rows.get("rev", []), x)
    if rev is None:
        return None
    oi = val_at(rows.get("oi", []), x) or 0.0
    fc = val_at(rows.get("fc", []), x) or 0.0
    dep = val_at(rows.get("dep", []), x) or 0.0
    # Decimal-integrity check via Schedule III's identity: Total Income = rev + other income.
    # A decimal-dropped REVENUE cell (MCX printed 197.47 as 19747) shows up as rev > total income,
    # which is impossible -> reject. But if rev <= ti yet rev+oi != ti, it's the OTHER-INCOME cell
    # that got mis-read (common in M&M-style integrated multi-column filings) — the revenue is still
    # trustworthy (it sits at the PAT-anchored column), so keep rev and just drop the derived op.
    ti = val_at(rows.get("ti", []), x)
    comp_ok = True
    if ti is not None:
        if rev > ti * 1.02 + 1:
            return None  # revenue can't exceed total income
        if abs((rev + oi) - ti) > max(0.6, 0.006 * abs(ti)):
            comp_ok = False  # a component (oi) mis-read -> op unreliable
    pbet = val_at(rows.get("pbet", []), x)
    if pbet is None:
        pbet = val_at(rows.get("pbt", []), x)
    op = ebit = None
    if comp_ok and pbet is not None:
        op = pbet + fc + dep - oi
        ebit = op - dep
        # Operating profit (≈EBITDA) can NEVER exceed revenue from operations for these filers — if
        # it does, a neighbouring column's number leaked into fc/dep/pbet (val_at matched the wrong
        # cell). Revenue itself sits at the PAT-anchored column and has its own Total-Income check,
        # so KEEP the revenue but drop the unreliable op/ebit (blank is better than a wrong bar).
        if op > rev * 1.05 + 1:
            op = ebit = None

    def r2(v):
        return None if v is None else round(v / scale, 2)

    return r2(rev), r2(op), r2(ebit)


# ---- main sweep -------------------------------------------------------------------------
def load(path, default):
    try:
        return json.load(open(path))
    except Exception:
        return default


def main():
    args = sys.argv[1:]
    only = set(args[args.index("--only") + 1].split(",")) if "--only" in args else None
    limit = int(args[args.index("--limit") + 1]) if "--limit" in args else None
    dry = "--dry" in args
    inc_fin = "--fin" in args

    n500_only = "--n500" in args
    # --rescue: also mine LATER filings' comparative columns for a gap quarter (next-quarter and
    # year-later result PDFs print it as their comparative) — the only source for pre-IPO quarters.
    rescue = "--rescue" in args
    # --symfile FILE: restrict to an explicit symbol list (JSON array) — used for the point-in-time
    # ever-member sweeps (ex-Nifty-500 names that no longer carry the current x&4 bit).
    symfile = args[args.index("--symfile") + 1] if "--symfile" in args else None
    symset = set(json.load(open(symfile))) if symfile else None
    all_q = "--all-quarters" in args
    # --years caps how far back to sweep; absent = FULL PAT history (every quarter in sf_fundamentals).
    back_years = int(args[args.index("--years") + 1]) if "--years" in args else None
    # --qe 20220630[,20220930] restricts the sweep to specific quarter-ends (implies --all-quarters,
    # since a target quarter is usually outside the 13-quarter display window). Added for the
    # FILL-2020 campaign's Jun-2022 pass: that ONE quarter is absent from the XBRL cache for 134 of
    # 142 affected N500 members (verified by scanning all 104k cached filings), so it needs a
    # surgical sweep instead of the multi-hour full-history one.
    qe_filter = {int(q) for q in args[args.index("--qe") + 1].split(",")} if "--qe" in args else None
    if qe_filter:
        all_q = True

    fund = json.load(open(FUND))
    revop = json.load(open(REVOP_DOCS))
    revop_scr = load(REVOP_SCR, {})
    qr = json.load(open(QR))
    by_id = json.load(open(SCRIPS, encoding="utf-8"))["by_id"]
    # bse_scrips.json is built from BSE's LIVE master, so a DELISTED/SUSPENDED company resolves to
    # nothing (§52b) and is dropped from the worklist before a single PDF is fetched — measured on
    # the 2018 campaign: 19 companies / 36 anchored cells never reached this route for that reason
    # alone (ALBK, DHFL, FRETAIL, MINDTREE, RELCAPITAL, RELINFRA, IDFC, SREINFRA...). Those cells
    # were NOT ATTEMPTED, not failed (§57a rule 4). The overrides below come from
    # fill2020_tools/resolve_delisted_scrips.py, which matches _bse_master_all.json on scrip_id and
    # then GATES ON ISIN against the one NSE prints on its own filing-index rows — never on the
    # scrip_id alone, which is the KALYANI coincidence (§76).
    _ovr = os.path.join(HERE, "fill2020_tools", "_delisted_scrip_overrides.json")
    if os.path.exists(_ovr):
        for _s, _v in json.load(open(_ovr)).items():
            by_id.setdefault(_s, _v["scrip"])
    done = load(DONE, {})
    skips = load(SKIPS, {})
    pnl = load(PNL, {})

    qes = qr["quarters"]
    if all_q:
        # EVERY quarter-end for which PAT exists in sf_fundamentals (fill all rev cells where we
        # have PAT), capped at the newest displayed quarter and, if --years given, that many years
        # back. No --years => full history (2015-> ), so year-ago bases are never the limiter.
        latest = max(qr["quarters"])
        hist = sorted({r[0] for rows in fund.values() for r in rows if r[0] <= latest})
        if back_years is not None:
            lo = (latest // 10000 - back_years) * 10000
            hist = [q for q in hist if q > lo]
        qes = hist
    if qe_filter:
        qes = sorted(qe_filter)
    fmap = {s: {r[0]: r for r in rows} for s, rows in fund.items()}

    def pat_of(sym, qe, basis):
        r = fmap.get(sym, {}).get(qe)
        if not r:
            return None
        return r[1] if basis == "std" else (r[3] if len(r) > 3 else None)

    _nosub_cache = {}

    def is_nosub(sym):
        """True when con PAT == std PAT (to the paisa) for every overlapping quarter (>=3): the
        stored con is the no-sub auto-copy, no consolidated statements exist to extract from."""
        if sym not in _nosub_cache:
            pairs = [(r[1], r[3]) for r in fund.get(sym, []) if len(r) > 3 and r[1] is not None and r[3] is not None]
            _nosub_cache[sym] = len(pairs) >= 3 and all(abs(c - s) <= 0.01 for s, c in pairs)
        return _nosub_cache[sym]

    def need_bases(sym, qe):
        """Bases still to fill: stored PAT exists but the revop rev slot for that basis is empty.
        No-sub companies only ever file standalone — never demand their con."""
        rr = revop.get(sym, {}).get(str(qe))
        out = []
        for basis, slot in (("std", 0), ("con", 1)):
            if pat_of(sym, qe, basis) is None:
                continue
            if basis == "con" and is_nosub(sym):
                continue
            if rr and rr[slot] is not None:
                continue
            out.append(basis)
        return out

    retry_skips = "--retry-skips" in args

    # Stored-PAT SCALE errors (filer filed in lakh/thousand, the earlier PAT backfill stored the
    # raw number — the §11 class). Anchoring against a broken PAT faithfully extends the wrong
    # scale to rev/op (caught live: QUINT rev "16407 cr" on a 184 cr mcap). Exclude these until
    # the PAT itself is corrected (§2b guard-edit), then re-run for them.
    def scale_suspect(sym):
        m = qr["co"].get(sym, {}).get("m")
        if not m:
            return False
        mx = max(
            (
                abs(v)
                for r in fund.get(sym, [])
                if r[0] >= 20230101
                for v in (r[1], r[3] if len(r) > 3 else None)
                if v is not None
            ),
            default=0,
        )
        return mx > max(3 * m, 1000)

    # ---- build the gap worklist (a cell is open while ANY basis with stored PAT lacks rev)
    #
    # ⚠ THE WORKLIST UNIVERSE IS `quarterly_results.json`, AND IT HAS NO DELISTED COMPANIES. That is
    # a SECOND scope bound on top of the bse_scrips one handled above, and it silently excluded the
    # same cells: measured 2026-08-11, all 18 delisted 2018 targets (ALBK, DHFL, FRETAIL, MINDTREE,
    # RELCAPITAL, RELINFRA, IDFC, SREINFRA, UJJIVAN, EQUITAS…) are absent from its 2,337-company map,
    # so `--symfile` produced "gap: 0 companies, 0 cells" — which reads as "nothing to do" when the
    # truth is "these were never in scope" (§57a rule 4).
    # When the caller names symbols EXPLICITLY (--only / --symfile) they have already decided the
    # universe, so honour it: iterate the union and default the metadata. Behaviour without those
    # flags is unchanged.
    universe = dict(qr["co"])
    if symset is not None or only:
        for _s in (symset or set()) | (only or set()):
            universe.setdefault(_s, {})
    gaps = {}
    for sym, meta in universe.items():
        if only and sym not in only:
            continue
        if symset is not None and sym not in symset:
            continue
        if n500_only and not (meta.get("x", 0) & 4):
            continue
        if meta.get("f") == 1 and not inc_fin:
            continue
        if scale_suspect(sym):
            skips[f"{sym}|scale"] = "stored-pat-scale-suspect"
            continue
        for qe in qes:
            if not need_bases(sym, qe):
                continue
            if not retry_skips and "%s|%d" % (sym, qe) in skips:
                continue
            gaps.setdefault(sym, []).append(qe)
    total_cells = sum(len(v) for v in gaps.values())
    print("gap: %d companies, %d cells" % (len(gaps), total_cells), flush=True)

    op_sess = FI.bse_session()
    time.sleep(1)
    filled = fetched = dup = 0
    syms = sorted(gaps)
    if limit:
        syms = syms[:limit]

    def put_cell(sym, qe, basis, rev, op, ebit, src):
        # "filled" counts only cells that actually CHANGED a store (None -> value). The old
        # unconditional count re-counted already-stored extractions and reported phantom yield
        # (M&M "filled 46" with an sha-identical sf_revop, 2026-08-05) — never trust a count
        # that doesn't require a write.
        nonlocal filled, dup
        key = "%s|%d" % (sym, qe)
        changed = False
        for store in (revop, revop_scr):
            d = store.setdefault(sym, {})
            rr = d.get(str(qe)) or [None] * 6 + [0, None, None]
            if len(rr) < 9:
                rr += [None] * (9 - len(rr))
            i = {"std": (0, 2, 7), "con": (1, 3, 8)}[basis]
            if rr[i[0]] is None and rev is not None:
                rr[i[0]] = rev
                changed = True
            if rr[i[1]] is None and op is not None:
                rr[i[1]] = op
                changed = True
            if rr[i[2]] is None and ebit is not None:
                rr[i[2]] = ebit
                changed = True
            # Adjudicated no-ebit filers (banks + screener-layout lenders, 2026-08-16 alignment).
            # This sweep DERIVES ebit = op - dep off PDF/HTML columns, so it can mint an ebit for a
            # lender the XBRL path would never produce. Guard at the WRITE, not at the source.
            strip_lender_ebit(sym, rr)
            # PAT mirror slots (4=std,5=con) — copy the anchored stored PAT for consistency
            pv = pat_of(sym, qe, basis)
            if rr[{"std": 4, "con": 5}[basis]] is None and pv is not None:
                rr[{"std": 4, "con": 5}[basis]] = pv
            d[str(qe)] = rr
        if changed:
            done.setdefault(key, {})[basis] = {"rev": rev, "op": op, "src": src}
            filled += 1
        else:
            dup += 1

    PNL_ROWS = ("rev", "oi", "fc", "dep", "pbet", "pbt", "tax", "pat", "own")

    def put_pnl(sym, qe, basis, rows, x, scale, op, ebit, src):
        """Harvest EVERY P&L line item at the anchored column into sf_pnl_full.json, so future
        features (other income, finance costs, depreciation, tax, PBT ...) never need a re-fetch."""
        prev = pnl.get(sym, {}).get(str(qe), {}).get(basis)
        if prev and prev.get("rev") is not None and prev.get("op") is not None:
            return  # fill-only: keep the first clean column

        def r2(v):
            return None if v is None else round(v / scale, 2)

        rec = {k: r2(val_at(rows.get(k, []), x)) for k in PNL_ROWS}
        # Per-field sanity: a single expense/income line (finance costs, depreciation, other income,
        # tax) or PBT/PAT can't exceed ~revenue — anything that does is a val_at column mismatch
        # (VBL fc read 7664.8 vs rev 2455). Null the offender rather than store a wrong number.
        rvv = rec.get("rev")
        if rvv:
            for k in ("oi", "fc", "dep", "tax", "pbet", "pbt", "pat", "own"):
                if rec[k] is not None and abs(rec[k]) > rvv * 1.1 + 1:
                    rec[k] = None
        rec["op"], rec["ebit"], rec["src"] = op, ebit, src  # op/ebit already scaled + guarded
        pnl.setdefault(sym, {}).setdefault(str(qe), {})[basis] = rec

    def try_page(sym, page, want_qes, src):
        """Extract every anchorable (qe, basis) on this page; fill gap cells. Returns filled qes."""
        text = page.get_text()
        if not text.strip() or not PL_PAGE.search(text):
            return []
        if BANKISH.search(text[:2500]):
            return []  # bank/insurer format — different rows
        is_con = bool(CON_HDR.search(text[:1200]))
        is_std = bool(STD_HDR.search(text[:1200]))
        bases = ["con"] if (is_con and not is_std) else (["std"] if (is_std and not is_con) else ["std", "con"])
        rows = extract_rows(page)
        if "rev" not in rows or ("pat" not in rows and "own" not in rows):
            return []
        got = []
        for basis in bases:
            # stored PAT anchors for every quarter this page could show. Include the NEXT quarter
            # and the YEAR-LATER quarter too: a later filing's page shows our target qe as its
            # prev-quarter / year-ago COMPARATIVE column, and its own (stored-PAT) columns then
            # anchor alongside it — a 2-3 column lock instead of a lone comparative match.
            cand = set()
            for qe in want_qes:
                cand.update((qe, prevq(qe), yago(qe), nextq(qe), qe + 10000, prevq(qe + 10000)))
            stored = {qe: pat_of(sym, qe, basis) for qe in cand}
            stored = {qe: v for qe, v in stored.items() if v is not None}
            if not stored:
                continue
            a = anchor_columns(rows, stored, basis)
            if not a:
                continue
            scale, colmap = a
            for qe, x in colmap.items():
                if qe not in want_qes:
                    continue
                m = metrics_at(rows, x, scale)
                if not m:
                    continue
                rev, op, ebit = m
                if rev is None or rev < 0:
                    continue
                # absurd-magnitude guard: quarterly revenue many multiples of market cap means a
                # broken scale slipped past the anchors — never write it, flag for review instead
                _m = qr["co"].get(sym, {}).get("m")
                if _m and rev > max(25 * _m, 500):
                    skips["%s|%d" % (sym, qe)] = "absurd-vs-mcap"
                    continue
                # con-vs-std floor guard: consolidated = standalone + subsidiaries, so con revenue
                # collapsing to a sliver of the SAME quarter's already-stored std revenue means the
                # anchor locked onto the wrong column (a stray EPS/per-share figure, a sub-table) —
                # PAT can coincidentally match while revenue is nonsense (caught live 2026-08-06:
                # 3MINDIA 20251231 con rev extracted as 1.23 vs std 1228.05, con PAT == std PAT so
                # the PAT anchor alone passed it). Skip for review instead of trusting the coincidence.
                if basis == "con" and not is_nosub(sym):
                    std_rev = (revop.get(sym, {}).get(str(qe)) or [None])[0]
                    if std_rev and std_rev > 0 and rev < 0.5 * std_rev:
                        skips["%s|%d" % (sym, qe)] = f"con-rev-far-below-std:{rev:.2f}-vs-{std_rev:.2f}"
                        continue
                put_cell(sym, qe, basis, rev, op, ebit, src)
                put_pnl(sym, qe, basis, rows, x, scale, op, ebit, src)
                got.append((qe, basis))
        return got

    def save_all(final=False):
        """Checkpoint every store ATOMICALLY (tmp + os.replace) with retries. A transient Windows
        file lock (AV/indexer) once raised EINVAL straight from open(...,'w') at a checkpoint and
        killed a 6-hour sweep at 130/485 — an interim save failure must never be fatal, and a
        direct 'w' open can truncate the file if it dies mid-write. os.replace is all-or-nothing."""
        for obj, path in ((revop, REVOP_DOCS), (revop_scr, REVOP_SCR), (done, DONE), (skips, SKIPS), (pnl, PNL)):
            for attempt in range(3):
                try:
                    tmp = path + ".tmp"
                    with open(tmp, "w") as f:
                        json.dump(obj, f, separators=(",", ":"))
                    os.replace(tmp, path)
                    break
                except OSError as ex:
                    if attempt == 2:
                        print(
                            "  ! save failed for {} ({}){}".format(
                                os.path.basename(path),
                                ex,
                                " — FINAL, data only in earlier checkpoint"
                                if final
                                else " — will retry next checkpoint",
                            ),
                            flush=True,
                        )
                    else:
                        time.sleep(2)

    for si, sym in enumerate(syms):
        want = sorted(gaps[sym], reverse=True)
        scrip = by_id.get(sym)
        if not scrip:
            for qe in want:
                skips["%s|%d" % (sym, qe)] = "no-bse-scrip"
            continue
        seen_atts = set()
        for qe in list(want):
            if not need_bases(sym, qe):  # filled meanwhile by a newer PDF's comparative cols
                skips.pop("%s|%d" % (sym, qe), None)
                continue
            r = fmap[sym][qe]
            ann = r[2] or (r[4] if len(r) > 4 else None)
            if r[2] and len(r) > 4 and r[4]:
                ann = min(r[2], r[4])
            # window 1: around the stored announce date (the §12 gate can shift ann a couple of
            # days past the actual filing); window 2 (fallback): the whole post-quarter stretch
            wins = []
            if ann:
                d0 = datetime.datetime.strptime(str(ann), "%Y%m%d").date()
                wins.append((d0 - datetime.timedelta(days=6), d0 + datetime.timedelta(days=6)))
            dq = datetime.datetime.strptime(str(qe), "%Y%m%d").date()
            wins.append((dq + datetime.timedelta(days=10), dq + datetime.timedelta(days=160)))
            if rescue:
                # COMPARATIVE RESCUE: our target quarter is printed as the prev-quarter /
                # year-ago comparative column of LATER filings — the only extant source when
                # the company IPO'd after qe (it never filed qe itself), and a second chance
                # when its own filing was scanned. Search around the NEXT quarter's and the
                # YEAR-LATER quarter's stored announce dates (else their post-quarter stretch).
                for rq in (nextq(qe), qe + 10000):
                    rr = fmap.get(sym, {}).get(rq)
                    rann = (rr[2] or (rr[4] if len(rr) > 4 else None)) if rr else None
                    if rann:
                        d1 = datetime.datetime.strptime(str(rann), "%Y%m%d").date()
                        wins.append((d1 - datetime.timedelta(days=6), d1 + datetime.timedelta(days=6)))
                    else:
                        dr = datetime.datetime.strptime(str(rq), "%Y%m%d").date()
                        wins.append((dr + datetime.timedelta(days=10), dr + datetime.timedelta(days=75)))
            fils, err, seen_f = [], None, set()
            for lo, hi in wins:
                try:
                    got_f = FI.datebound(op_sess, str(scrip), lo.strftime("%Y%m%d"), hi.strftime("%Y%m%d"))
                except Exception as ex:
                    err = f"ann-list-err:{type(ex).__name__}"
                    got_f = []
                time.sleep(0.5)
                for t in got_f or []:
                    if t[1] not in seen_f:
                        seen_f.add(t[1])
                        fils.append(t)
                if fils and not rescue:
                    break  # legacy behaviour: first productive window wins
            if not fils:
                skips["%s|%d" % (sym, qe)] = err or "no-result-filing-in-window"
                continue
            for annd, att, _sub in fils[: 10 if rescue else 4]:
                if att in seen_atts:
                    continue
                seen_atts.add(att)
                raw, from_cache = cached_pdf(op_sess, att)
                if not from_cache:  # only count + throttle on real network hits
                    fetched += 1
                    time.sleep(0.4)
                if not raw:
                    continue
                try:
                    doc = fitz.open(stream=raw, filetype="pdf")
                except Exception:
                    continue
                open_want = [q for q in want if need_bases(sym, q)]
                # investor-letter PDFs (Eternal/Zomato style) bury the statements 20+ pages in —
                # scan deeper when rescue-mining comparatives; 14 pages stays the cheap default.
                for pi in range(min(len(doc), 40 if rescue else 14)):
                    try_page(sym, doc[pi], open_want, f"{att[:24]}@{annd}")
                doc.close()
                if not need_bases(sym, qe):
                    break
            if need_bases(sym, qe):
                skips.setdefault("%s|%d" % (sym, qe), "no-anchor-or-scanned")
            else:
                skips.pop("%s|%d" % (sym, qe), None)
        if (si + 1) % 10 == 0 or si + 1 == len(syms):
            print("  [%d/%d] %s — filled %d cells, %d PDFs" % (si + 1, len(syms), sym, filled, fetched), flush=True)
            if not dry:
                save_all()

    if not dry:
        save_all(final=True)
    print(
        "DONE: filled %d basis-cells (%d re-extractions were already stored, not counted) via %d PDF fetches "
        "(cache: %s); skips ledger %d entries; pnl rows %d"
        % (filled, dup, fetched, os.path.basename(PDFCACHE), len(skips), sum(len(v) for v in pnl.values())),
        flush=True,
    )


if __name__ == "__main__":
    main()
