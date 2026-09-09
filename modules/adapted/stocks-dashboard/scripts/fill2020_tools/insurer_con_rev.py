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
"""FILL-2020 rev track: CONSOLIDATED revenue for insurers, from the exchange filing PDF.

WHY NOT ANY EXISTING ROUTE.
  * XBRL: NSE serves no rev/op XBRL for insurers before the 2025 Integrated-Filing regime
    (INTEGRATED_FILING_LI/GI); api/integrated-filing-results returns only the last ~20 filings.
    That is exactly why 2025+ insurer quarters are filled and 2020-2024 are not.
  * IRDAI public disclosures (runbook §43): the L-/NL-forms are ENTITY-level regulatory returns —
    standalone only. They are where our insurer *standalone* revenue came from, and they can never
    yield consolidated.
  * runbook §3's `_con_tracks_std` finding: only ICICIPRULI's con tracks std; HDFCLIFE/NIACL/GICRE
    consolidated genuinely diverges, so con=std would be fabrication. EXTRACT, never derive.
So the only real source is the quarterly filing itself, which carries BOTH statements.

THE CONVENTION (life), reverse-engineered in runbook §43 and re-validated here to the paisa:
    revenue = Policyholders' [Net premium income + Income from investments (Net)]
            + Shareholders'  [Investment Income]
Validation on HDFCLIFE Jun-2022, standalone page: 9,27,187 − 3,48,656 + 10,060 = 5,88,591 lakh
= ₹5,885.91cr against our stored 5,885.91 — exact. Same page's PAT 36,529 lakh = 365.29 against
stored 365.29 — exact. The consolidated page of the same filing gives 6,690.11 (the gap is Exide
Life, a subsidiary until its Oct-2022 merger — a real ₹800cr of consolidated premium).
General insurers use the GI convention: Premium earned (net) + policyholders' investment income
+ shareholders' investment income, matching build_revop.metrics_for's GI branch.

HOW A VALUE IS PROVEN (all must hold — otherwise the cell is skipped WITH a reason):
  A1  COLUMN by anchor, never by position. Every row is read as a full vector of columns; the
      column used is the one whose PAT equals our stored PAT for that (sym, qe, basis). Insurer
      packs print [current qtr | prev qtr | year-ago | FY], and the order is not stable across
      years, so a positional guess is how you land a year-ago number in a current-quarter cell.
  A2  SCALE by anchor. lakh (÷100), crore (÷1) and million (÷10) are all tried; the one that makes
      PAT match is the one used. A wrong scale misses by 100x and simply fails.
  A3  DISTINCT PAGE PER BASIS (runbook §44's ISEC trap): standalone and consolidated PAT can sit
      within anchor tolerance of each other, so one page satisfies both and silently duplicates
      itself into the con slot. Each basis takes the page whose PAT is CLOSEST to that basis'
      stored value, and the two bases must resolve to DIFFERENT pages.
  A4  Rows are located POSITIONALLY (word x/y boxes), not by line order — insurer packs put labels
      and figures in separate text flows, and a naive "numbers after the label" scan picks up the
      next row's serial number.
  A5  ★ PER-FILING POSITIVE CONTROL. The consolidated figure is only accepted if the SAME filing's
      STANDALONE statement reproduces the standalone revenue we already store for that quarter,
      within 0.5%. This is the gate that matters, because it tests the whole chain — page choice,
      column choice, scale, and every revenue leg — against a known answer, per document, instead
      of trusting that a convention validated on one filing holds for a layout from another year.
      It was added after the 2025-format packs read 29,061.08 against a stored 29,381.30: the
      shareholders' investment-income leg lives on a different page there and was silently
      contributing zero. The PAT anchor happily passed that read; only the control caught it.
      Quarters with no stored standalone revenue to control against are SKIPPED, not guessed.

Fill-only. Ledger: scripts/insurer_con_rev_fills.json (tracked, per-cell provenance).
PDFs cache under scripts/_ins_pdfcache/ (gitignored).

Run:  python -X utf8 scripts/fill2020_tools/insurer_con_rev.py [--only SYM] [--qe YYYYMMDD] [--apply]
"""
import json
import os
import re
import sys
import time
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
SCRIPTS = os.path.join(ROOT, "scripts")
sys.path.insert(0, SCRIPTS)

import fetch_insurers as FI  # noqa: E402  (bse session / datebound / fetch_pdf)
import fitz  # noqa: E402

PDFCACHE = os.path.join(SCRIPTS, "_ins_pdfcache")
REVOP_DOCS = os.path.join(ROOT, "docs", "sf_revop.json")
REVOP_LEDGER = os.path.join(SCRIPTS, "revop_fundamentals.json")
FUND = os.path.join(ROOT, "docs", "sf_fundamentals.json")
SCRIPS = os.path.join(SCRIPTS, "bse_scrips.json")
TARGETS = os.path.join(HERE, "_rev2020_targets.json")
FILLS = os.path.join(SCRIPTS, "insurer_con_rev_fills.json")
SKIPS = os.path.join(SCRIPTS, "_insurer_con_rev_skips.json")

LIFE = {"HDFCLIFE", "ICICIPRULI", "SBILIFE", "LICI"}
GENERAL = {"NIACL", "GICRE", "ICICIGI", "STARHEALTH", "GODIGIT", "NIVABUPA"}
SCALES = (("lakh", 100.0), ("crore", 1.0), ("million", 10.0), ("thousand", 10000.0))

R_NETPREM = re.compile(r"^net premium income", re.IGNORECASE)
R_PREMEARNED = re.compile(r"^premium earned\s*\(?net\)?|^net premium earned", re.IGNORECASE)
R_PH_INV = re.compile(r"^income from investments?\s*:?\s*\(net\)", re.IGNORECASE)  # ICICIPRULI prints a colon
# 2023-24 life packs print the shareholders' leg as "(a) Investment Income (net)2" — the (a)
# prefix and (net)N suffix made the leg contribute a silent ZERO (the §55 failure class; the A5
# control caught it reading ~1% under stored on every 2023-24 HDFCLIFE/LICI quarter, 2026-08-10).
R_SH_INV = re.compile(
    r"^(?:\([a-z]\)\s*)?investment income(?:\s*\(net\)\s*\d?)?\s*$"
    r"|^(?:\([a-z]\)\s*)?income from investments?\s*$",
    re.IGNORECASE,
)
R_PAT = re.compile(
    r"^profit\s*/?\s*\(?loss\)?\s*after tax and extraordinary items"
    r"|^profit after tax and extraordinary"
    r"|^profit\s*/?\s*\(?loss\)?\s*after tax\b",
    re.IGNORECASE,
)
NUMRE = re.compile(r"^\(?-?[\d,]+\.?\d*\)?$")


# ---------------------------------------------------------------------------------------------
# OCR MODE — for filings whose text layer is corrupted (GICRE; runbook §51b glyph substitution).
# rapidocr renders and re-reads the page, which is CLEANER than the broken text layer, but it
# returns whole phrases with the spaces stripped ("PremiumEarned(Net)"). So every row label is also
# matched in a NORMALISED form (lowercase, alphanumerics only), which incidentally makes the
# text-layer path immune to punctuation variants too.
#
# ⚠️ Runbook §0 says OCR mangles digits — true, and it is exactly why nothing here relies on OCR
# being right. A mangled digit fails the PAT anchor, or the standalone control, or the con/std
# ratio family (§55b). The reader is allowed to be unreliable because the gates are not.
# ---------------------------------------------------------------------------------------------
OCR_BAND_TOL = 5.0  # OCR baselines wobble more than a text layer's
OCR_MAX_PAGES = 45  # cap the render cost; insurer statements sit well inside this


def norm(t):
    return re.sub(r"[^a-z0-9]", "", (t or "").lower())


N_NETPREM = re.compile(r"^netpremiumincome")
N_PREMEARNED = re.compile(r"^premiumearned(net)?$|^netpremiumearned")
N_PH_INV = re.compile(r"^incomefrominvestments?net$")
N_SH_INV = re.compile(r"^[a-z]?incomefrominvestments\d?$|^[a-z]?investmentincome(net)?\d?$")
N_PAT = re.compile(r"^profit(loss)?aftertax(andbeforeextraordinaryitems|andextraordinaryitems)?$")
N_MINORITY = re.compile(r"minorityinterest|noncontrolling")
N_ASSOCIATE = re.compile(r"shareofprofit.*associate|associateenterprises")
N_CARRIED = re.compile(r"^profit(loss)?carriedtobalancesheet")
N_TRANSFER_OUT = re.compile(r"transferredtoshareholders")
N_TRANSFER_IN = re.compile(r"transferfrompolicyholders")
N_SHARE_HEAD = re.compile(r"shareholders(ac|account)")


def words_of(page, ocr=False):
    """(x0, y0, x1, y1, text) from the text layer, or from rapidocr when ocr=True."""
    if ocr:
        return [(w[0], w[1], w[2], w[3], w[4]) for w in FI._ocr_words(page)]
    return [(w[0], w[1], w[2], w[3], w[4]) for w in page.get_text("words")]


# OCR reads the Indian digit grouping "1,74,942" as "1.74942" — the comma becomes a decimal point.
# These statements print MONETARY figures as whole lakhs and RATIOS with at most two decimals, so a
# value with 3+ digits after a single point and a short integer part is a mangled group, not a
# fraction: 1.74942 -> 174942, 35.97353 -> 3597353, while 2.88 and 10.36 are left alone. A wrong
# call here cannot land a cell — it fails the PAT anchor.
REGROUP = re.compile(r"^(\d{1,3})\.(\d{3,})$")


def num(tok):
    t = tok.strip().replace(",", "")
    if not NUMRE.match(t) or t in ("-", ""):
        return None
    neg = t.startswith("(")
    t = t.strip("()")
    m = REGROUP.match(t)
    if m:
        t = m.group(1) + m.group(2)
    try:
        v = float(t)
    except ValueError:
        return None
    return -v if neg else v


SERIAL = re.compile(r"^\(?[0-9]{1,2}\)?$|^\([a-z]\)$|^[ivx]{1,4}\.?$", re.IGNORECASE)
DASHES = {"-", "–", "—", "−"}
COL_TOL = 14.0  # points; figure columns in these packs sit well over 30pt apart


NORM_OF = {}  # populated after the R_* patterns exist (see _init_norm_map)


def _init_norm_map():
    NORM_OF.update(
        {
            id(R_NETPREM): N_NETPREM,
            id(R_PREMEARNED): N_PREMEARNED,
            id(R_PH_INV): N_PH_INV,
            id(R_SH_INV): N_SH_INV,
            id(R_PAT): N_PAT,
            id(R_MINORITY): N_MINORITY,
            id(R_ASSOCIATE): N_ASSOCIATE,
            id(R_CARRIED): N_CARRIED,
            id(R_TRANSFER_OUT): N_TRANSFER_OUT,
            id(R_TRANSFER_IN): N_TRANSFER_IN,
            id(R_SHARE_HEAD): N_SHARE_HEAD,
        }
    )


def _raw_rows(page, ocr=False):
    """[(label, [(x_right, value)])] — one entry per y-band, figures keyed by their right edge.

    Two traps this handles, both of which produced ZERO usable rows in the naive version:
      * rows open with a SERIAL cell ("2  Net premium income  9,87,006 ..."). Treating that as the
        first value drops the label and the row disappears.
      * a row's label and its figures can sit in different text blocks at slightly different y, so
        the band tolerance has to be a few points, not an exact key."""
    words = sorted(words_of(page, ocr), key=lambda w: (round(w[1], 1), w[0]))
    tol = OCR_BAND_TOL if ocr else 3.0
    bands, cur, cy = [], [], None
    for x0, y0, x1, _y1, w, *_ in words:
        if cy is None or abs(y0 - cy) <= tol:
            cur.append((x0, x1, w))
            cy = y0 if cy is None else cy
        else:
            bands.append(cur)
            cur, cy = [(x0, x1, w)], y0
    if cur:
        bands.append(cur)

    raw = []
    for toks in bands:
        toks.sort()
        # A figure cell is a number OR a nil dash. Everything to the LEFT of the last text token
        # is label furniture (row serials, "- Shareholders'" bullets); everything to the right of
        # it is a figure. Splitting on that boundary is what makes a dash safe to keep.
        last_text_x = max([x0 for x0, x1, w in toks if num(w) is None and w not in DASHES], default=-1e9)
        label = [w for x0, x1, w in toks if num(w) is None and w not in DASHES]
        vals = []
        for x0, x1, w in toks:
            if x0 <= last_text_x:
                continue
            # figures are RIGHT-aligned, so the right edge is the stable column key; the left edge
            # moves with the digit count and shatters a column into several clusters
            if w in DASHES:
                vals.append((x1, 0.0))  # nil, but it OCCUPIES ITS COLUMN
            else:
                v = num(w)
                if v is not None:
                    vals.append((x1, v))
        raw.append((" ".join(label).strip(), vals))
    return raw


def page_rows(page, ocr=False):
    """[(label, [values left->right])] on the page's own figure-geometry columns."""
    raw = _raw_rows(page, ocr)

    # Page-level column geometry. Aligning by ORDER breaks the moment one row prints a dash that
    # the reader drops: every later value shifts one column left, and the anchor still passes
    # because the PAT row shifted too. HDFCLIFE Mar-2020 came out as revenue 246.03 against a
    # ~15,000 neighbour that way. Columns are therefore taken from x-geometry: cluster the figure
    # x-positions across the whole page, and every row reports into those same columns.
    xs = sorted(x for _, vals in raw for x, _ in vals)
    cols, cur = [], []
    for x in xs:
        if cur and x - cur[-1] > COL_TOL:
            cols.append(sum(cur) / len(cur))
            cur = []
        cur.append(x)
    if cur:
        cols.append(sum(cur) / len(cur))
    cols = [c for c in cols if sum(1 for x in xs if abs(x - c) <= COL_TOL) >= 3]

    rows = []
    for label, vals in raw:
        if not label:
            continue
        slotted = [None] * len(cols)
        for x, v in vals:
            if not cols:
                break
            k = min(range(len(cols)), key=lambda i: abs(cols[i] - x))
            if abs(cols[k] - x) <= COL_TOL * 2 and slotted[k] is None:
                slotted[k] = v
        # heading rows (no figures) are KEPT: locating the SHAREHOLDERS' A/C heading is how
        # the shareholders' investment-income row is told apart from the policyholders' one
        rows.append((label, slotted if any(v is not None for v in slotted) else []))
    return rows


# a leading enumerator to strip before matching: "(a)", "(iv)", "12." — never a bare short word.
# (_nse_archive_revop learned this the hard way: a looser pattern ate the "Net " of "Net Profit".)
ENUM = re.compile(r"^\((?:[a-z]|[ivx]{1,4}|\d{1,2})\)\s*|^\d{1,2}\.\s+", re.IGNORECASE)


def pick_row(rows, pat, after=-1):
    npat = NORM_OF.get(id(pat))
    for i, (lab, vals) in enumerate(rows):
        if i <= after or not vals:
            continue
        for form in (lab, re.sub(r"[\d\*¹²³]+$", "", lab).strip(), ENUM.sub("", lab).strip()):
            if pat.search(form):
                return vals
        # normalised: OCR strips the spaces inside a box, and filers vary the punctuation
        if npat is not None and npat.search(norm(lab)):
            return vals
    return None


R_SHARE_HEAD = re.compile(r"shareholders[’'`\s]*\s*(a/?c|account)", re.IGNORECASE)
# The one line printed in BOTH halves of the statement: the policyholders' surplus transferred out
# is the shareholders' transfer in. When the two halves sit on different pages (the 2025 format,
# and some 2023-24 packs), matching this vector proves the two pages' columns are the same periods
# in the same order — without it, joining pages would be a guess.
R_TRANSFER_OUT = re.compile(r"transferred to shareholders", re.IGNORECASE)
R_TRANSFER_IN = re.compile(r"transfer from policyholders", re.IGNORECASE)
# General insurers print the profit tail on the page AFTER the revenue rows, and their
# owners-attributable consolidated profit is never printed as one number — runbook §3. It is
# PAT + minority(signed) + share of associates, which is exactly what our stored con PAT holds.
R_MINORITY = re.compile(r"profit attributable to minority|minority interest|non.?controlling", re.IGNORECASE)
R_ASSOCIATE = re.compile(r"share of profit.*associate|associate enterprises", re.IGNORECASE)
R_CARRIED = re.compile(r"profit\s*/?\s*\(?loss\)?\s*carried to balance sheet", re.IGNORECASE)


def align(tout, tin):
    """Column offset s such that tin[k + s] is the same period as tout[k], proven by the shared
    transfer line. None when no offset reconciles them — in which case the pages are NOT joined."""
    best = None
    for s in range(-4, 5):
        pairs = 0
        for k in range(len(tout)):
            j = k + s
            if j < 0 or j >= len(tin) or tout[k] is None or tin[j] is None:
                continue
            if abs(tout[k] - tin[j]) > 1.0:
                pairs = -99
                break
            pairs += 1
        if pairs >= 2 and (best is None or pairs > best[0]):
            best = (pairs, s)
    return best[1] if best else None


def reindex(vec, shift):
    """Re-express a vector from the shareholders' page in the policyholders' page column space."""
    if not vec:
        return []
    out = []
    for k in range(len(vec) + abs(shift)):
        j = k + shift
        out.append(vec[j] if 0 <= j < len(vec) else None)
    return out


# ---------------------------------------------------------------------------------------------
# HEADER-DATE COLUMN MODEL — select a column by the PERIOD it is headed with, never by index.
# Index-based selection is what broke the general-insurer cross-page join: NIACL's Sep-2020 pack
# detects 6 figure columns on its revenue page and 7 on its profit page, so slot k is a different
# period on each, and a 3%-tolerant PAT anchor happily accepted the mismatch (Jun-2020 and
# Sep-2020 both read 6,923.24). Both pages DO print the same dated header row, so the period is
# available directly: read it, and pick the column whose date IS the quarter being filled.
# ---------------------------------------------------------------------------------------------
_MONTHS = {
    m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)
}
# Header dates come in every shape a filer can imagine, and OCR strips the spaces:
#   (30/06/2023) · 31.03.2024 · March31,2024 · 31stMarch2024
_DATE_FORMS = (
    re.compile(r"^(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4})$"),  # d m y
    re.compile(r"^([a-z]{3,9})\.?(\d{1,2}),?(\d{4})$"),  # month d y
    re.compile(r"^(\d{1,2})(?:st|nd|rd|th)?([a-z]{3,9})\.?,?(\d{4})$"),  # d month y
)


def parse_date_tok(tok):
    """Quarter-end int from a header token, or None. Punctuation and spaces are ignored, so the
    same matcher works on a text layer and on an OCR read (which strips spaces inside a box)."""
    t = re.sub(r"[()\s]", "", (tok or "")).lower()
    for i, rx in enumerate(_DATE_FORMS):
        m = rx.match(t)
        if not m:
            continue
        try:
            if i == 0:
                d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
            elif i == 1:
                mo = _MONTHS.get(m.group(1)[:3])
                d, y = int(m.group(2)), int(m.group(3))
            else:
                d = int(m.group(1))
                mo = _MONTHS.get(m.group(2)[:3])
                y = int(m.group(3))
        except (TypeError, ValueError):
            continue
        if not mo or not (1 <= mo <= 12) or not (1 <= d <= 31) or not (1990 <= y <= 2100):
            continue
        return y * 10000 + mo * 100 + d
    return None


DATE_TOK = re.compile(r"^\(?(\d{2})/(\d{2})/(\d{4})\)?$")  # kept: legacy callers
HDR_TOL = 26.0  # pt; how far a figure's right edge may sit from its header's right edge


def header_columns(page, ocr=False):
    """[(x_right, qe)] left-to-right for the page's dated header row, or [] if there isn't one.

    The header is the y-band carrying the MOST date tokens (>=3) — titles and 'Renewed from'
    lines elsewhere on the page also contain dates and must not be mistaken for it."""
    words = sorted(words_of(page, ocr), key=lambda w: (round(w[1], 1), w[0]))
    bands = {}
    for _x0, y0, x1, _y1, w, *_ in words:
        qe = parse_date_tok(w)
        if qe is None:
            continue
        bands.setdefault(round(y0 / 4.0), []).append((x1, qe))
    if not bands:
        return []
    best = max(bands.values(), key=len)
    return sorted(best) if len(best) >= 3 else []


def rows_on_columns(page, cols, ocr=False):
    """page_rows(), but every figure is slotted by the HEADER column it sits under, so the same
    index means the same period on every page of the filing."""
    if not cols:
        return []
    out = []
    for label, vals in _raw_rows(page, ocr):
        slotted = [None] * len(cols)
        for x1, v in vals:
            k = min(range(len(cols)), key=lambda i: abs(cols[i][0] - x1))
            if abs(cols[k][0] - x1) <= HDR_TOL and slotted[k] is None:
                slotted[k] = v
        out.append((label, slotted if any(v is not None for v in slotted) else []))
    return out


def map_columns(cols_a, cols_b):
    """For each column of page A, the index of the SAME period on page B, or None.

    Matched by (date, occurrence) rather than by date alone: these statements print the same date
    twice — once heading the quarter, once heading the six-months-ended column — so "first column
    with this date" would map the six-month column onto the quarter's figures."""
    seen_a, out = {}, []
    for _x, q in cols_a:
        j = seen_a.get(q, 0)
        seen_a[q] = j + 1
        k, hit = 0, None
        for i, (_xb, qb) in enumerate(cols_b):
            if qb == q:
                if k == j:
                    hit = i
                    break
                k += 1
        out.append(hit)
    return out


def column_for(cols, qe):
    """LEFTMOST column headed with this quarter-end. These statements print the quarter columns
    before the six-month / year-to-date ones, and the same date heads both (NIACL prints
    30/09/2020 twice: once as the quarter, once as the six months), so leftmost = the quarter."""
    for i, (_x, q) in enumerate(cols):
        if q == qe:
            return i
    return None


def declared_basis(rows):
    # general insurers put the statement title below a registration/circular preamble, so the
    # header scan has to reach further than the first few rows
    head = " ".join(lab for lab, _ in rows[:12])[:600]
    if re.search(r"consolidat", head, re.IGNORECASE):
        return "con"
    if re.search(r"standalone|stand\s*alone", head, re.IGNORECASE):
        return "std"
    return None


def read_doc(doc, life, ocr=False):
    """[(label, page_data)] — one entry per statement found, joining a statement that runs across
    two pages (see R_TRANSFER_OUT). Returns the same dict shape read_page produces.

    ocr=True re-reads every page with rapidocr instead of the text layer — for filings whose text
    layer is corrupted (GICRE, runbook §51b). Slow (~1-2s/page), so it is a fallback, never first."""
    per_page = []
    for pno in range(min(doc.page_count, OCR_MAX_PAGES if ocr else doc.page_count)):
        try:
            rows = page_rows(doc[pno], ocr)
        except Exception:
            continue
        per_page.append((pno, rows, declared_basis(rows)))

    out = []
    for i, (pno, rows, decl) in enumerate(per_page):
        pd = build(rows, life, decl)
        if pd:
            out.append((pno, pd))
            continue
        # half a statement: premium legs here, shareholders' P&L on a following page
        prem = pick_row(rows, R_NETPREM if life else R_PREMEARNED)
        tout = pick_row(rows, R_TRANSFER_OUT)
        if prem is None:
            continue
        if tout is None and life:
            continue  # life format joins on the transfer line; without it, no join
        ph = pick_row(rows, R_PH_INV)
        if ph is None:
            continue
        share_at = -1
        for j, (lab_, vals_) in enumerate(rows):
            if R_SHARE_HEAD.search(lab_):
                share_at = j
        for pno2, rows2, decl2 in per_page[i + 1 : i + 4]:
            if decl2 and decl and decl2 != decl:
                break
            tin = pick_row(rows2, R_TRANSFER_IN)
            pat = pick_row(rows2, R_PAT)
            if pat is not None and tin is None:
                # GENERAL-FORMAT CONTINUATION, re-enabled on the header-date column model.
                # History (keep this, it is the reason the gate looks like it does): the first
                # version joined the two pages by INDEX and let the PAT anchor stand in for proof
                # of alignment. It is not proof. NIACL's Sep-2020 pack detects 6 figure columns on
                # the revenue page and 7 on the profit page, so slot k differed between them, and
                # the 3% tolerance accepted the near-miss — Jun-2020 and Sep-2020 both landed
                # 6,923.24 (Jun's revenue wearing Sep's anchor). Both pages DO print the same dated
                # header row, so the period is now read directly from it and the profit vector is
                # re-expressed in the revenue page's column space by (date, occurrence).
                cols_a = header_columns(doc[pno], ocr)
                cols_b = header_columns(doc[pno2], ocr)
                if len(cols_a) < 3 or len(cols_b) < 3:
                    continue
                rows_a = rows_on_columns(doc[pno], cols_a, ocr)
                rows_b = rows_on_columns(doc[pno2], cols_b, ocr)
                prem = pick_row(rows_a, R_NETPREM if life else R_PREMEARNED)
                ph = pick_row(rows_a, R_PH_INV)
                pat_b = pick_row(rows_b, R_PAT)
                if prem is None or ph is None or pat_b is None:
                    continue
                share_a = -1
                for j2, (lab2, _v2) in enumerate(rows_a):
                    if R_SHARE_HEAD.search(lab2):
                        share_a = j2
                sh_a = pick_row(rows_a, R_SH_INV, after=share_a) if share_a >= 0 else None
                minor = pick_row(rows_b, R_MINORITY) or []
                assoc = pick_row(rows_b, R_ASSOCIATE) or []
                owners_b = [
                    None if v is None else v + (at(minor, k2) or 0.0) + (at(assoc, k2) or 0.0)
                    for k2, v in enumerate(pat_b)
                ]
                carried = pick_row(rows_b, R_CARRIED)
                if carried:  # when the filing prints it, it must agree — a free second check
                    n = min(len(owners_b), len(carried))
                    if any(
                        owners_b[k2] is not None and carried[k2] is not None and abs(owners_b[k2] - carried[k2]) > 1.0
                        for k2 in range(n)
                    ):
                        continue
                mapping = map_columns(cols_a, cols_b)
                owners = [None if mapping[i2] is None else at(owners_b, mapping[i2]) for i2 in range(len(cols_a))]
                out.append(
                    (
                        pno,
                        {
                            "prem": prem,
                            "ph": ph,
                            "sh": sh_a or [],
                            "pat": owners,
                            "decl": decl or decl2,
                            "joined": pno2,
                            "owners_built": True,
                            "cols": [q for _x, q in cols_a],
                        },
                    )
                )
                break
            if tin is None or pat is None:
                continue
            shift = align(tout, tin)  # the two pages need not start at the same column
            if shift is None:
                continue  # columns do not line up — refuse to join
            share_at = -1
            for j, (lab, vals) in enumerate(rows2):
                if not vals and R_SHARE_HEAD.search(lab):
                    share_at = j
            sh = pick_row(rows2, R_SH_INV, after=share_at) if share_at >= 0 else None
            out.append(
                (
                    pno,
                    {
                        "prem": prem,
                        "ph": ph,
                        "sh": reindex(sh, shift),
                        "pat": reindex(pat, shift),
                        "decl": decl or decl2,
                        "joined": pno2,
                        "shift": shift,
                    },
                )
            )
            break
    return out


def build(rows, life, decl):
    prem = pick_row(rows, R_NETPREM if life else R_PREMEARNED)
    if prem is None:
        return None
    ph = pick_row(rows, R_PH_INV)
    # the shareholders' investment income must come from BELOW the SHAREHOLDERS' A/C heading —
    # searching the whole page picks a policyholders' or segment row with a similar label
    # The shareholders' section marker is a bare heading in the life format ("SHAREHOLDERS' A/C")
    # but a figure row in the general format ("Income in shareholders' account (a+b+c):"), so it
    # cannot be required to be value-less. Taking the LAST match is what keeps the life format
    # right: "Transferred to Shareholders A/c" also matches, but it sits above the real heading.
    share_at = -1
    for i, (lab, _vals) in enumerate(rows):
        if R_SHARE_HEAD.search(lab):
            share_at = i
    sh = pick_row(rows, R_SH_INV, after=share_at) if share_at >= 0 else None
    pat = pick_row(rows, R_PAT)
    if ph is None or pat is None:
        return None
    # `decl` is the page's own title ("Statement of Consolidated Unaudited Results for the Quarter
    # ended ..."). That declaration is the tiebreaker the PAT anchor cannot give: HDFCLIFE
    # Mar-2024 stores std 411.66 and con 411.64, well inside anchor tolerance, so the standalone
    # page would happily anchor to the con slot and duplicate itself there (runbook §44, ISEC).
    return {"prem": prem, "ph": ph, "sh": sh or [], "pat": pat, "decl": decl}


def at(vec, k):
    return vec[k] if vec and k < len(vec) else None


def solve(page_data, stored_pat):
    """(revenue, column_index, scale_name, pat_seen) under A1 + A2, or None.

    Every row is indexed by the PAGE's column geometry, so column k means the same period in the
    revenue rows as in the PAT row. The premium and policyholders'-investment legs must BOTH be
    present in that column — a column where they are missing is a header/annual artefact, not a
    quarter we can total."""
    best = None
    for name, div in SCALES:
        for k, p in enumerate(page_data["pat"]):
            if p is None:
                continue
            seen = p / div
            if abs(seen - stored_pat) > max(2.0, 0.03 * max(abs(seen), abs(stored_pat))):
                continue
            prem, ph = at(page_data["prem"], k), at(page_data["ph"], k)
            if prem is None or ph is None:
                continue
            rev = (prem + ph + (at(page_data["sh"], k) or 0.0)) / div
            err = abs(seen - stored_pat)
            if best is None or err < best[4]:
                best = (round(rev, 2), k, name, round(seen, 2), err)
    return best[:4] if best else None


def anns_with_retry(sess, code, lo, hi, tries=3):
    """(filings, session) — an EMPTY announcement list is not proof of absence.

    BSE rate-limits per IP (runbook §0: the 162-byte stub). Over quota, datebound()'s inner
    `except: break` swallows the failure and returns [], which reads exactly like "this company
    filed nothing that quarter". That produced seven false "no result filing" verdicts for NIACL
    on 2026-08-06 — every one of which returned two real filings when retried on a fresh session.
    So: retry on a NEW session with a pause before believing an empty result."""
    for attempt in range(tries):
        try:
            got = FI.datebound(sess, code, lo, hi)
        except Exception:
            got = []
        if got:
            return got, sess
        if attempt < tries - 1:
            time.sleep(3.0 * (attempt + 1))
            sess = FI.bse_session()
    return [], sess


def main():
    argv = sys.argv
    only = set(argv[argv.index("--only") + 1].split(",")) if "--only" in argv else None
    one_qe = int(argv[argv.index("--qe") + 1]) if "--qe" in argv else None
    apply_it = "--apply" in argv

    targets = json.load(open(TARGETS))
    revop = json.load(open(REVOP_DOCS))
    ledger = json.load(open(REVOP_LEDGER))
    fund = json.load(open(FUND))
    fmap = {s: {r[0]: r for r in rows} for s, rows in fund.items()}
    codes = json.load(open(SCRIPS))["by_id"]
    fills = json.load(open(FILLS)) if os.path.exists(FILLS) else {}
    skips = json.load(open(SKIPS)) if os.path.exists(SKIPS) else {}
    os.makedirs(PDFCACHE, exist_ok=True)

    syms = [s for s in sorted(targets) if s in LIFE | GENERAL]
    if only:
        syms = [s for s in syms if s in only]
    sess = FI.bse_session()
    nread = 0

    for sym in syms:
        life = sym in LIFE
        code = codes.get(sym)
        if not code:
            skips[f"{sym}|code"] = "no BSE scrip code"
            continue
        qes = sorted(set(targets[sym]["revS"] + targets[sym]["revC"]))
        if one_qe:
            qes = [q for q in qes if q == one_qe]
        for qe in qes:
            need = [b for b, fld in (("std", "revS"), ("con", "revC")) if qe in targets[sym][fld]]
            need = [b for b in need if "%s|%d|%s" % (sym, qe, b) not in fills]
            if not need:
                continue
            y, m, d = qe // 10000, (qe // 100) % 100, qe % 100
            lo = "%04d%02d%02d" % (y + (m + 1) // 12, (m % 12) + 1, 5)

            # ADAPTIVE WINDOW — narrow first, widen only on failure (2026-08-10).
            # The wide window exists because several insurers publish NO consolidated statement in
            # the quarter's own pack (HDFCLIFE filed std-only through FY24), so the target quarter
            # lives in a LATER pack's preceding-quarter / year-ago column. Every read is anchored
            # to the TARGET quarter's stored PAT via the printed column date and controlled by the
            # A5 std check, so a later pack passes exactly the same gates (TIMKEN Jun-25).
            # But scanning 15 months of packs costs ~33 min/quarter under OCR (measured on GICRE),
            # against ~10 min for the quarter's own season — and MOST quarters land from their own
            # pack. So try the 4-month window first and only pay for the wide one when it fails.
            def _hi(months):
                hm, hy = ((m + months - 1) % 12) + 1, y + (m + months - 1) // 12
                return "%04d%02d%02d" % (hy, hm, 28)

            got, used_ocr, seen_att, anns = {}, False, set(), []
            for _w in (4, 15):
                hi = _hi(_w)
                anns, sess = anns_with_retry(sess, str(code), lo, hi)
                # earliest result filing after quarter-end first (runbook §3)
                for adate, att, _sub in sorted(anns):
                    if att in seen_att:
                        continue  # already read under the narrow window
                    seen_att.add(att)
                    p = os.path.join(PDFCACHE, "%s_%d_%s" % (sym, qe, re.sub(r"[^A-Za-z0-9.]", "_", att)))
                    if os.path.exists(p) and os.path.getsize(p) > 5000:
                        pdf = open(p, "rb").read()
                    else:
                        pdf = FI.fetch_pdf(sess, att)
                        if not pdf:
                            continue
                        open(p, "wb").write(pdf)
                    try:
                        doc = fitz.open(stream=pdf, filetype="pdf")
                    except Exception:
                        continue
                    try:
                        cands = read_doc(doc, life)
                    except Exception:
                        cands = []
                    std_pat = (fmap.get(sym, {}).get(qe) or [None, None, None, None])[1]
                    std_solvable = std_pat is not None and any(
                        solve(pd, std_pat) for _p, pd in cands if pd.get("decl") != "con"
                    )
                    if not any(pd.get("decl") == "con" for _p, pd in cands) or not std_solvable:
                        # Text layer gave no consolidated statement OR no std page the A5 control
                        # could anchor. Either can be corruption rather than absence (GICRE's layer
                        # reads "OPERA TING RES UL TS", and a garbage page can even carry a con
                        # declaration, which used to SUPPRESS this fallback and surface as
                        # "std control failed: filing reads None"). Re-read with OCR before judging.
                        try:
                            ocr_cands = read_doc(doc, life, ocr=True)
                        except Exception:
                            ocr_cands = []
                        if ocr_cands:
                            cands = ocr_cands
                            used_ocr = True

                    def best_for(basis):
                        stored = (fmap.get(sym, {}).get(qe) or [None, None, None, None])[1 if basis == "std" else 3]
                        if stored is None:
                            return None
                        hits = []
                        for pno, pd in cands:
                            # the page must not DECLARE the other basis (see build()'s `decl`)
                            if pd.get("decl") and pd["decl"] != basis:
                                continue
                            s = solve(pd, stored)
                            if s:
                                hits.append((0 if pd.get("decl") == basis else 1, abs(s[3] - stored), pno, s))
                        if not hits:
                            return None
                        hits.sort()
                        return hits[0][2], hits[0][3], ("declared" if hits[0][0] == 0 else "undeclared")

                    # A5 — this filing must first reproduce the standalone revenue we already store
                    ctrl_stored = ((revop.get(sym) or {}).get(str(qe)) or [None])[0]
                    ctrl = best_for("std")
                    ctrl_ok = (
                        ctrl is not None
                        and ctrl_stored is not None
                        and abs(ctrl[1][0] - ctrl_stored) <= max(1.0, 0.005 * abs(ctrl_stored))
                    )
                    for basis in need:
                        if basis == "con" and not ctrl_ok:
                            skips["%s|%d|con" % (sym, qe)] = (
                                f"std control failed: filing reads {round(ctrl[1][0], 2) if ctrl else None} against stored {ctrl_stored}"
                            )
                            continue
                        b = best_for(basis)
                        if not b:
                            continue
                        # A3 — the consolidated figure must NOT come from the page that just served as
                        # the standalone control. NIACL Jun-2023 stores std and con PAT identically
                        # (260.23 both), so one page satisfies both anchors and would duplicate itself
                        # into the con slot (runbook §44, the ISEC bug).
                        if basis == "con" and ctrl and b[0] == ctrl[0]:
                            skips["%s|%d|con" % (sym, qe)] = (
                                "same page (p%d) served both bases — refusing to duplicate, runbook §44" % b[0]
                            )
                            continue
                        got.setdefault(basis, (b[0], b[1], att, adate, b[2], round(ctrl[1][0], 2) if ctrl else None))
                    if len(got) == len(need):
                        break
                if len(got) == len(need):
                    break  # narrow window sufficed — skip the wide pass
            if not seen_att:
                skips["%s|%d|list" % (sym, qe)] = f"no result filing in {lo}..{hi} after 3 tries on fresh sessions"
                continue
            # A3 — distinct page per basis
            if len(got) == 2 and got["std"][0] == got["con"][0]:
                skips["%s|%d|both" % (sym, qe)] = (
                    "one page satisfied BOTH bases (p%d) — refusing to duplicate it, runbook §44" % got["std"][0]
                )
                got = {}
            for basis, (pno, s, att, adate, how, ctrl_rev) in got.items():
                key = "%s|%d|%s" % (sym, qe, basis)
                rev, col, scale, pat_seen = s
                fills[key] = {
                    "rev": rev,
                    "basis": basis,
                    "page": pno,
                    "column": col,
                    "reader": "ocr" if used_ocr else "text",
                    "scale": scale,
                    "anchor": pat_seen,
                    "page_basis": how,
                    "std_control": ctrl_rev,
                    "stored_pat": (fmap[sym][qe][1 if basis == "std" else 3]),
                    "src": f"BSE {att} (filed {adate})",
                    "fin": 1,
                }
                nread += 1
                print(
                    "%-11s %d %-3s rev %-11.2f p%-3d col%d %-7s anchor %.2f  %s (std ctrl %s)"
                    % (sym, qe, basis, rev, pno, col, scale, pat_seen, how, ctrl_rev),
                    flush=True,
                )
            for basis in need:
                k = "%s|%d|%s" % (sym, qe, basis)
                if basis in got:
                    skips.pop(k, None)  # an earlier filing's failure is not the verdict
                else:
                    skips.setdefault(k, f"no page anchored to stored {basis} PAT")
            json.dump(fills, open(FILLS, "w"), indent=1, sort_keys=True)
            json.dump(skips, open(SKIPS, "w"), indent=0, sort_keys=True)

    print("\nREAD %d cells this run (%d ledgered)" % (nread, len(fills)))
    if not apply_it:
        print("(dry run — ledgers written, data files untouched)")
        return

    # ★ DUPLICATE-VALUE GUARD — the check that would have caught the 2026-08-06 column bug.
    # Two quarters of the same company reporting the SAME revenue to the paisa is the fingerprint
    # of a column misalignment (one quarter's figure wearing another's anchor). Real revenue
    # repeating exactly across quarters does not happen at these magnitudes. Refuse the whole
    # apply rather than land a plausible wrong number.
    by_sym = defaultdict(list)
    for key, v in fills.items():
        sym_, qe_, basis_ = key.split("|")
        if v.get("rev") is not None:
            by_sym[(sym_, basis_)].append((qe_, v["rev"]))
    dupes = []
    for (sym_, basis_), items in sorted(by_sym.items()):
        seen = {}
        for qe_, rev in sorted(items):
            if rev in seen:
                dupes.append(f"{sym_} {basis_}: {seen[rev]} and {qe_} both {rev:.2f}")
            seen[rev] = qe_
    if dupes:
        print("REFUSING TO APPLY — duplicate revenue across quarters (column misalignment):")
        for d in dupes:
            print("   " + d)
        sys.exit(2)

    applied = 0
    for key, v in sorted(fills.items()):
        sym, qe_s, basis = key.split("|")
        row = (revop.get(sym) or {}).get(qe_s)
        if row is None:
            continue
        slot = 0 if basis == "std" else 1
        if row[slot] is None and v.get("rev") is not None:
            row[slot] = v["rev"]
            applied += 1
            lrow = ledger.setdefault(sym, {}).get(qe_s)
            if lrow is None:
                ledger[sym][qe_s] = list(row)
            elif lrow[slot] is None:
                lrow[slot] = v["rev"]
        if row[6] is None:
            row[6] = 1
    json.dump(revop, open(REVOP_DOCS, "w"), separators=(",", ":"))
    json.dump(ledger, open(REVOP_LEDGER, "w"), separators=(",", ":"))
    print("APPLIED %d insurer revenue cells" % applied)


_init_norm_map()  # R_* patterns exist by now


if __name__ == "__main__":
    main()
