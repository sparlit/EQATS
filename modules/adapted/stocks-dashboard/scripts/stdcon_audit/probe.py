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
"""STD-SLOT-HOLDS-CON audit: the decisive per-cell test (runbook §57 ladder, rung 3 first).

For a suspect cell (sym, qe) where stored std PAT == stored con PAT:
    std_page == stored_std                                  -> OK
    std_page != stored_std AND con_page == stored_std       -> CONFIRMED DEFECT (std slot holds con)
    otherwise                                               -> INCONCLUSIVE (routes recorded)

ROUTE. 95% of the suspect population is 2019+, where the NSE archive serves no detail page and the
BSE detailed-results JSON is standalone-only -- so the workhorse is the BSE announcement PDF, which
carries BOTH bases in one document. Detres (§42) is used as an independent standalone corroborator
where it answers.

COLUMN ANCHORING IS THE WHOLE POINT (the ANGELONE/ADANIGREEN/LICI method). A number lifted from a
P&L row means nothing until you know which column it sits in. So every read is accepted only if a
COMPARATIVE column of the same row reproduces a STORED value for a neighbouring quarter -- and the
neighbours used as anchors are restricted to quarters where stored std != stored con, because on
those the stored value is demonstrably not itself a copy. That proves document + scale + column
mapping + company identity in one step.

Anti-traps carried over from the runbook:
  * §51b glyph corruption -- basis detection uses substitution-tolerant fragments, and a filing
    where NEITHER basis marker is found is reported as such, never silently treated as standalone.
  * §53b blank templates -- a PAT of exactly 0.00 is refused.
  * §52 default announce dates -- the search window is qe+8d..qe+150d, not a window around the
    stored announce date.
  * §55a empty announcement lists are often rate-limiting -- retried on a fresh session.
  * FY/YTD columns -- the period gate reads the statement title, and the YTD column is excluded by
    the anchor test rather than by position alone.
"""
import io
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, SCRIPTS)
import bse_vision as V  # noqa: E402
import fitz  # noqa: E402

sys.path.insert(0, HERE)
import detres as D  # noqa: E402
import scrips as SC  # noqa: E402

FUND = os.path.join(ROOT, "docs", "sf_fundamentals.json")
PDFDIR = os.path.join(HERE, "_pdf")
OUT = os.path.join(HERE, "_probe.json")


# --- basis markers, corruption-tolerant (runbook §51b: "Standalone" extracts as "Slondolone") ---
R_STD = re.compile(r"s[tl][ao]nd[ao]l[o0]ne", re.IGNORECASE)
R_CON = re.compile(r"c[o0]ns[o0][li1]id[ao][lt]", re.IGNORECASE)
NUM = re.compile(r"^\(?-?[\d,]+\.?\d*\)?$")
_PL = r"(net\s+)?profit\s*(/|\s)?\s*\(?\s*(loss|llossl|\(loss\))?\s*\)?\s*"
R_PAT = re.compile(_PL + r"(after tax\s*)?(for|of)\s+the\s+(period|quarter|year)", re.IGNORECASE)
R_PAT2 = re.compile(r"^\s*" + _PL + r"(after\s+tax|after\s+taxe?s?|for\s+the\s+period)", re.IGNORECASE)
R_OWN = re.compile(r"(owners?|equity ?holders?|shareholders?) of the (parent|company|holding)", re.IGNORECASE)
R_NCI = re.compile(r"non[- ]?controlling interest|minority interest", re.IGNORECASE)
R_BEFORE = re.compile(r"before\s+tax|before\s+except|comprehensive|per\s+share|eps", re.IGNORECASE)
UNITS = [
    (re.compile(r"in\s*(rs\.?|₹|inr)?\s*\.?\s*lakh", re.IGNORECASE), 100.0),
    (re.compile(r"in\s*(rs\.?|₹|inr)?\s*\.?\s*(million|mn\b|mio)", re.IGNORECASE), 10.0),
    (re.compile(r"in\s*(rs\.?|₹|inr)?\s*\.?\s*(crore|cr\.?\b)", re.IGNORECASE), 1.0),
    (re.compile(r"in\s*(rs\.?|₹|inr)?\s*\.?\s*(thousand|'000|`000)", re.IGNORECASE), 10000.0),
]
MON = {1: 31, 2: 28, 3: 31, 4: 30, 5: 31, 6: 30, 7: 31, 8: 31, 9: 30, 10: 31, 11: 30, 12: 31}


def qdiff(a, b):
    """Quarter offset of a relative to b (a = b + k quarters), or None if a is not a quarter-end."""
    for q in (a, b):
        if (q // 100) % 100 not in (3, 6, 9, 12):
            return None
    ia = (a // 10000) * 4 + {3: 0, 6: 1, 9: 2, 12: 3}[(a // 100) % 100]
    ib = (b // 10000) * 4 + {3: 0, 6: 1, 9: 2, 12: 3}[(b // 100) % 100]
    return ia - ib


def qshift(qe, k):
    y, m = qe // 10000, (qe // 100) % 100
    i = y * 4 + {3: 0, 6: 1, 9: 2, 12: 3}[m] + k
    y2, mi = divmod(i, 4)
    m2 = [3, 6, 9, 12][mi]
    return y2 * 10000 + m2 * 100 + [31, 30, 30, 31][mi]


def to_ord(qe):
    return (qe // 10000) * 12 + (qe // 100) % 100


def days_after(qe, n):
    """qe + n days as YYYYMMDD (rough calendar walk -- only used for search windows)."""
    y, m, d = qe // 10000, (qe // 100) % 100, qe % 100
    d += n
    while True:
        dim = MON[m] + (1 if m == 2 and y % 4 == 0 else 0)
        if d <= dim:
            break
        d -= dim
        m += 1
        if m > 12:
            m, y = 1, y + 1
    return y * 10000 + m * 100 + d


def tv(w):
    w = w.replace(",", "").replace("(", "-").replace(")", "").replace("−", "-")
    try:
        return float(w)
    except Exception:
        return None


def rows_of(page):
    """(label, [numbers], y) per visual row, y-clustered with tolerance."""
    words = sorted(page.get_text("words"), key=lambda w: (round(w[1], 1), w[0]))
    lines, cur, cy = [], [], None
    for w in words:
        if cy is None or abs(w[1] - cy) <= 3.0:
            cur.append(w)
            cy = w[1] if cy is None else cy
        else:
            lines.append((cy, cur))
            cur, cy = [w], w[1]
    if cur:
        lines.append((cy, cur))
    out = []
    for y, ws in lines:
        ws = sorted(ws, key=lambda w: w[0])
        alpha = [w for w in ws if not NUM.match(w[4].replace(",", ""))]
        lab = " ".join(w[4] for w in alpha)
        # Numeric tokens sitting to the LEFT of the label are ROW INDICES ("29 Profit/(loss)..."),
        # not data. Including them shifted every column by one (LICI Sep-23: [29.0, 8030.28, ...]).
        lx = min((w[0] for w in alpha), default=0.0)
        # x is the token's RIGHT edge: statement numbers are right-aligned, and so are the header
        # date cells, so right edges are what line a value up with its column. (Using left edges
        # here while the header used right edges put every column ~32pt out and matched nothing.)
        nums = [(w[2], tv(w[4])) for w in ws if NUM.match(w[4].replace(",", "")) and w[0] >= lx - 2.0]
        nums = [(x, v) for x, v in nums if v is not None]
        out.append((lab.strip(), nums, y))
    return out


def unit_div(text):
    for rx, d in UNITS:
        if rx.search(text):
            return d, rx.pattern
    return None, None


MONNAME = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}
R_DATE1 = re.compile(r"([A-Za-z]{3,9})\.?\s+(\d{1,2})\s*,?\s*(\d{4})")
R_DATE2 = re.compile(r"(\d{1,2})[.\-/\s]([A-Za-z]{3,9}|\d{1,2})[.\-/\s](\d{4})")


def _mk(y, m, d):
    return None if not (1 <= m <= 12) else y * 10000 + m * 100 + d


def raw_rows(page):
    """(text, [(x, token)], y) per visual row -- numbers INCLUDED in the text, which is what date
    parsing needs (PyMuPDF hands back "June", "30,", "2020" as three tokens and the label-only
    view of rows_of() drops the numeric ones)."""
    words = sorted(page.get_text("words"), key=lambda w: (round(w[1], 1), w[0]))
    lines, cur, cy = [], [], None
    for w in words:
        if cy is None or abs(w[1] - cy) <= 3.0:
            cur.append(w)
            cy = w[1] if cy is None else cy
        else:
            lines.append((cy, cur))
            cur, cy = [w], w[1]
    if cur:
        lines.append((cy, cur))
    out = []
    for y, ws in lines:
        ws = sorted(ws, key=lambda w: w[0])
        out.append((" ".join(w[4] for w in ws), [(w[2], w[4]) for w in ws], y))
    return out


def _dates_in(toks):
    """[(x_right, qe)] for every date spelled across 1-3 consecutive tokens on one row.

    Token-based rather than character-offset based, so the x returned is the exact right edge of
    the date's last token -- which is what lines a header cell up with the numbers under it.
    """
    out = []
    for i in range(len(toks)):
        for n in (1, 2, 3):
            if i + n > len(toks):
                break
            frag = " ".join(t for _, t in toks[i : i + n])
            for rx, order in ((R_DATE1, "mdy"), (R_DATE2, "dmy")):
                m = rx.fullmatch(frag.strip())
                if not m:
                    continue
                g = m.groups()
                try:
                    if order == "mdy":
                        mo = MONNAME.get(g[0][:3].lower())
                        v = _mk(int(g[2]), mo or 0, int(g[1]))
                    else:
                        mo = MONNAME.get(g[1][:3].lower()) if not g[1].isdigit() else int(g[1])
                        v = _mk(int(g[2]), mo or 0, int(g[0]))
                except Exception:
                    v = None
                if v and 2000 < v // 10000 < 2100:
                    out.append((toks[i + n - 1][0], v))
    ded = []
    for x, v in sorted(out):
        if ded and abs(x - ded[-1][0]) < 3 and v == ded[-1][1]:
            continue
        ded.append((x, v))
    return ded


R_TITLEISH = re.compile(r"result|quarter ended on|statement of|for the (quarter|period|year)", re.IGNORECASE)


def header_cols(doc, secs, p, maxrows=22):
    """The statement's COLUMN-HEADER row, as [(x_right, quarter_end)].

    THIS IS THE COLUMN MAP, and it is read rather than assumed. Taking column 0 to be the target
    quarter is wrong often enough to matter: HDFCLIFE Mar-2020 was first read out of the JULY
    filing, whose columns are [Jun-2020, Mar-2020, Jun-2019, FY20] -- col0 there is a different
    quarter, and the anchor hits were consistent with that shifted layout, so nothing caught it.

    Only ONE row is used: the row carrying the most dates, preferring the lowest such row (the one
    just above the data). Accumulating dates across rows pulled the TITLE's date in as a phantom
    fifth column and mis-picked SHRI JAGDAMBA's Jun-2020 value.
    """
    basis = {q: b for b, q in secs}.get(p)
    for q in (p, p - 1):
        if q < 0 or {y: x for x, y in secs}.get(q) != basis:
            continue
        best = []
        for text, toks, _y in raw_rows(doc[q])[:maxrows]:
            if R_TITLEISH.search(text):
                continue
            ds = _dates_in(toks)
            if len(ds) >= len(best) and len(ds) >= 2:
                best = ds
        if best:
            return best, q
    return [], None


def col_value(nums, cols, qe, tol=20.0):
    """Value in the column whose header date is qe. nums = [(x_right, value)] from the data row.

    Ordinal mapping when the counts agree (the strongest signal -- a statement prints one number
    per header column); otherwise nearest-x, since headers may be centred over right-aligned
    figures and a couple of points of drift is normal.
    """
    idxs = [i for i, (x, d) in enumerate(cols) if d == qe]
    if not idxs:
        return None, "target quarter %d not among header dates %s" % (qe, [d for _, d in cols])
    if len(cols) == len(nums):
        return nums[idxs[0]][1], "ordinal col %d of %d (header %d)" % (idxs[0] + 1, len(cols), qe)
    for i in idxs:  # leftmost first: a FY column repeats the date
        wx = cols[i][0]
        best = min(nums, key=lambda t: abs(t[0] - wx)) if nums else None
        if best and abs(best[0] - wx) <= tol:
            return best[1], "nearest-x %.0f vs header %.0f (header %d)" % (best[0], wx, qe)
    return None, "no value under the %d column (header x %s vs numbers %s)" % (
        qe,
        [round(cols[i][0]) for i in idxs],
        [round(x) for x, _ in nums],
    )


def unit_for(doc, secs, p):
    """Unit divisor for the statement page p. A multi-page statement declares "(Rs. in Lakhs)" once,
    on its FIRST page -- the P&L rows usually sit on the continuation page, which declares nothing.
    So walk BACK through the same basis-section, then fall back to the document majority. Reading
    the cover letter's first pages instead (the old fallback) found no unit at all for LICI and
    silently dropped both statements."""
    basis = {q: b for b, q in secs}.get(p)
    for q in range(p, -1, -1):
        if {y: x for x, y in secs}.get(q) != basis:
            break
        d, pat = unit_div(doc[q].get_text()[:3000])
        if d:
            return d, "p%d:%s" % (q, pat)
    votes = {}
    for q in range(min(len(doc), 40)):
        d, pat = unit_div(doc[q].get_text()[:3000])
        if d:
            votes[d] = votes.get(d, 0) + 1
    if votes:
        d = max(votes, key=votes.get)
        return d, "doc-majority(%d pages)" % votes[d]
    return None, None


def sections(doc, maxp=40):
    """[(basis, page_index)] -- basis inherited from the last marker seen, like a real filing.

    Small filers routinely print no basis word at all: SHRI JAGDAMBA's Jun-2020 statement is headed
    only "UN-AUIDITED FINANCIAL RESULTS FOR THE QUARTER ENDED ON 30.06.2020". Leaving those pages
    unlabelled dropped the whole document. When the WHOLE document never says "consolidated"
    (checked with the §51b corruption-tolerant fragment), the statement in it is the standalone one
    -- that is §51a's reasoning, applied per document rather than per page.
    """
    out, basis = [], None
    whole = " ".join(doc[q].get_text() for q in range(min(len(doc), maxp)))
    doc_default = "std" if not R_CON.search(whole) else None
    for p in range(min(len(doc), maxp)):
        t = doc[p].get_text()
        head = t[:1400]
        has_c, has_s = bool(R_CON.search(head)), bool(R_STD.search(head))
        if has_c and not has_s:
            basis = "con"
        elif has_s and not has_c:
            basis = "std"
        elif has_c and has_s:
            # both words on the page: a combined cover sheet, or a "Standalone and Consolidated"
            # title. Decide by which appears first in the statement title line.
            mc, ms = R_CON.search(head), R_STD.search(head)
            basis = "std" if ms.start() < mc.start() else "con"
        out.append((basis or doc_default, p))
    return out


R_REV = re.compile(
    r"^\s*(total\s+)?(revenue|income)\s+from\s+operations|^\s*revenue\s+from\s+oper|"
    r"^\s*(i+\s*[.)]?\s*)?total\s+income\b",
    re.IGNORECASE,
)


def rev_rows(page):
    out = []
    for lab, nums, _y in rows_of(page):
        if nums and R_REV.search(lab) and not R_BEFORE.search(lab.lower()):
            out.append(("rev", lab, nums))
    return out


def pat_rows(page, basis):
    """Candidate PAT rows on this page: [(kind, label, [values])]. Values are raw page numbers."""
    rs = rows_of(page)
    cands = []
    for _i, (lab, nums, _y) in enumerate(rs):
        l = lab.lower()
        if not nums:
            continue
        if R_BEFORE.search(l):
            continue
        if R_PAT.search(l) or R_PAT2.search(l):
            kind = "period"
            if re.search(r"continuing", l) and not re.search(r"discontinu", l):
                kind = "period-continuing"
            cands.append((kind, lab, nums))
    if basis == "con":
        # owners-attributable row: the FIRST "owners of the parent" line that is not inside the
        # Total-Comprehensive-Income block (runbook §53c / project-stocks-profit-basis).
        seen_tci = False
        for lab, nums, _y in rs:
            l = lab.lower()
            if re.search(r"total comprehensive income", l):
                seen_tci = True
            if R_OWN.search(l) and nums and not seen_tci:
                cands.insert(0, ("owners", lab, nums))
                break
    return cands


def anchors(rows_stored, qe, basis):
    """{offset: (stored value, divergent?)} for neighbour quarters.

    A DIVERGENT neighbour (stored std != stored con) is the strong anchor: there the stored value
    is demonstrably not itself a std/con copy, so matching it proves column mapping AND basis.
    A NON-divergent neighbour still proves document + scale + column mapping (that is exactly the
    Mar-2023 anchor that made the LICI read certain), it just cannot speak to basis -- so it is
    kept, flagged, and reported. Companies whose whole early series is equal have nothing else.
    """
    idx = {r[0]: r for r in rows_stored}
    out = {}
    for k in (-1, -4, -2, -3, -5, -8):
        q = qshift(qe, k)
        r = idx.get(q)
        if not r or len(r) < 4:
            continue
        v = r[1] if basis == "std" else (r[3] if len(r) > 3 else None)
        if v is None:
            continue
        div = r[1] is not None and len(r) > 3 and r[3] is not None and abs(r[3] - r[1]) > max(0.05, 0.001 * abs(r[1]))
        out[k] = (v, div)
    return out


REVOP = json.load(open(os.path.join(ROOT, "docs", "sf_revop.json")))


def rev_anchors(sym, qe, slot):
    """Same idea as anchors(), on the REVENUE row -- a second, independent row for the column map."""
    rv = REVOP.get(sym) or {}
    out = {}
    for k in (-1, -4, -2, -3, -5, -8):
        r = rv.get(str(qshift(qe, k)))
        if not r or r[slot] is None:
            continue
        div = r[0] is not None and r[1] is not None and abs(r[1] - r[0]) > max(0.05, 0.001 * abs(r[0]))
        out[k] = (r[slot], div)
    return out


def close(a, b):
    """Verdict tolerance -- generous enough for rounding/units across sources."""
    return abs(a - b) <= max(0.05, 0.005 * abs(b))


def exact(a, b):
    """ANCHOR tolerance. An anchor's job is to prove column mapping + scale + document identity,
    and a stored value came from this same filing family, so it should reproduce to the paisa.
    0.5% slack on a 13,427.81 anchor would be +/-67cr -- wide enough for a coincidence; this is
    not. A single EXACT hit on a material number is therefore decisive on its own, which is what
    made the LICI standalone read certain (col1 == stored Mar-2023 13427.81)."""
    return abs(a - b) <= max(0.03, 0.0005 * abs(b))


def column_evidence(rowsets, div, ancs, tcol=0):
    """Which comparative column reproduces which stored neighbour, counted ACROSS ROWS.

    rowsets: {"pat": [values], "rev": [values]}   ancs: {"pat": {off: (v, divergent)}, "rev": ...}
    A single row matching a single stored number is not evidence -- LICI's consolidated IRDAI page
    has segment columns whose 4th number happened to sit within tolerance of the year-ago con PAT.
    Two DIFFERENT rows (revenue and profit) agreeing on the same column->offset assignment cannot
    plausibly coincide, and neither can a match against a DIVERGENT neighbour of material size.
    Returns {(col, off): [notes]}.
    """
    hits = {}
    for kind, vals in rowsets.items():
        anc = ancs.get(kind) or {}
        if not vals:
            continue
        scaled = [v / div for v in vals]
        for col in range(min(len(scaled), 6)):
            if col == tcol:
                continue
            for off, (av, dv) in anc.items():
                if exact(scaled[col], av):
                    hits.setdefault((col, off), []).append(
                        "%s col%d==stored[%+d]=%.2f%s%s"
                        % (kind, col, off, av, " DIVERGENT" if dv else "", " MATERIAL" if abs(av) >= 5 else "")
                    )
    return hits


def try_read(vals, div, anc, stored_self=None):
    """Map columns. Returns (value_for_target, [anchor notes]) or (None, reason).

    Column 0 is the target quarter in every SEBI-format statement; the anchors PROVE it by
    reproducing stored neighbours at the expected offsets. Offsets tested: -1 (preceding quarter,
    col 1) and -4 (year-ago quarter, col 2, or col 1 in a 2-column comparative layout).
    """
    if not vals:
        return None, "no-values"
    scaled = [v / div for v in vals]
    notes, hits, strong = [], 0, 0
    for col in (1, 2, 3, 4):
        if col >= len(scaled):
            continue
        for off in (-1, -2, -3, -4, -5, -8):
            if off in anc and close(scaled[col], anc[off][0]):
                notes.append(
                    "col%d==stored[%+d]=%.2f%s" % (col, off, anc[off][0], " (divergent)" if anc[off][1] else "")
                )
                hits += 1
                strong += 1 if anc[off][1] else 0
                break
    if not hits:
        return (
            None,
            f"no-anchor-column-matched (scaled={[round(x, 2) for x in scaled[:6]]} anchors={ ({k: round(v[0], 2) for k, v in sorted(anc.items())}) })",
        )
    if abs(scaled[0]) < 1e-9:
        return None, "blank-template(zero)"  # runbook §53b
    return round(scaled[0], 2), {"anchors": notes, "strong": strong, "scaled": [round(x, 2) for x in scaled[:6]]}


R_EXCL = re.compile(
    r"xbrl|investor\s*present|press\s*release|media\s*release|earnings\s*call|"
    r"transcript|newspaper|analyst|intimation of|prior intimation",
    re.IGNORECASE,
)
R_INCL = re.compile(
    r"financial\s*result|board\s*meeting\s*outcome|outcome of (the )?board|"
    r"un-?audited|audited.*result",
    re.IGNORECASE,
)


def is_candidate(r):
    """A result FILING, judged on headline+subcat+attachment (memory: project-stocks-bse-announcement-pick).

    V.is_result() alone is too narrow: LICI's Jun-2023 results -- the proven defect case -- were
    filed as "Board Meeting Outcome for Outcome Of The Board Meeting Held On 10Th August 2023",
    with no "financial result" text anywhere. Missing that class is why a naive headline matcher
    reports "no filing" for quarters that were plainly filed. Content gates downstream (period
    statement + anchor columns) do the real filtering, so a loose include-list here is safe.
    """
    if not r.get("ATTACHMENTNAME"):
        return False
    sub, ns = (r.get("SUBCATNAME") or ""), (r.get("NEWSSUB") or "")
    if R_EXCL.search(ns) or R_EXCL.search(sub):
        return False
    return bool(V.is_result(r) or R_INCL.search(ns) or R_INCL.search(sub) or "result" in sub.lower())


def find_filing(o, code, qe, cache):
    """Result filings for the quarter, newest-first, searched over qe+8d..qe+150d (§52: stored
    announce dates for old quarters are 45-day defaults, so never window on them)."""
    lo, hi = days_after(qe, 8), days_after(qe, 200)
    key = "%s|%d" % (code, qe)
    if key in cache:
        return cache[key]
    out = []
    for attempt in (1, 2, 3):
        for pg in (1, 2, 3):
            u = (
                "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w?pageno=%d"
                "&strCat=-1&strPrevDate=%d&strScrip=%s&strSearch=P&strToDate=%d&strType=C" % (pg, lo, code, hi)
            )
            try:
                rows = json.loads(V.get(o, u)).get("Table", [])
            except Exception:
                rows = []
            for r in rows:
                if is_candidate(r):
                    a = re.sub(r"[^0-9]", "", (r.get("NEWS_DT") or ""))[:8]
                    out.append((int(a or 0), r["ATTACHMENTNAME"], (r.get("NEWSSUB") or "")[:120]))
            if len(rows) < 50:
                break
        if out:
            break
        # §55a: an empty announcement list is usually RATE-LIMITING, not absence. Back off on a
        # fresh session and retry -- and never cache an empty answer, or one throttled moment
        # becomes a permanent "no filing" for that cell.
        time.sleep(3.0 * attempt)
        o = V.session()
    # EARLIEST first: the first result filing after the quarter is that quarter's own statement;
    # later ones carry it only as a comparative column.
    out = sorted(set(out))
    if out:
        cache[key] = out
    return out


def get_pdf(o, att):
    os.makedirs(PDFDIR, exist_ok=True)
    p = os.path.join(PDFDIR, re.sub(r"[^A-Za-z0-9._-]", "_", att))
    if os.path.exists(p) and os.path.getsize(p) > 1000:
        return open(p, "rb").read()
    for base in ("AttachHis", "AttachLive"):
        try:
            d = V.get(o, f"https://www.bseindia.com/xml-data/corpfiling/{base}/{att}", b=True)
            if d[:4] == b"%PDF":
                open(p, "wb").write(d)
                return d
        except Exception:
            pass
    return None


def period_ok(doc, qe):
    """The document must state this quarter. Accepts 'quarter ended 30 June 2023' in any of the
    usual spellings; returns (ok, snippet)."""
    y, m, _d = qe // 10000, (qe // 100) % 100, qe % 100
    names = {3: "march", 6: "june", 9: "september", 12: "december"}
    txt = " ".join(doc[p].get_text() for p in range(min(len(doc), 6))).lower()
    txt = re.sub(r"\s+", " ", txt)
    pat = re.compile(
        r"(quarter|period|three months)[^.]{0,60}?(ended|ending)[^.]{0,30}?%s[^.]{0,12}?%d" % (names[m], y)
    )
    mm = pat.search(txt)
    return (bool(mm), mm.group(0)[:90] if mm else "")


def calibrate(sym, qe, code, rows, dr):
    """Is the detres endpoint serving STANDALONE for this scrip? (see detres.py docstring)"""
    notes, verdict = [], "ambiguous"
    rv = (REVOP.get(sym) or {}).get(str(qe))
    if rv and rv[0] is not None and dr.get("rev") is not None:
        hit_s, hit_c = close(dr["rev"], rv[0]), (rv[1] is not None and close(dr["rev"], rv[1]))
        if hit_s and not hit_c:
            notes.append(
                "CAL-REV pass: detres rev {:.2f} == stored revStd {:.2f} (revCon {})".format(dr["rev"], rv[0], rv[1])
            )
            verdict = "standalone"
        elif hit_c and not hit_s:
            notes.append("CAL-REV FAIL: detres rev {:.2f} == stored revCON {:.2f}".format(dr["rev"], rv[1]))
            verdict = "consolidated"
        elif hit_s and hit_c:
            notes.append("CAL-REV tie: stored revStd == revCon here, uninformative")
    # PAT calibration over SEVERAL divergent neighbours, decided by majority. One neighbour is
    # not enough: SHRJAGP's stored Mar-2020 std is itself corrupt (it holds the Jun-2019 value), so
    # a single-quarter test read "detres is serving consolidated" for a company that has only ever
    # filed one basis. A corrupt neighbour can outvote nothing; it cannot outvote two good ones.
    if verdict != "standalone":
        idx = {r[0]: r for r in rows}
        votes = {"standalone": 0, "consolidated": 0}
        tried = 0
        for k in (-1, 1, -2, 2, -3, 3, -4, 4, -5, 5, -6, 6, -8, 8):
            if tried >= 3:
                break
            r = idx.get(qshift(qe, k))
            if not r or len(r) < 4 or r[1] is None or r[3] is None:
                continue
            if abs(r[3] - r[1]) <= max(0.05, 0.001 * abs(r[1])):
                continue
            c = D.read(code, qshift(qe, k))
            if not c or not c["span_ok"]:
                continue
            tried += 1
            if close(c["pat"], r[1]) and not close(c["pat"], r[3]):
                votes["standalone"] += 1
                notes.append(
                    "CAL-PAT std @%d: detres %.2f == stored std %.2f (con %.2f)" % (qshift(qe, k), c["pat"], r[1], r[3])
                )
            elif close(c["pat"], r[3]) and not close(c["pat"], r[1]):
                votes["consolidated"] += 1
                notes.append(
                    "CAL-PAT CON @%d: detres %.2f == stored CON %.2f (std %.2f)" % (qshift(qe, k), c["pat"], r[3], r[1])
                )
            else:
                notes.append(
                    "CAL-PAT none @%d: detres %.2f vs std %.2f / con %.2f" % (qshift(qe, k), c["pat"], r[1], r[3])
                )
        if votes["standalone"] > votes["consolidated"]:
            verdict = "standalone"
        elif votes["consolidated"] > votes["standalone"]:
            verdict = "consolidated"
        notes.append(
            "CAL-PAT votes std=%d con=%d over %d divergent neighbours"
            % (votes["standalone"], votes["consolidated"], tried)
        )
    return {"verdict": verdict, "notes": notes}


def probe(sym, qe, fund, o, lcache, want_pages=False):
    rows = fund.get(sym) or []
    row = {r[0]: r for r in rows}.get(qe)
    if not row:
        return {"verdict": "NO-STORED-ROW"}
    stored_std, stored_con = row[1], row[3]
    code, csrc = SC.code_for(sym)
    res = {"stored_std": stored_std, "stored_con": stored_con, "routes": [], "scrip": code, "scrip_src": csrc}
    if not code:
        res["routes"].append("bse-scrip:unresolved (live master + delisted/suspended master)")
        res["verdict"] = "INCONCLUSIVE"
        return res
    # ---- ROUTE D: BSE detailed-results JSON (§42), calibrated for basis on this scrip ----------
    dr = D.read(code, qe)
    std_d = None
    if dr and dr["span_ok"]:
        cal = calibrate(sym, qe, code, rows, dr)
        res["detres"] = {"pat": dr["pat"], "rev": dr["rev"], "type": dr["type"], "calib": cal}
        res["routes"].append("detres(§42): pat={:.2f} calib={}".format(dr["pat"], cal["verdict"]))
        if cal["verdict"] == "standalone":
            std_d = dr["pat"]
    elif dr:
        res["routes"].append(
            "detres(§42): span={} end={} -> not a 3-month row for this quarter".format(dr.get("span"), dr.get("end"))
        )
    else:
        res["routes"].append("detres(§42): no row")
    if std_d is not None and close(std_d, stored_std):
        res["verdict"] = "OK"
        res["std_page"] = std_d
        res["source"] = "detres"
        return res

    fl = find_filing(o, code, qe, lcache)
    res["routes"].append("bse-ann(qe+8..150d):%d filings" % len(fl))
    if not fl:
        res["verdict"] = "INCONCLUSIVE"
        return res
    anc_p = {"std": anchors(rows, qe, "std"), "con": anchors(rows, qe, "con")}
    anc_r = {"std": rev_anchors(sym, qe, 0), "con": rev_anchors(sym, qe, 1)}
    res["anchors_pat"] = {b: {str(k): v for k, v in sorted(d.items())} for b, d in anc_p.items()}
    res["anchors_rev"] = {b: {str(k): v for k, v in sorted(d.items())} for b, d in anc_r.items()}
    best = None
    for ann, att, subj in fl[:6]:
        pdf = get_pdf(o, att)
        if not pdf:
            res["routes"].append(f"pdf-fetch-failed:{att[:40]}")
            continue
        try:
            doc = fitz.open(stream=pdf, filetype="pdf")
        except Exception as ex:
            res["routes"].append(f"pdf-open-failed:{type(ex).__name__}")
            continue
        # A results filing is routinely a text cover letter + SCANNED statement pages (IDEA
        # Mar-2024: page 0 has 1,795 chars, pages 1-22 have zero). Counting the first pages
        # therefore passes documents whose P&L is an image. Require text on the BODY.
        textpages = sum(1 for p in range(len(doc)) if len(doc[p].get_text().strip()) > 400)
        if textpages < 2:
            res["routes"].append(
                "scanned-no-text-layer:%s(ann=%d,%d/%d text pages)" % (att[:32], ann, textpages, len(doc))
            )
            continue
        pok, psnip = period_ok(doc, qe)
        secs = sections(doc)
        found = {}
        for basis, p in secs:
            if basis not in ("std", "con"):
                continue
            page = doc[p]
            div, upat = unit_for(doc, secs, p)
            if div is None:
                continue
            pc = pat_rows(page, basis)
            if not pc:
                continue
            order = {"owners": 0, "period": 1, "period-continuing": 2}
            kind, lab, nums = min(pc, key=lambda t: order.get(t[0], 3))
            cols, hpage = header_cols(doc, secs, p)
            rv = rev_rows(page)
            raw, why = col_value(nums, cols, qe) if cols else (None, "no header dates found")
            val = None if raw is None else round(raw / div, 2)
            # ANCHORS: every OTHER header column must reproduce the stored value for the quarter it
            # names. That validates the column map, the scale, the row choice and the document
            # identity in one pass -- and it is checked on the profit row AND the revenue row, so a
            # single coincidental hit cannot carry a read (LICI's consolidated page has a segment
            # column that lands within tolerance of a year-ago PAT by chance).
            ev, strong = [], 0
            for rowname, rnums, anc in (("pat", nums, anc_p[basis]), ("rev", rv[0][2] if rv else [], anc_r[basis])):
                for cx, cd in cols:
                    if cd == qe or not rnums:
                        continue
                    k = qdiff(cd, qe)
                    if k is None or k not in anc:
                        continue
                    got, _ = col_value(rnums, [(cx, cd)], cd)
                    if got is None:
                        continue
                    av, dv = anc[k]
                    if exact(got / div, av):
                        ev.append(
                            "%s col(%d)==stored[%+d]=%.2f%s%s"
                            % (rowname, cd, k, av, " DIVERGENT" if dv else "", " MATERIAL" if abs(av) >= 5 else "")
                        )
                        strong += 1 if (dv or abs(av) >= 5) else 0
            # TIER A -- the column map is confirmed by other columns reproducing stored values.
            # TIER B -- no anchor could be checked or the stored neighbours themselves disagree,
            # but the header row names the target quarter and there is exactly one number per
            # header column, so the mapping is unambiguous on the document's own terms. Tier B is
            # accepted and FLAGGED for a human read: SHRJAGP Jun-2020 lands here because its own
            # stored Mar-2020 and Jun-2019 are transposed, so every anchor contradicts a perfectly
            # readable statement. Refusing tier B outright reports "unreachable" for cells the
            # document states plainly -- exactly what §57 forbids.
            ordinal = "ordinal col" in (why or "")
            tier = (
                "A"
                if (val is not None and abs(val) > 1e-9 and (strong or len(ev) >= 2))
                else "B"
                if (val is not None and abs(val) > 1e-9 and ordinal)
                else None
            )
            accepted = tier is not None
            rec = {
                "page": p,
                "kind": kind,
                "label": lab[:80],
                "unit_div": div,
                "unit_src": upat,
                "header": [(round(x), d) for x, d in cols],
                "header_page": hpage,
                "raw_row": [(round(x), v) for x, v in nums][:8],
                "why": why,
                "evidence": ev,
                "accepted": accepted,
                "tier": tier,
                "value": val if accepted else None,
                "value_unaccepted": val,
            }
            cur = found.get(basis)
            rank = (tier == "A", accepted, len(ev), order.get(kind, 3) == 0, -p)
            if cur is None or rank > cur["_rank"]:
                rec["_rank"] = rank
                found[basis] = rec
        res["routes"].append("pdf:%s ann=%d period_ok=%s pages=%d %s" % (att[:36], ann, pok, len(doc), psnip))
        if found:
            cand = {
                "ann": ann,
                "att": att,
                "subj": subj,
                "period_ok": pok,
                "std": found.get("std"),
                "con": found.get("con"),
            }
            score = sum(1 for b in ("std", "con") if found.get(b) and found[b].get("value") is not None)
            if best is None or score > best[0]:
                best = (score, cand)
        if best and best[0] == 2:
            break
        time.sleep(0.6)
    if not best:
        if std_d is not None:
            res["std_page"] = std_d
            res["verdict"] = "OK" if close(std_d, stored_std) else "STD-MISMATCH-CON-UNREAD"
            res["source"] = "detres"
        else:
            res["verdict"] = "INCONCLUSIVE"
        return res
    cand = best[1]
    for b in ("std", "con"):
        if cand.get(b):
            cand[b].pop("_rank", None)
    res["read"] = cand
    res["std_page_detres"] = std_d
    sp = (cand["std"] or {}).get("value")
    cp = (cand["con"] or {}).get("value")
    if sp is None and std_d is not None:
        sp = std_d
        res["source"] = "detres+pdf-con"
    if sp is not None and close(sp, stored_std):
        res["verdict"] = "OK"
    elif sp is not None and cp is not None and not close(sp, stored_std) and close(cp, stored_std):
        res["verdict"] = "DEFECT"
    elif sp is not None and not close(sp, stored_std):
        res["verdict"] = "STD-MISMATCH-CON-UNREAD"
    else:
        res["verdict"] = "INCONCLUSIVE"
    return res


def main():
    args = sys.argv[1:]
    fund = json.load(open(FUND))
    if "--cells" in args:
        cells = [(c.split(":")[0], int(c.split(":")[1])) for c in args[args.index("--cells") + 1].split(",")]
    else:
        cells = [(c["sym"], c["qe"]) for c in json.load(open(os.path.join(HERE, "_sample.json")))]
    out = json.load(open(OUT)) if os.path.exists(OUT) else {}
    if "--redo" in args:
        for s, q in cells:
            out.pop("%s|%d" % (s, q), None)
    o = V.session()
    lcache = {}
    for _i, (sym, qe) in enumerate(cells):
        k = "%s|%d" % (sym, qe)
        if k in out:
            continue
        try:
            r = probe(sym, qe, fund, o, lcache)
        except Exception as ex:
            r = {"verdict": "ERROR", "err": f"{type(ex).__name__}: {ex}"}
        out[k] = r
        rd = r.get("read") or {}
        print(
            "%-12s %d  %-24s std_page=%-9s con_page=%-9s stored=%s"
            % (
                sym,
                qe,
                r["verdict"],
                (rd.get("std") or {}).get("value"),
                (rd.get("con") or {}).get("value"),
                r.get("stored_std"),
            ),
            flush=True,
        )
        json.dump(out, open(OUT, "w"), indent=1, sort_keys=True)
        time.sleep(0.4)
    json.dump(out, open(OUT, "w"), indent=1, sort_keys=True)
    import collections

    print(
        "\n" + " | ".join("%s=%d" % kv for kv in collections.Counter(v["verdict"] for v in out.values()).most_common())
    )


if __name__ == "__main__":
    main()
