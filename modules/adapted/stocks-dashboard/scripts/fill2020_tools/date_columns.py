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
"""Address a statement's columns by their PRINTED PERIOD DATE, with no stored value to anchor on.

Why this is needed. Every reader in this campaign identifies the target column by matching a value
we ALREADY store (§58 column anchor). That works beautifully for revenue, because consolidated PAT
is usually present to anchor on -- and it fails completely for the 2,744 pre-2020 consolidated
revenue cells whose con PAT is ALSO missing. No stored value, no anchor, no read: measured, every
one of 203 successful pre-2020 reads came from the anchored pool and ZERO from the unanchored one.

The way out is the thing §55b was always pointing at: the statement prints its own period dates in
the header. Parse those and the column is identified by what the document SAYS it is, not by what we
happen to already know.

    header:  "Quarter ended 31.12.2018 | 30.09.2018 | 31.12.2017 | Nine months ended 31.12.2018"
    -> {20181231: x=412, 20180930: x=478, 20171231: x=544, ...}

CUMULATIVE COLUMNS ARE THE TRAP. A quarterly statement prints year-to-date columns beside the
quarterly ones, often ending on the SAME date -- "Quarter ended 31.12.2018" and "Nine months ended
31.12.2018" both key to 20181231. Taking the wrong one lands a 9-month figure as a quarter, which is
exactly the cumulative defect this campaign spent the night healing (58 cells). So a date is only
usable when the span word above it says quarter/three-months, and any column whose span reads
nine/six/half/year-to-date/twelve is EXCLUDED, not silently preferred against.

Self-validating: the caller checks the mapping on the STANDALONE statement first (where a stored
value does exist), and only trusts the consolidated page if the same parsing reproduced standalone.

STATUS 2026-08-07 (third pass): NOT FIT TO WRITE DATA. Do not wire it to a writer.

Detection improved a lot; ACCURACY did not follow, and accuracy is the only thing that matters.
    header parsed on 67% of real statement pages (was ~4%), 2.4 quarter-columns/page (was 1.5);
    but bound per-document -- each cached PDF matched to its OWN issuer via docs/search_index.json,
    then the date-mapped column checked against that company's stored PAT for that quarter and
    basis -- it reproduced the stored figure on only 45 of 128 tests: 35%.

The earlier "70%" was measured by matching each read against EVERY company's stored figures, so
coincidental matches inflated it. Binding the document to its issuer halved it. Trust the bound
number; the unbound one is not a measurement of anything useful.

35% means the column is wrong about two times in three. A writer on those terms would inject errors
faster than the screener audit removes them -- this campaign healed 195 wrong cells on 2026-08-07,
many of them from exactly this failure mode (a plausible value read from the wrong column).

WHERE IT ACTUALLY FAILS, from the miss list: consolidated pages (BIOCON 2018-2019, FLEXITUFF). The
header parse finds dates, but on a con page the PAT row picked is often the wrong one -- these
statements carry several profit lines (before tax, after tax, total comprehensive, owners vs NCI)
and the date column alone does not disambiguate the ROW. Fixing the column was necessary and not
sufficient: row selection needs the same rigour, and the owners-attributable line must be pinned
before this can be trusted.

Next attempt should start from: (1) this 35% bound baseline, (2) row disambiguation on con pages,
(3) the per-document self-check as the gate -- require the SAME parse to reproduce the standalone
figure on the same document before accepting anything it says about the consolidated page.
"""
import re

# 31.12.2018 | 31/12/2018 | 31-12-2018 | 31.12.18
NUMERIC = re.compile(r"^(\d{1,2})[./-](\d{1,2})[./-](\d{2,4})$")
# 31st December, 2018 / December 31, 2018 / 31 Dec 2018
MONTHS = {
    m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)
}
DAYMON = re.compile(r"^(\d{1,2})(?:st|nd|rd|th)?$", re.IGNORECASE)
YEAR = re.compile(r"^(20\d{2})$")

# span words that mean this column is NOT a single quarter
CUMULATIVE = re.compile(
    r"nine|six|half|year\s*to\s*date|y\.?t\.?d|twelve|\byear\s+ended|"
    r"period\s+ended.*month",
    re.IGNORECASE,
)
QUARTERLY = re.compile(r"quarter|three\s*month|3\s*month", re.IGNORECASE)
LAST_DAY = {3: 31, 6: 30, 9: 30, 12: 31}


def _norm(d, m, y):
    y = int(y)
    if y < 100:
        y += 2000
    d, m = int(d), int(m)
    if not (1 <= m <= 12) or not (1 <= d <= 31):
        return None
    # snap to the quarter end it belongs to; statements print the true period end
    if m in LAST_DAY and d >= 28:
        return y * 10000 + m * 100 + LAST_DAY[m]
    return None


def dates_on(page, ytol=3.0):
    """-> [(qe, x_right, y, span_text)] for every period date printed on the page."""
    words = page.get_text("words")
    if not words:
        return []
    rows = {}
    for x0, y0, x1, _y1, w, *_ in words:
        rows.setdefault(round(y0 / ytol), []).append((x0, x1, w))
    lines = []
    for key in sorted(rows):
        toks = sorted(rows[key], key=lambda t: t[0])
        lines.append((key * ytol, toks))

    out = []
    for li, (y, toks) in enumerate(lines):
        # the span wording usually sits on the 1-3 lines above the dates
        ctx = " ".join(w for _lj, ts in lines[max(0, li - 3) : li + 1] for _a, _b, w in ts)
        for i, (x0, x1, w) in enumerate(toks):
            qe = None
            m = NUMERIC.match(w.strip().rstrip(","))
            if m:
                qe = _norm(*m.groups())
            else:
                dm = DAYMON.match(w.strip().rstrip(","))
                if dm and i + 2 < len(toks):
                    mon = toks[i + 1][2].strip(",.").lower()[:3]
                    yr = YEAR.match(toks[i + 2][2].strip(",."))
                    if mon in MONTHS and yr:
                        qe = _norm(dm.group(1), MONTHS[mon], yr.group(1))
                if qe is None and w.strip(",.").lower()[:3] in MONTHS and i + 2 < len(toks):
                    dd = DAYMON.match(toks[i + 1][2].strip(","))
                    yr = YEAR.match(toks[i + 2][2].strip(",."))
                    if dd and yr:
                        qe = _norm(dd.group(1), MONTHS[w.strip(",.").lower()[:3]], yr.group(1))
            if qe:
                out.append((qe, x1, y, ctx))
    return out


def header_rows(page, ytol=3.0, min_dates=2):
    """Date rows that are a real TABLE HEADER, not a date mentioned in prose.

    The first version scanned the whole page and mistook narrative dates for columns -- it averaged
    1.5 columns per page where a statement has 3-5, and 1 of 8 sampled pages produced a value.
    A header has two properties prose does not:
      * SEVERAL dates share one baseline (a column header row), so require >= min_dates on one y;
      * it sits ABOVE the numeric body of the table.
    A lone date on a line is prose until proven otherwise.
    """
    # Cluster by a BAND, not an exact baseline. Many statements stack the caption inside each
    # column cell ("Quarter / ended / 31.12.2018"), so the dates of adjacent columns land on
    # slightly different y. Requiring an exact shared baseline found headers on only 3% of pages;
    # a +-14pt band recovers them without letting a prose date in (prose dates are isolated).
    pts = sorted(dates_on(page, ytol), key=lambda t: t[2])
    out, i = [], 0
    while i < len(pts):
        j, y0 = i, pts[i][2]
        while j < len(pts) and pts[j][2] - y0 <= 14.0:
            j += 1
        grp = pts[i:j]
        # de-duplicate by x so one column counted once
        seen, uniq = set(), []
        for qe, x, _y, ctx in sorted(grp, key=lambda t: t[1]):
            k = round(x / 8.0)
            if k in seen:
                continue
            seen.add(k)
            uniq.append((qe, x, ctx))
        if len(uniq) >= min_dates:
            out.append((y0, uniq))
        i = j
    return out


# An AMOUNT, not merely a number. The letterhead of every Indian filing is full of digits --
# "ISO 9001", "IS014001", "DANDELI - 581 325", "CIN: L02101KA1955PLC001936", phone numbers -- and
# treating those as table body put the body marker ABOVE the real header, so the true header row
# was discarded as a footnote. That single confusion was most of the 4% detection rate.
AMOUNT = re.compile(
    r"^\(?-?\d{1,3}(?:,\d{2,3})+(?:\.\d+)?\)?$"  # 1,234 / 12,34,567.89
    r"|^\(?-?\d+\.\d{2}\)?$"
)  # 1234.56


def _first_numeric_y(page, ytol=3.0):
    """Baseline of the first row that looks like table BODY (>=2 AMOUNTS on one line)."""
    rows = {}
    for _x0, y0, _x1, _y1, w, *_ in page.get_text("words"):
        if AMOUNT.match(w):
            k = round(y0 / ytol)
            rows[k] = rows.get(k, 0) + 1
    hits = [y for y, n in sorted(rows.items()) if n >= 2]
    return hits[0] * ytol if hits else None


def quarter_columns(page, ytol=3.0):
    """-> {qe: x_right} for columns that are a SINGLE QUARTER, taken from a real header row.

    A cumulative column ending on the same date is dropped rather than competing, because taking it
    silently converts a nine-month figure into 'the quarter' -- the defect class this campaign
    healed 58 of.
    """
    body_y = _first_numeric_y(page, ytol)
    best = {}
    for y, dates in header_rows(page, ytol):
        if body_y is not None and y > body_y:
            continue  # below the numbers: a footnote, not a header
        for qe, x, ctx in dates:
            if CUMULATIVE.search(ctx) and not QUARTERLY.search(ctx):
                continue
            # a date seen more than once at different x: keep the leftmost (statements print the
            # current quarter first, cumulative blocks to its right)
            if qe not in best or x < best[qe]:
                best[qe] = x
    return best


BASIS_CON = re.compile(r"c[o0]ns[o0]lidated", re.IGNORECASE)
BASIS_NOT_CON = re.compile(
    r"n[o0]n[\s-]*c[o0]ns[o0]lidated|un[\s-]*c[o0]ns[o0]lidated|"
    r"standal[o0]ne",
    re.IGNORECASE,
)


def page_basis(page):
    """'con' / 'std' / 'both' / None from the page's own wording. Glyph-tolerant (§51: a->o, t->l).

    'both' USED TO BE None, and that was the single biggest source of false "this filing has no
    consolidated page" verdicts (runbook §71k). A very common Indian layout prints STANDALONE and
    CONSOLIDATED side by side in ONE statement, five columns each -- that page names both bases, so
    it collapsed to None, and every reader filtering `page_basis(pg) == "con"` skipped the only page
    carrying the numbers. BANCOINDIA 2019-03 was escalated all the way to the vision rung over it;
    its consolidated PAT was sitting in plain text on page 1 the whole time.

    'both' is NOT a promise that the page is a statement -- a cover note saying "the Standalone and
    Consolidated results were approved" says both words too. It means "do not rule this page out on
    basis alone"; the caller still has to find a labelled row and anchor a column on it.
    """
    t = page.get_text()[:1500]
    has_not = bool(BASIS_NOT_CON.search(t))
    # "Consolidated" must be found OUTSIDE any "Non-Consolidated"/"Un-Consolidated", or the word
    # inside the negation counts as evidence of a consolidated statement. NSE titles standalone
    # filings "Non-Consolidated", so without this every standalone page reads as 'both' and gets
    # offered as a consolidated candidate -- the exact opposite of the bug this function is fixing.
    has_con = bool(BASIS_CON.search(BASIS_NOT_CON.sub(" ", t)))
    if has_con and not has_not:
        return "con"
    if has_not and not has_con:
        return "std"
    if has_con and has_not:
        return "both"
    return None


def page_shows(page, want):
    """Could this page carry `want` ('con'/'std')? True for its own basis AND for 'both'.

    Use this instead of `page_basis(pg) == want` anywhere you are filtering pages to read. On a
    'both' page the two bases sit in separate column blocks, so the caller MUST identify its column
    by anchoring on a value it already stores (§58) rather than taking the first match -- otherwise
    it can read the standalone block while believing it read the consolidated one.
    """
    b = page_basis(page)
    return b in (want, "both")
