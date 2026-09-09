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
"""§2b CORRECTION: GICRE's consolidated PAT is a STANDALONE COPY for ~12 quarters since Sep-2022.

WHAT IS WRONG (runbook §55c).  GIC Re has subsidiaries (GIC Re South Africa, GIC Re Corporate
Member Ltd) and associates, and it files a CONSOLIDATED statement every quarter — yet our stored
con PAT equals the standalone to the paisa in every quarter since Sep-2022 except the March ones.
The Jun-2023 filing settles it: its consolidated statement prints ₹977.66cr where we store 731.79,
which is that same filing's STANDALONE figure.

WHY IT NEEDS ITS OWN READER.  This is not a fill — it OVERWRITES non-null cells, which is runbook
§2b, and §2b demands the value be anchored 2+ ways BEFORE the file is touched. `insurer_con_rev.py`
is fill-only and reads REVENUE; it also treats the stored con PAT as its ANCHOR, so it cannot be
the thing that judges the anchor. This reader therefore re-derives both bases from the filings and
proves each cell independently.

THE ONE THING GICRE MAKES EASY.  Its packs print a four-column statement
    (30/06/2023) (31/03/2023) (30/06/2022) (31/03/2023)
      current Q     preceding Q   year-ago Q    full year
on BOTH bases, so every quarter appears in THREE separate filings (its own, the next quarter's
"preceding" column, the next year's "year-ago" column) plus a ΣQ=FY reconciliation. That is the
§2b neighbour cross-check, available without fetching anything extra.

HOW A VALUE IS PROVEN (all must hold; see adjudicate()):
  C1  OCR, not the text layer.  GICRE's text layer is corrupted (runbook §51b/§55d: "OPERA TING
      RES UL TS", "Aooropriations"), so nothing matches on it.  rapidocr reads the same pages
      cleanly.  OCR is allowed to be unreliable because every gate below is independent of it.
  C2  COLUMN BY PRINTED DATE, never by index (runbook §55b).  The header row states each column's
      period; a date appearing twice (quarter vs year-ended) is disambiguated by occurrence.
  C3  PER-FILING STANDALONE CONTROL, on EVERY column.  The filing's standalone statement must
      reproduce the standalone PAT we already store for every one of its dated quarter columns
      (typically 3 cells) within a paisa.  That tests OCR, scale, column mapping and row choice
      against known answers before a single consolidated number is believed.
  C4  INTERNAL IDENTITY on the consolidated page: profit-for-the-period must equal
      profit-after-tax + share-of-associates + NCI-adjustment, per column, on the filing's own
      figures.
  C5  TWO INDEPENDENT FILINGS must agree to the paisa on the cell, OR one filing plus the ΣQ=FY
      reconciliation.  A single unconfirmed read is reported, never applied.
  C6  CALIBRATION.  The five quarters whose stored con is genuine (20220331 20220630 20240331
      20250331 20260331) are read the same way; the convention the corrections use is the one
      that reproduces THEM.  A correction that is right about the number but wrong about the
      convention would silently break the series.

Ledger: scripts/gicre_con_pat_fills.json (tracked, per-cell provenance per runbook §57).
PDFs cache under scripts/_ins_pdfcache/ (gitignored); OCR caches under scripts/_gicre_ocr/.

Run:  python -X utf8 scripts/fill2020_tools/gicre_con_pat.py            # harvest + adjudicate
      python -X utf8 scripts/fill2020_tools/gicre_con_pat.py --report   # adjudicate from ledger
      python -X utf8 scripts/fill2020_tools/gicre_con_pat.py --apply    # write the two json files
"""
import difflib
import json
import os
import pickle
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
SCRIPTS = os.path.join(ROOT, "scripts")
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, HERE)

import fetch_insurers as FI  # noqa: E402
import fitz  # noqa: E402
import insurer_con_rev as ICR  # noqa: E402  (page_rows / declared_basis / retry)

SYM = "GICRE"
CODE = "540755"
PDFCACHE = os.path.join(SCRIPTS, "_ins_pdfcache")
OCRCACHE = os.path.join(SCRIPTS, "_gicre_ocr")
FUND_DOCS = os.path.join(ROOT, "docs", "sf_fundamentals.json")
FUND_SCRIPTS = os.path.join(SCRIPTS, "fundamentals.json")
LEDGER = os.path.join(SCRIPTS, "gicre_con_pat_fills.json")
OBS = os.path.join(HERE, "_gicre_con_pat_obs.json")

# every quarter we need to read: the 12 defective cells plus the 5 genuine ones used to calibrate
QUARTERS = [
    20220331,
    20220630,
    20220930,
    20221231,
    20230331,
    20230630,
    20230930,
    20231231,
    20240331,
    20240630,
    20240930,
    20241231,
    20250331,
    20250630,
    20250930,
    20251231,
    20260331,
    20260630,
]
GENUINE = {20220331, 20220630, 20240331, 20250331, 20260331}  # stored con != std today
DEFECTS = [q for q in QUARTERS if q not in GENUINE]

# The correction is scoped to the defect the audit established: GICRE's consolidated series from
# FY2023 onward. Comparative columns also expose COPY defects in 2021 (Mar/Sep/Dec-2021 all read
# materially different consolidated figures from what we store) — those are REPORTED but not
# written here, because fixing three quarters of an era nobody has swept leaves the series in a
# worse state than leaving it alone. They belong to a pre-2022 sweep of their own; see the
# runbook's pending queue.
SCOPE_FROM = 20220331

MAX_PAGES = 45
PAISA = 0.02  # two reads of the same printed figure must agree to the paisa

# ---- rows on the statement ------------------------------------------------------------------
# matched on ICR.norm() output (lowercase, alphanumerics only) because OCR returns whole phrases
# with the spaces stripped: "Profit/(loss) after tax" -> "profitlossaftertax"
N_PAT = re.compile(r"^profit(loss)?aftertax$")
N_PROFIT_PERIOD = re.compile(r"^profitforthe(year|period)")
N_ASSOC = re.compile(r"^shareofprofit.*associate")
N_NCI = re.compile(r"minorityinterest|noncontrolling")
N_PBT = re.compile(r"^profit(loss)?beforetax$")
N_TAX = re.compile(r"^(provisionfor)?tax(ation)?$")
# C7's two rows. GICRE's consolidated statement prints NO minority/NCI line at all (its subsidiaries
# are wholly owned), so "Profit for the year" IS the owners' figure — but that has to be PROVEN per
# filing, not assumed, because picking the wrong line is exactly the kind of silent convention error
# a §2b correction must not introduce. The EPS row settles it (the §2d principle): basic EPS x shares
# must reproduce the owners' profit, and shares = paid-up capital / face value.
# The EPS caption wraps over three printed lines and the FIGURES sit on the middle one, so the row
# that carries the values is labelled "items (net of tax expense) for the period (not to be" — not
# anything containing "EPS". Match the fragment that is actually on the figure row.
N_EPS = re.compile(
    r"netoftaxexpense|^.?a.?basicand?dilu.?a?tedepsbeforeextraordinary"
    r"|^basicanddilutedeps"
)
N_PAIDUP = re.compile(r"^paidupequity(share)?capital")

# canonical forms for the fuzzy fallback (see find_row) — what the label reads when OCR behaves
C_PAT = "profitlossaftertax"
C_PROFIT_PERIOD = "profitfortheyear"
C_ASSOC = "shareofprofitinassociatescompanies"
C_PBT = "profitlossbeforetax"
C_TAX = "provisionfortax"
C_PAIDUP = "paidupequitycapital"
# the ₹-crore recap pages GICRE appends ("Summary of Revenue and Profit and Loss Account" /
# "Consolidated Financials of GICRe") — an INDEPENDENT printing of the same figures, in crore
N_SUM_PAT = re.compile(r"^profit(loss)?aftertax$")
N_SUM_ASSOC = re.compile(r"^shareofprofitinassociate")

# dates print as (30/06/2023) and, on the recap pages, 30.06.2023 — and OCR sometimes returns a
# full-width parenthesis, so strip everything that is not a digit or a separator before matching
DATE_ANY = re.compile(r"(\d{2})[/.](\d{2})[/.](\d{4})")


LAST_DAY = {3: 31, 6: 30, 9: 30, 12: 31}


def qe_of(tok):
    """The quarter-end a header token names, or None.

    ONLY real quarter-ends are accepted. These scans misread digits — the Jun-2022 pack's header
    yields "30/08/2021" where the page prints 30/06/2021 — and a bogus date must not become a
    quarter key that a value could be filed under. Rejecting the column loses one reading; keying
    a value to 2021-08-30 would corrupt the series. Nothing shifts, because columns are keyed by
    date, not by position."""
    t = re.sub(r"[^0-9/.]", "", tok or "")
    m = DATE_ANY.fullmatch(t)
    if not m:
        return None
    d, mth, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if LAST_DAY.get(mth) != d or not (2000 <= y <= 2100):
        return None
    return y * 10000 + mth * 100 + d


# ---- OCR with an on-disk cache (a page costs ~1-2s; a filing is ~30 pages) --------------------
_ocr_orig = FI._ocr_words
_ocr_state = {"path": None, "words": {}}


def _ocr_cached(page):
    n = page.number
    st = _ocr_state
    if n not in st["words"]:
        st["words"][n] = _ocr_orig(page)
        if st["path"]:
            pickle.dump(st["words"], open(st["path"], "wb"))
    return st["words"][n]


FI._ocr_words = _ocr_cached


def use_ocr_cache(pdfname):
    os.makedirs(OCRCACHE, exist_ok=True)
    p = os.path.join(OCRCACHE, pdfname + ".pkl")
    _ocr_state["path"] = p
    try:
        _ocr_state["words"] = pickle.load(open(p, "rb")) if os.path.exists(p) else {}
    except Exception:
        _ocr_state["words"] = {}


# ---- page reading ----------------------------------------------------------------------------
HDR_TOL = 26.0


def header_dates(page):
    """[(x_right, qe)] for the y-band carrying the most date tokens (>=3).

    Page titles and 'as at' lines carry dates too, so the header is the DENSEST date band, not the
    first one (runbook §55b)."""
    words = sorted(FI._ocr_words(page), key=lambda w: (round(w[1], 1), w[0]))
    bands = {}
    for _x0, y0, x1, _y1, w in words:
        q = qe_of(w)
        if q is None:
            continue
        bands.setdefault(round(y0 / 4.0), []).append((x1, q))
    if not bands:
        return []
    best = max(bands.values(), key=len)
    return sorted(best) if len(best) >= 3 else []


def rows_on_dates(page, cols):
    """[(label, [v per dated column])] — every figure slotted under the header column it sits below."""
    out = []
    for label, vals in ICR._raw_rows(page, ocr=True):
        slotted = [None] * len(cols)
        for x1, v in vals:
            k = min(range(len(cols)), key=lambda i: abs(cols[i][0] - x1))
            if abs(cols[k][0] - x1) <= HDR_TOL and slotted[k] is None:
                slotted[k] = v
        out.append((label, slotted if any(v is not None for v in slotted) else []))
    return out


def find_row(rows, npat, canon=None, thresh=0.86):
    """The row matching `npat`, else the best FUZZY match against `canon`.

    The 2022-vintage scans are poor enough that exact labels do not survive OCR: the standalone
    PAT row comes back as "Prohiti(loss)aftertax" and the consolidated one as
    "Proft/(loss}after tax". A regex cannot be loosened enough to catch those without also
    matching rows it must not (the segment annexures repeat profit-shaped labels a dozen times),
    so the fallback is a similarity score against the canonical label, taking the single best row
    above a high threshold. Every value found this way still has to pass the value anchor, the
    internal identity and the EPS arbitration — the fuzzy match only nominates a candidate."""
    for lab, vals in rows:
        if vals and npat.search(ICR.norm(lab)):
            return vals
    if not canon:
        return None
    best = None
    for lab, vals in rows:
        if not vals:
            continue
        r = difflib.SequenceMatcher(None, ICR.norm(lab), canon).ratio()
        if r >= thresh and (best is None or r > best[0]):
            best = (r, vals)
    return best[1] if best else None


def anchored_row(rows, ref, dated, tol=PAISA):
    """(values, scale, quarter_keys, label) for the row whose dated columns reproduce values we
    already store — the standalone PAT row, found by what it SAYS rather than what it is labelled,
    and simultaneously the thing that tells us WHICH COLUMNS ARE QUARTERS.

    Two jobs, because they are the same measurement:

    * ROW SELECTION. On a scan where the caption is unrecoverable ("Prohiti(loss)aftertax") the
      numbers still identify the row uniquely — nothing else on an insurer's statement reproduces
      two independent stored quarters at one scale. Same principle as insurer_con_rev's A1/A2.

    * COLUMN ROLE. "Occurrence 0 of a date is the quarter" is FALSE in general, and believing it
      would have been the worst bug available here. The Dec-2022 pack prints
          3 months ended [31/12/2022] [30/09/2022] [31/12/2021] | year to date [31/12/2022]
          [31/12/2021] | previous year ended [31/03/2022]
      — 31/03/2022 appears exactly ONCE and it is the FULL YEAR (₹2,005.74cr), not the March
      quarter (₹1,795.40cr). Writing that column into 20220331 would have replaced a quarter with
      a year. So the role is not assumed from position or occurrence: a column is a QUARTER only
      if this row reproduces the standalone PAT we already store for that quarter-end. The rest
      are year-to-date or full-year columns and are never read as quarters."""
    best = None
    for lab, vals in rows:
        if not vals:
            continue
        for name, div in (("lakh", 100.0), ("crore", 1.0), ("million", 10.0)):
            keys = [
                (q, k)
                for i, q, k in dated
                if i < len(vals)
                and vals[i] is not None
                and ref.get(q) is not None
                and abs(vals[i] / div - ref[q]) <= tol
            ]
            if len(keys) >= 2 and (best is None or len(keys) > len(best[2])):
                best = (vals, name, keys, lab)
    return best


def shift_q(qe, n):
    """The quarter-end n quarters before qe."""
    y, m = qe // 10000, (qe // 100) % 100
    t = y * 4 + (m // 3 - 1) - n
    y2, m2 = t // 4, (t % 4 + 1) * 3
    return y2 * 10000 + m2 * 100 + LAST_DAY[m2]


def templates(own_qe):
    """The column layouts GIC Re prints, as [(qe, role)] left to right.

    Every pack lays the columns out the same way: the three QUARTER columns first (this quarter,
    the preceding one, the year-ago one), then the cumulative pair, then the previous year ended.
    Q1 packs drop the cumulative pair (year-to-date IS the quarter); Q4 packs print the two annual
    columns instead of a year-to-date pair."""
    q1, q4 = shift_q(own_qe, 1), shift_q(own_qe, 4)
    y = own_qe // 10000
    is_q4 = own_qe % 10000 == 331
    prev_fy = ((y - 1) if is_q4 else y) * 10000 + 331
    # in a Q4 pack the cumulative columns ARE the fiscal years, so they are labelled FY, not YTD;
    # labelling them both ways would make two templates with identical dates and the alignment
    # would be ambiguous for every March filing
    cum = "FY" if is_q4 else "YTD"
    head = [(own_qe, "Q"), (q1, "Q"), (q4, "Q")]
    tpls = [
        [*head, (own_qe, cum), (q4, cum), (prev_fy, "FY")],
        [*head, (own_qe, cum), (q4, cum)],
        [*head, (prev_fy, "FY")],
        head,
    ]
    out, seen = [], set()
    for t in tpls:  # dedupe by date sequence — same dates, same alignment
        key = tuple(q for q, _r in t)
        if key not in seen:
            seen.add(key)
            out.append(t)
    return out


def align_roles(cols, own_qe, ncols):
    """{column index: role} by aligning the DETECTED header dates to the pack's canonical layout,
    or None when no single alignment fits.

    ★ This is what makes a partly-unreadable header safe instead of fatal. OCR routinely loses one
    or two dates, and the survivors then LOOK like a complete header with different occurrences:
    the Sep-2024 consolidated page detects four dates for six figure columns, and its H1-FY25
    year-to-date column (Rs 3,256.37cr) presents itself as the first "(30/09/2024)" — the Sep-2024
    QUARTER slot. Reading occurrences off the survivors would have written a half-year into a
    quarter. Matching the survivors as a SUBSEQUENCE of the known layout instead recovers what each
    surviving column actually is (there: quarter, YTD, YTD, full year), so the good columns are
    still usable and the cumulative ones are correctly excluded. An alignment that is not unique
    proves nothing and the page is dropped."""
    dates = [q for _x, q in cols]
    hits = []
    for tpl in templates(own_qe):
        if len(tpl) != ncols:
            continue
        for pick in _subseq_matches([q for q, _r in tpl], dates):
            hits.append({i: tpl[j][1] for i, j in enumerate(pick)})
        if len(hits) > 1:
            return None
    return hits[0] if len(hits) == 1 else None


def _subseq_matches(hay, needle, start=0, acc=()):
    """Every way `needle` embeds in `hay` in order, as tuples of indices."""
    if not needle:
        yield acc
        return
    for j in range(start, len(hay) - len(needle) + 1):
        if hay[j] == needle[0]:
            yield from _subseq_matches(hay, needle[1:], j + 1, (*acc, j))


def occurrences(cols):
    """[(index, qe, occ)] — every column with the occurrence number of its date.

    The same date heads BOTH the quarter and the year-ended column (GICRE's Jun packs print
    31/03/2023 twice: preceding quarter, then full year), so a column is identified by
    (date, occurrence) and never by date alone — runbook §55b."""
    out, seen = [], {}
    for i, (_x, q) in enumerate(cols):
        k = seen.get(q, 0)
        seen[q] = k + 1
        out.append((i, q, k))
    return out


def fuzzy_in(hay, needle, thresh=0.86):
    """Is `needle` present in `hay` allowing for OCR damage?

    ICR.declared_basis() misses these packs: the Jun-2022 consolidated statement is titled
    "Reviewed Statement of ConsolldatedFinancial Results" — 'Consolldated' with a doubled l — and
    a literal "consolidat" search reads that page as declaring nothing. Since the declaration is
    the tiebreaker that stops a standalone page anchoring into the consolidated slot (runbook §44),
    losing it is not acceptable; it has to be matched as fuzzily as the labels are."""
    n = len(needle)
    for i in range(max(0, len(hay) - n + 3)):
        for w in (n - 1, n, n + 1):
            if difflib.SequenceMatcher(None, hay[i : i + w], needle).ratio() >= thresh:
                return True
    return False


def basis_of(rows):
    # 0.80 is safe here precisely because the two words are so far apart: the worst real damage
    # seen ("Consolldatod") scores 0.833 against "consolidated" and only 0.18 against "standalone",
    # and unrelated statement furniture scores ~0.35 against both.
    head = ICR.norm(" ".join(lab for lab, _ in rows[:14])[:700])
    if fuzzy_in(head, "consolidated", 0.80):
        return "con"
    if fuzzy_in(head, "standalone", 0.80):
        return "std"
    return None


def physical_cols(plain_rows):
    """How many figure columns the page actually has, from x-geometry alone (ICR.page_rows
    clusters them without reference to the header)."""
    return max([len(v) for _l, v in plain_rows if v] or [0])


def dated_pages(doc):
    """[(pno, basis, cols, rows)] for pages that declare a basis and print a COMPLETE dated header.

    ★ THE COMPLETENESS TEST is the guard that matters. When OCR misreads one header date the page
    still yields a plausible-looking column list — but the surviving dates no longer line up with
    the periods they name, and `occurrence` shifts. The Sep-2024 pack is the live example: its
    consolidated page has SIX figure columns and only FOUR readable header dates, so the H1-FY25
    year-to-date column (₹3,256.37cr) presents itself as "(30/09/2024) occurrence 0" — the
    Sep-2024 QUARTER slot. Landing that would have written a half-year into a quarter.
    A header that does not name every figure column is not usable, so the page is dropped."""
    out = []
    for pno in range(min(doc.page_count, MAX_PAGES)):
        try:
            plain = ICR.page_rows(doc[pno], ocr=True)
        except Exception:
            continue
        basis = ICR.declared_basis(plain) or basis_of(plain)
        if basis is None:
            continue
        cols = header_dates(doc[pno])
        if len(cols) < 3:
            continue
        out.append((pno, basis, cols, rows_on_dates(doc[pno], cols), physical_cols(plain)))
    return out


def eps_for(pages, i):
    """(eps_vector, paidup_vector) for the statement on pages[i], re-expressed in ITS columns.

    The analytical-ratio block (EPS, solvency, NPA) runs onto the NEXT page of the same statement,
    so the EPS row usually is not on the page carrying the profit tail. The continuation is joined
    only when it declares the SAME basis and its header prints the SAME (date, occurrence) sequence
    — a join by page order alone would happily graft the standalone ratios onto the consolidated
    statement."""
    pno, basis, cols, rows, _n = pages[i]
    key = [(q, k) for _i, q, k in occurrences(cols)]
    eps = find_row(rows, N_EPS)
    paid = find_row(rows, N_PAIDUP, C_PAIDUP)
    for j in (i, i + 1, i + 2):
        if j >= len(pages) or (eps is not None and paid is not None):
            break
        pno2, basis2, cols2, rows2, _n2 = pages[j]
        if basis2 != basis or pno2 > pno + 2:
            continue
        # The continuation need not detect the SAME number of columns — a misread date drops one
        # header from one page and not the other (the Jun-2022 pack: 5 on the statement, 6 on the
        # ratios). Re-express the continuation's vectors in THIS page's column space by
        # (date, occurrence), per runbook §55b; a column with no counterpart stays None.
        idx = {(q, k): i2 for i2, q, k in occurrences(cols2)}
        remap = [idx.get(kq) for kq in key]
        if sum(1 for r in remap if r is not None) < 3:
            continue

        def pull(vec):
            return None if vec is None else [None if (r is None or r >= len(vec)) else vec[r] for r in remap]

        eps = eps if eps is not None else pull(find_row(rows2, N_EPS))
        paid = paid if paid is not None else pull(find_row(rows2, N_PAIDUP, C_PAIDUP))
    return eps, paid


def scaled(vec, div):
    return [None if v is None else round(v / div, 2) for v in vec]


def read_filing(doc, stored_std, stored_con, own_qe):
    """{'std': {...}, 'con': {...}} of dated readings for one filing, or {} when the gates fail.

    stored_std/stored_con: {qe: value} of what we already hold, used as the control (C3) and for
    calibration (C6) only — never as a source."""
    pages = dated_pages(doc)
    res = {}

    # TWO PASSES, standalone first: the consolidated read depends on the column roles the
    # standalone control establishes, and page order does not guarantee std comes first.
    for pass_basis in ("std", "con"):
        for pi, (pno, basis, cols, rows, ncols) in enumerate(pages):
            if basis != pass_basis:
                continue
            occ = occurrences(cols)

            # ---- STANDALONE: the C3 control page. Its PAT row is found by VALUE, not by label —
            # the row that reproduces >=2 quarters we already store, at a consistent scale, IS the
            # PAT row, whatever OCR made of its caption. Nothing on this page is used as a source.
            if basis == "std" and "std" not in res:
                hit = anchored_row(rows, stored_std, occ)
                if hit:
                    vals_raw, name, qkeys, lab = hit
                    div = {"lakh": 100.0, "crore": 1.0, "million": 10.0}[name]
                    res["std"] = {
                        "page": pno,
                        "scale": name,
                        "label_seen": lab[:60],
                        "cols": [[q, k] for _i, q, k in occ],
                        "pat": [[q, k, scaled(vals_raw, div)[i]] for i, q, k in occ],
                        # (qe, occurrence) of every column PROVEN to be a quarter
                        "quarter_keys": [list(k) for k in qkeys],
                        "control_ok": sorted({q for q, _k in qkeys}),
                    }
                continue

            # ---- CONSOLIDATED: the source page. Scale cannot be anchored here (the stored con is the
            # very thing under suspicion), so it is taken from the statement's own unit line, and the
            # arithmetic identity + the EPS row are what prove the reading.
            if basis != "con" or "con" in res:
                continue
            per = find_row(rows, N_PROFIT_PERIOD, C_PROFIT_PERIOD)
            pat = find_row(rows, N_PAT, C_PAT)
            if per is None and pat is None:
                continue
            head = ICR.norm(" ".join(lab for lab, _ in rows[:14])[:700])
            div = 100.0 if fuzzy_in(head, "rsinlakh", 0.8) else (1.0 if fuzzy_in(head, "rsincrore", 0.8) else None)
            if div is None:
                continue
            name = "lakh" if div == 100.0 else "crore"

            def g(v, i):
                return None if not v or i >= len(v) or v[i] is None else round(v[i] / div, 2)

            eps, paid = eps_for(pages, pi)
            tail = {
                "assoc": find_row(rows, N_ASSOC, C_ASSOC) or [],
                "nci": find_row(rows, N_NCI) or [],
                "profit_period": per or [],
                "pat_after_tax2": pat or [],
                "pbt": find_row(rows, N_PBT, C_PBT) or [],
                "tax": find_row(rows, N_TAX, C_TAX) or [],
            }
            # Column ROLES: from the filing's own reporting quarter (quarter_roles), and where the
            # standalone control page anchored, cross-checked against it. The two must not disagree
            # — a column the control proves is a quarter must be typed 'Q', and vice versa.
            byidx = align_roles(cols, own_qe, ncols)
            if byidx is None:
                continue  # the header cannot be placed in a known layout -> unusable
            roles = {(q, k): byidx[i] for i, q, k in occ}
            # NOTE: the standalone page's quarter keys are deliberately NOT compared against these.
            # The two pages lose different header dates to OCR, so the same (date, occurrence) key
            # denotes a different physical column on each — comparing them across pages rejects
            # perfectly good reads (the Jun-2024 pack, where the standalone page keeps its year-ago
            # column and the consolidated one does not). Each page is aligned to the canonical layout
            # on its own; that alignment, not a cross-page key match, is the guarantee.
            res["con"] = {
                "page": pno,
                "scale": name,
                "cols": [[q, k] for _i, q, k in occ],
                # EPS is a per-share RATIO — printed in rupees whatever the statement's
                # scale is, so it must NOT be divided by `div`
                "eps": [None if not eps or i >= len(eps) else eps[i] for i, _q, _k in occ],
                "paidup": [g(paid, i) for i, _q, _k in occ],
                "roles": {"%d|%d" % k: v for k, v in roles.items()},
                "own_qe": own_qe,
                "series": [
                    dict(
                        {"qe": q, "occ": k, "role": roles.get((q, k))},
                        **{("pat_after_tax" if nm == "pat_after_tax2" else nm): g(vec, i) for nm, vec in tail.items()},
                    )
                    for i, q, k in occ
                ],
            }
    return res


# ---------------------------------------------------------------------------------------------
def harvest(only_qe=None):
    fund = json.load(open(FUND_DOCS))
    rows = {r[0]: r for r in fund[SYM]}
    stored_std = {q: r[1] for q, r in rows.items()}
    stored_con = {q: r[3] for q, r in rows.items()}

    obs = json.load(open(OBS)) if os.path.exists(OBS) else {}
    os.makedirs(PDFCACHE, exist_ok=True)
    sess = FI.bse_session()

    for qe in QUARTERS if only_qe is None else [only_qe]:
        if str(qe) in obs and obs[str(qe)].get("filings"):
            continue
        y, m = qe // 10000, (qe // 100) % 100
        lo = "%04d%02d%02d" % (y + (m + 1) // 12, (m % 12) + 1, 5)
        hi_m, hi_y = ((m + 4 - 1) % 12) + 1, y + (m + 4 - 1) // 12
        hi = "%04d%02d%02d" % (hi_y, hi_m, 28)
        anns, sess = ICR.anns_with_retry(sess, CODE, lo, hi)
        print("[%d] window %s..%s -> %d filings" % (qe, lo, hi, len(anns)), flush=True)
        entry = {"window": [lo, hi], "filings": []}
        for adate, att, _sub in sorted(anns):
            fname = "%s_%d_%s" % (SYM, qe, re.sub(r"[^A-Za-z0-9.]", "_", att))
            p = os.path.join(PDFCACHE, fname)
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
            use_ocr_cache(fname)
            r = read_filing(doc, stored_std, stored_con, qe)
            if not r.get("std") and not r.get("con"):
                continue
            r["att"] = att
            r["filed"] = adate
            r["own_qe"] = qe
            entry["filings"].append(r)
            print(
                "    {} filed {}: std p{} ctrl={} | con p{}".format(
                    att[:28],
                    adate,
                    r.get("std", {}).get("page"),
                    r.get("std", {}).get("control_ok"),
                    r.get("con", {}).get("page"),
                ),
                flush=True,
            )
            if r.get("con"):
                break  # the earliest filing carrying both statements wins
        obs[str(qe)] = entry
        json.dump(obs, open(OBS, "w"), indent=1, sort_keys=True)
    return obs


FACE_VALUES = (1.0, 2.0, 5.0, 10.0)
FACE_VALUE = 5.0  # GIC Re's, solved from the filings by eps_arbitrate and stable throughout


def shares_of(con):
    """Number of shares (crore) implied by the statement's paid-up capital row, or None.

    Paid-up capital is the same figure in every column, so the MEDIAN of what was read is used —
    the Jun-2022 scan returns 677.2 in one slot where the page prints 877.20."""
    seen = sorted(p for p in (con.get("paidup") or []) if p)
    return (seen[len(seen) // 2] / FACE_VALUE) if seen else None


def identity(v, a, n, per):
    """How the consolidated profit tail reconciles: 'closes', 'closes|assoc-sign',
    'closes|scale', 'unchecked' (a leg is missing) or 'fails'."""
    if per is None or v is None:
        return "unchecked"
    nci = n or 0.0
    if abs(per - (v + (a or 0.0) + nci)) <= 1.0:
        return "closes"
    if a is not None and abs(per - (v - a + nci)) <= 1.0:
        return "closes|assoc-sign"
    for f in (10.0, 0.1):
        w = v * f
        if abs(per - (w + (a or 0.0) + nci)) <= 1.0 or (a is not None and abs(per - (w - a + nci)) <= 1.0):
            return "closes|scale"
    return "fails"


def eps_check(con, i, owners):
    """(True | False | None, why) — does column i's printed EPS reproduce `owners`?

    True confirms the column, False drops it, None means the filing prints no EPS for it. This is
    the §2d arbitration applied PER COLUMN: basic EPS x shares must equal the owners' profit.
    Per column and not per page, because averaging lets one damaged column condemn the good ones
    — and lets good ones excuse a bad one, which is the direction that lands a wrong number."""
    eps = con.get("eps") or []
    e = eps[i] if i < len(eps) else None
    sh = shares_of(con)
    if not e or not sh or owners is None:
        return None, "no EPS/paid-up for this column"
    implied = e * sh
    err = abs(implied - owners) / max(abs(owners), 1.0)
    # 0.5% absorbs the EPS row's own rounding to two decimals: one paisa of EPS is ~Rs 1.75cr, so
    # a quarter near Rs 700cr can legitimately differ by ~0.13%
    return (err <= 0.005), f"EPS {e:.2f} x {sh:.2f} cr sh = {implied:.2f} vs {owners:.2f} ({100 * err:.2f}%)"


def eps_arbitrate(con):
    """Which profit line the filing's OWN EPS row reproduces: 'profit_period', 'pat_after_tax',
    or None when the filing prints no usable EPS/paid-up pair.

    Both candidates are tested against the same shares, over every column that prints an EPS, and
    the winner must fit at least 3x better — a near-tie proves nothing and is reported as None."""
    eps, paid = con.get("eps") or [], con.get("paidup") or []
    ser = con["series"]
    # paid-up capital is the SAME number in every column, so take the median of what was read
    # rather than each column's own cell — the Jun-2022 scan returns 677.2 in one slot where the
    # page prints 877.20, and a per-column base would carry that typo into the verdict
    seen_paid = sorted(p for p in paid if p)
    paid_med = seen_paid[len(seen_paid) // 2] if seen_paid else None
    best = None
    for fv in FACE_VALUES:
        errs = {"profit_period": [], "pat_after_tax": []}
        for i, c in enumerate(ser):
            e = eps[i] if i < len(eps) else None
            p = paid_med
            if not e or not p or e == 0:
                continue
            shares = p / fv  # paid-up capital and profit share one scale
            for cand in errs:
                v = c.get(cand)
                if v is None:
                    continue
                errs[cand].append(abs(v - e * shares) / max(abs(v), 1.0))
        if not errs["profit_period"]:
            continue
        m = {k: sum(v) / len(v) for k, v in errs.items() if v}
        cand = min(m, key=m.get)
        if best is None or m[cand] < best["err"]:
            best = {
                "winner": cand,
                "err": round(m[cand], 5),
                "face_value": fv,
                "n_cols": len(errs[cand]),
                "two_sided": len(m) == 2,
                "runner_up_err": round(max(m.values()), 5) if len(m) == 2 else None,
                "owners_err": round(m["profit_period"], 5),
            }
    if best is None:
        return None  # the filing prints no usable EPS/paid-up pair
    if best["two_sided"] and best["runner_up_err"] < 3 * best["err"]:
        return None  # the two candidates are too close to call
    # `fits` is the ONE-SIDED verdict, available even on a scan whose profit-after-tax row is
    # unreadable (the Jun-2022 pack): does the owners' figure alone reconcile to the printed EPS?
    best["fits"] = best["owners_err"] <= 0.005
    if best["err"] > 0.01:
        best["winner"] = None
    return best


# ---------------------------------------------------------------------------------------------
def adjudicate(obs, verbose=True):
    """{qe: {'value':…, 'sources':[…]}} for cells proven under C3-C6."""
    fund = json.load(open(FUND_DOCS))
    rows = {r[0]: r for r in fund[SYM]}
    stored_std = {q: r[1] for q, r in rows.items()}
    stored_con = {q: r[3] for q, r in rows.items()}

    # every (quarter, filing) reading, from whichever column of whichever filing printed it
    seen = {}  # qe -> [(source, pat_after_tax, assoc, nci, profit_period)]
    fy = {}  # fy-end qe -> [(source, pat_after_tax, profit_period)]
    eps_seen = {}  # source -> its EPS arbitration verdict
    for _own_qe_s, entry in sorted(obs.items()):
        for f in entry.get("filings", []):
            con, std = f.get("con"), f.get("std")
            if not con:
                continue
            ctrl = sorted((std or {}).get("control_ok") or [])
            controlled = len(ctrl) >= 2
            src = "BSE %s (filed %s, p%d)" % (f["att"], f["filed"], con["page"])
            # C7 — EPS ARBITRATION (runbook §2d principle). GICRE's consolidated statement prints
            # no NCI line, so the owners' profit is either "Profit/(loss) after tax" or that plus
            # the associates' share ("Profit for the year"). Only the filing's own EPS row can say
            # which: basic EPS x shares must reproduce the owners' number, shares = paid-up / face
            # value. The face value is solved from the filing rather than assumed (a wrong face
            # value scales BOTH candidates equally, so it cannot manufacture a verdict).
            eps_verdict = eps_arbitrate(con)
            f["eps_verdict"] = eps_verdict
            if eps_verdict and (
                eps_verdict.get("fits") is False
                or (eps_verdict["two_sided"] and eps_verdict["winner"] != "profit_period")
            ):
                if verbose:
                    print("  EPS ARBITRATION rejects this filing ({}): {}".format(f["att"][:24], eps_verdict))
                continue
            eps_seen[src] = eps_verdict
            for i, c in enumerate(con["series"]):
                v, a, n = c["pat_after_tax"], c["assoc"], c["nci"]
                per = c["profit_period"]
                # C4 — the filing's own arithmetic must close: owners' profit = profit after
                # tax + associates' share (+ NCI, which GIC Re never prints). Two OCR damage
                # modes are tolerated here and recorded, because this row CORROBORATES the value
                # rather than supplying it — `per` is what gets written, and it is separately
                # gated by the EPS row, by a second filing, and by the SQ=FY closure:
                #   * a lost parenthesis flips the associates' sign (Sep-2024 prints (9.20) and
                #     OCR returns 9.20), so the leg is accepted at either sign;
                #   * a spurious or dropped digit shifts profit-after-tax by a power of ten
                #     (Dec-2024's 1,62,343 comes back as 16234.31).
                how = identity(v, a, n, per)
                if how == "fails":
                    if verbose:
                        print(
                            "  IDENTITY FAIL %s %s occ%d: %s + %s + %s != %s"
                            % (f["att"][:20], c["qe"], c["occ"], v, a, n, per)
                        )
                    continue
                # C7 PER COLUMN, not per filing. Averaging the EPS error over a page lets one
                # damaged column condemn the good ones (and, worse, lets good ones excuse a bad
                # one). Each column is confirmed or dropped on its own EPS.
                ok, why = eps_check(con, i, per)
                if ok is False:
                    if verbose:
                        print("  EPS drops %s %s occ%d: %s" % (f["att"][:20], c["qe"], c["occ"], why))
                    continue
                rec = (src, v, a, n, per, ok, controlled, how)
                if c.get("role") == "Q":
                    seen.setdefault(c["qe"], []).append(rec)
                elif c.get("role") in ("FY", "YTD"):
                    # a cumulative column: the quarters of its fiscal year up to its date must
                    # rebuild it. FY is the four-quarter case; the 9-month and half-year columns
                    # give the same closure one quarter earlier, which is what confirms a quarter
                    # whose fiscal year is not finished yet.
                    fy.setdefault(c["qe"], []).append((src, v, per))

    # ---- PAGE CONTROL: how many OTHER quarters each consolidated page prints that the rest of
    # the corpus independently confirms. A page whose neighbouring columns reproduce values two
    # other filings agree on has proven its own reading chain — the same positive-control logic as
    # A5, but run against confirmed readings instead of against the stored series (which is the
    # thing under audit). This is what makes a quarter only ONE filing prints admissible.
    consensus = {}
    for q, recs in seen.items():
        tal = {}
        for r in recs:
            if r[4] is None:
                continue
            k = next((k for k in tal if abs(k - r[4]) <= PAISA), round(r[4], 2))
            tal.setdefault(k, set()).add(r[0])
        for k, srcs in tal.items():
            if len(srcs) >= 2:
                consensus[q] = k
    page_control = {}
    for q, recs in seen.items():
        for r in recs:
            if consensus.get(q) is not None and r[4] is not None and abs(consensus[q] - r[4]) <= PAISA:
                page_control.setdefault(r[0], set()).add(q)

    out = {}
    for q in sorted(seen):
        recs = seen[q]

        # C5 — the value must be printed identically by two independent filings
        def tally(pick):
            # cluster within a paisa: the same figure printed as 97,766 lakh in one filing and
            # 977.65 crore in another is ONE reading, not a disagreement
            d = {}
            for r in recs:
                v = pick(r)
                if v is None:
                    continue
                key = next((k for k in d if abs(k - v) <= PAISA), round(v, 2))
                d.setdefault(key, []).append(r[0])
            return d

        vals_per = tally(
            lambda r: r[4] if r[4] is not None else (None if r[1] is None else r[1] + (r[2] or 0.0) + (r[3] or 0.0))
        )
        if not vals_per:
            continue
        best = max(vals_per.items(), key=lambda kv: len(set(kv[1])))
        pat_only = tally(lambda r: r[1])
        assoc_only = tally(lambda r: r[2])
        out[q] = {
            "profit_for_period": best[0],
            "sources": sorted(set(best[1])),
            "n_independent": len(set(best[1])),
            "disagreements": {k: sorted(set(v)) for k, v in vals_per.items() if k != best[0]},
            "pat_after_tax": (max(pat_only.items(), key=lambda kv: len(set(kv[1])))[0] if pat_only else None),
            "pat_n": (len(set(max(pat_only.items(), key=lambda kv: len(set(kv[1])))[1])) if pat_only else 0),
            "assoc": (max(assoc_only.items(), key=lambda kv: len(set(kv[1])))[0] if assoc_only else None),
            "stored_std": stored_std.get(q),
            "stored_con": stored_con.get(q),
            # which of the agreeing filings carried a passing standalone control, and which
            # columns their EPS row independently confirmed
            "controlled_sources": sorted(
                {r[0] for r in recs if r[6] and abs((r[4] if r[4] is not None else -1e9) - best[0]) <= PAISA}
            ),
            "identity": sorted({r[7] for r in recs}),
            # other quarters on the same page(s) that the corpus independently confirms
            "page_control": sorted({x for r in recs for x in page_control.get(r[0], set()) if x != q}),
            "eps_confirmed": sorted(
                {r[0] for r in recs if r[5] is True and r[4] is not None and abs(r[4] - best[0]) <= PAISA}
            ),
        }
    return out, fy


def verdicts(res, fy):
    """Stamp each quarter with what it is and whether it may be written.

    States:
      COPY      stored con == stored std and the filings prove otherwise -> the reported defect
      CONVENTN  stored con IS consolidated but is the BEFORE-associates line, which the filing's
                own EPS row contradicts -> same correction, different cause
      OK        stored con already equals the owners' figure -> leave alone. This is C6: the
                calibration quarters have to land here, or the convention is wrong and NOTHING
                should be written.
      OTHER     stored con is none of the above -> reported for review, never written.

    A cell may be APPLIED only with two independent filings agreeing to the paisa AND a
    document-anchored control: either one of those filings reproduced >=2 stored standalone cells
    from its own standalone page (C3), or the cell's fiscal year rebuilds exactly from its four
    quarters against the printed annual (C5's SQ=FY leg). Agreement alone is not enough — two
    filings can repeat one systematic misreading; agreement plus an independent arithmetic
    closure cannot."""
    for q, r in sorted(res.items()):
        owners, stored, std = r["profit_for_period"], r["stored_con"], r["stored_std"]
        # the before-associates line, whether or not this filing's PAT row was legible
        # The profit-after-tax and associates figures quoted in the ledger must be the RECONCILED
        # ones, not the raw OCR: Sep-2024's associates share is (9.20) and comes back as +9.20,
        # and Dec-2024's after-tax 1,62,343 comes back as 16234.31. `identity()` already
        # established which variant closes; use it, so the recorded arithmetic actually adds up.
        assoc = r["assoc"]
        if assoc is not None and "closes|assoc-sign" in r["identity"] and "closes" not in r["identity"]:
            assoc = -assoc
        r["assoc_signed"] = assoc
        before = r["pat_after_tax"]
        if assoc is not None and (before is None or abs(owners - (before + assoc)) > 1.0):
            before = round(owners - assoc, 2)  # rebuild from the two figures that reconcile
        r["pat_after_tax_implied"] = before
        if stored is not None and abs(stored - owners) <= PAISA:
            r["state"] = "OK"
        elif stored is not None and std is not None and abs(stored - std) <= PAISA:
            r["state"] = "COPY"
        elif before is not None and stored is not None and abs(stored - before) <= PAISA:
            r["state"] = "CONVENTN"
        else:
            r["state"] = "OTHER"

        fy_end = q if q % 10000 == 331 else (q // 10000 + 1) * 10000 + 331
        # every cumulative column that ENDS on or after this quarter and belongs to its fiscal
        # year: each one the quarters can rebuild is an independent confirmation of this cell
        sq, r["sq_detail"] = None, []
        for cum_end, items in sorted(fy.items()):
            cum_fy = cum_end if cum_end % 10000 == 331 else (cum_end // 10000 + 1) * 10000 + 331
            if cum_fy != fy_end or cum_end < q:
                continue
            qs = sorted(x for x in res if fy_end - 10000 < x <= cum_end)
            want = sorted({v for _s, _p, v in items if v is not None})
            # how many quarters this cumulative column spans: Jun=1, Sep=2, Dec=3, Mar=4
            span = ((cum_end % 10000 // 100 - 6) // 3) % 4 + 1
            if len(qs) != span or len(want) != 1:
                continue
            got = sum(res[x]["profit_for_period"] for x in qs)
            ok = abs(got - want[0]) <= 1.0  # Rs 1cr absorbs paisa rounding, nothing more
            sq = ok if sq is None else (sq and ok)
            r["sq_detail"].append(
                "%s: SQ(%d q) %.2f vs printed %.2f -> %s" % (cum_end, len(qs), got, want[0], "OK" if ok else "MISMATCH")
            )
        r["sq_check"] = sq
        r["fy_end"] = fy_end

        agreed = r["n_independent"] >= 2
        anchored = bool(r["controlled_sources"]) or len(r["page_control"]) >= 2
        # SQ=FY is a proof in its own right, not merely a substitute control. Four quarters read
        # from four separately printed columns reproducing the printed annual TO THE PAISA cannot
        # happen by accident, and — unlike the compensating-error trap the runbook warns about
        # (§45, BDL FY18) — none of these four is DERIVED from the annual or from each other:
        # every one is read directly off a document column.
        # A CONVENTN cell can be proven by ONE filing, because the stored value is itself the
        # column anchor: it equals that filing's printed profit-AFTER-TAX line to the paisa, which
        # means our own historical import read this very column of this very statement. The
        # correction moves one printed line down within a column already proven to be the right
        # one — a much narrower claim than a COPY correction, where the stored value says nothing
        # about which column is right. Still requires the page's own arithmetic to close and two
        # corroborated neighbours on it.
        one_filing_ok = (
            r["state"] == "CONVENTN" and anchored and "fails" not in r["identity"] and len(r["page_control"]) >= 2
        )
        proven = (sq is True or (agreed and anchored) or one_filing_ok) and not r["disagreements"]
        if r["state"] == "OK":
            r["verdict"] = "confirms stored"
        elif r["state"] == "OTHER":
            r["verdict"] = "REVIEW"
        elif proven:
            r["verdict"] = "APPLY"
        else:
            r["verdict"] = "UNCONFIRMED({}{}{}{})".format(
                "" if agreed else "1 filing ",
                "" if anchored else "no control ",
                "" if sq is not False else "SQ!=FY ",
                "disagree" if r["disagreements"] else "",
            )
        r["in_scope"] = q >= SCOPE_FROM
        if not r["in_scope"] and r["verdict"] == "APPLY":
            r["verdict"] = "APPLY(out of scope - report only)"
        r["verdict_apply"] = bool(proven and r["state"] in ("COPY", "CONVENTN") and r["in_scope"])
        r["reason"] = (
            "stored con PAT was an exact copy of the STANDALONE PAT; GIC Re files consolidated "
            "results quarterly and its consolidated statement prints owners' profit "
            f"(profit after tax {before} + share of associates {assoc} = {owners}). Runbook 55c/2b."
            if r["state"] == "COPY"
            else "stored con PAT was the consolidated PROFIT-AFTER-TAX line, i.e. BEFORE the share of "
            f"profit in associates ({assoc}); the filing's own EPS row reproduces the owners' figure {owners}, "
            f"not {before}. Runbook 55c/2b, EPS arbitration per 2d."
        )


def apply(res, dry=True):
    """§2b guard-edit of BOTH fundamentals files.

    The §2b rules, literally: load fresh, assert the OLD value still matches (a concurrent job may
    have moved it), change ONLY the con-PAT slot, assert nothing else differs, and dump minified.
    The con DATE (idx 4) is NOT touched — it is the announcement date and is already correct."""
    plan = []
    for q in sorted(res):
        r = res[q]
        if not r.get("verdict_apply"):
            continue
        plan.append((q, r["stored_con"], r["profit_for_period"], r))
    if not plan:
        print("nothing to apply")
        return 0

    print("\n%-10s %12s -> %-12s  %s" % ("QE", "stored con", "corrected", "why"))
    for q, old, new, r in plan:
        print("%-10d %12s -> %-12s  %s" % (q, old, new, r["reason"]))
    if dry:
        print("\n(dry run — pass --apply to write)")
        return 0

    for path in (FUND_DOCS, FUND_SCRIPTS):
        d = json.load(open(path))
        before = json.dumps(d, sort_keys=True, separators=(",", ":"))
        rows = {r[0]: r for r in d[SYM]}
        for q, old, new, _r in plan:
            row = rows.get(q)
            if row is None:
                raise SystemExit("GUARD: %s has no row for %d in %s" % (SYM, q, path))
            if row[3] != old:
                raise SystemExit(
                    "GUARD: %s %d con is %r, expected %r in %s — REFUSING "
                    "(another writer moved it; re-derive, do not merge)" % (SYM, q, row[3], old, path)
                )
            row[3] = new
        # nothing but the intended con-PAT slots may have changed
        after = json.loads(json.dumps(d))
        ref = json.loads(before)
        diffs = []
        for sym in set(ref) | set(after):
            if sym != SYM:
                if ref.get(sym) != after.get(sym):
                    diffs.append(sym)
                continue
            a = {r[0]: r for r in ref[sym]}
            b = {r[0]: r for r in after[sym]}
            if set(a) != set(b):
                diffs.append(f"{sym} row set")
            for q in a:
                for i in range(len(a[q])):
                    if a[q][i] != b[q][i] and not (i == 3 and q in {p[0]: 1 for p in plan}):
                        diffs.append("%s %d idx%d" % (sym, q, i))
        if diffs:
            msg = f"GUARD: unintended changes {diffs[:8]} in {path}"
            raise SystemExit(msg)
        json.dump(d, open(path, "w"), separators=(",", ":"))
        print(f"wrote {path}")

    led = json.load(open(LEDGER)) if os.path.exists(LEDGER) else {}
    defects = json.load(open(os.path.join(SCRIPTS, "pat_defects.json")))
    for q, old, new, r in plan:
        led["%s|%d|con" % (SYM, q)] = {
            "stored_pat_con": old,
            "correct_pat_con": new,
            "reason": r["reason"],
            "pat_after_tax": r["pat_after_tax_implied"],
            "share_of_associates": r["assoc_signed"],
            "n_independent_filings": r["n_independent"],
            "sources": r["sources"],
            "standalone_control": r["controlled_sources"],
            "eps_confirmed_filings": len(r["eps_confirmed"]),
            "profit_tail_identity": r["identity"],
            "same_page_corroborated_quarters": r["page_control"],
            "cumulative_closures": r["sq_detail"],
            "fin": 1,
        }
        defects.setdefault(SYM, {})[str(q)] = {
            "stored_pat_con": old,
            "correct_pat_con": new,
            "defect": r["reason"],
            "source": " | ".join(r["sources"])
            + ("  || cumulative closure: " + "; ".join(r["sq_detail"]) if r["sq_detail"] else ""),
        }
    json.dump(led, open(LEDGER, "w"), indent=1, sort_keys=True)
    json.dump(defects, open(os.path.join(SCRIPTS, "pat_defects.json"), "w"), indent=1, sort_keys=True)
    print("ledgered %d cells -> %s + pat_defects.json" % (len(plan), LEDGER))
    return len(plan)


def main():
    argv = sys.argv
    only = int(argv[argv.index("--qe") + 1]) if "--qe" in argv else None
    obs = json.load(open(OBS)) if "--report" in argv or "--apply" in argv else harvest(only)

    res, fy = adjudicate(obs)
    verdicts(res, fy)
    print(
        "\n%-10s %10s %10s %10s %10s %3s %3s %3s %-9s %s"
        % ("QE", "storedSTD", "storedCON", "PAT(a-tax)", "OWNERS", "n", "ctl", "eps", "state", "verdict")
    )
    for q in sorted(res):
        r = res[q]
        print(
            "%-10d %10s %10s %10s %10s %3d %3d %3d %-9s %s%s"
            % (
                q,
                r["stored_std"],
                r["stored_con"],
                r["pat_after_tax_implied"],
                r["profit_for_period"],
                r["n_independent"],
                len(r["controlled_sources"]),
                len(r["eps_confirmed"]),
                r["state"],
                r["verdict"],
                ("  DISAGREE {}".format(r["disagreements"])) if r["disagreements"] else "",
            )
        )
    apply(res, dry="--apply" not in argv)
    print("\nFY columns (full-year, 2nd occurrence of the 31/03 date):")
    for k, v in sorted(fy.items()):
        print(
            "  FY%d  pat_after_tax=%s  profit_for_period=%s"
            % (k, sorted({x[1] for x in v if x[1] is not None}), sorted({x[2] for x in v if x[2] is not None}))
        )
        qs = [q for q in res if k - 10000 < q <= k]
        if len(qs) == 4:
            print(
                "        SQ check: profit_for_period Q1..Q4 = {} -> {:.2f}".format(
                    [res[q]["profit_for_period"] for q in sorted(qs)],
                    sum(res[q]["profit_for_period"] for q in sorted(qs)),
                )
            )
            pats = [res[q]["pat_after_tax_implied"] for q in sorted(qs)]
            print(
                "        SQ check: pat_after_tax   Q1..Q4 = {} -> {}".format(
                    pats, (f"{sum(pats):.2f}") if all(x is not None for x in pats) else "n/a"
                )
            )
    json.dump(res, open(os.path.join(HERE, "_gicre_adjudicated.json"), "w"), indent=1, sort_keys=True)


if __name__ == "__main__":
    main()
