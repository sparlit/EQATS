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
"""GEOMETRIC column addressing -- the correct implementation of §55b.

Every column bug in this campaign has the same root: `values[i]` from one row was assumed to mean
the same period as `values[i]` from another row. In a PDF that is simply false. Text extraction
linearises a table, and rows legitimately differ in width -- merged cells, a notes column, a
sub-total that spans, a footnote marker parsed as a token. So:

    BALKRISIND: PAT row and revenue row differ in width -> index 5 pointed at a different period
                -> 170.61, which is the exact wrong number I refused by hand earlier.
    Requiring equal width instead makes the reader SAFE but nearly blind (1 of 7).

The fix is not a better index rule. It is to stop using indices. Financial statements RIGHT-ALIGN
their figures, so a period column is a vertical band of x-coordinates, stable across every row of
the table. `page.get_text("words")` gives each token's bounding box, so:

    1. group tokens into visual lines by y
    2. on the PAT row, find the token whose value reproduces our STORED PAT for this quarter+basis
       at some declared scale -> that token's RIGHT EDGE x1 is the target column's x
    3. on the revenue row, take the token whose right edge sits in the SAME band
    4. confirm: a DIFFERENT band on the same rows must reproduce a DIFFERENT quarter we store

Two rows can now have completely different widths and the read is still correct, because the column
is a geometric fact about the page rather than a guess about list positions.
"""
import re

NUMTOK = re.compile(r"^\(?-?[\d,]+\.?\d*\)?$")
SCALES = ((1.0, "crore"), (10.0, "million"), (100.0, "lakh"))
XTOL = 14.0  # points; columns are typically 40-90pt apart, so this is comfortably tight


def parse_num(tok):
    if not NUMTOK.match(tok):
        return None
    neg = tok.startswith("(")
    try:
        v = float(tok.strip("()").replace(",", ""))
    except ValueError:
        return None
    return -v if neg else v


def band_rows(words, ytol=3.0):
    """Group words into visual rows by CLUSTERING y, not by BUCKETING it.

    ROWS ARE GEOMETRY TOO (2026-08-09). This module fixed columns and left rows as
    `round(y0 / ytol)` -- the same defect one axis over. A bucket has hard edges, so a row whose
    tokens sit at y=388.4 and y=389.3 is TORN IN HALF: 388.4/3 rounds to 129, 389.3/3 to 130. The
    label keeps whichever fragment shares its bucket and the rest becomes an orphan numeric row
    belonging to no label. Statements typeset figures with sub-point baseline jitter, so this is
    routine rather than exotic.

    It is what made TIMKEN 2024-12-31 unreadable -- its consolidated PAT row extracted as
        y389.3  "5 Net Profit after tax (3-4)"  545.56@286  935.99@330
        y388.4                                  782.0J@381  2,565.82@423  2,718.89@469 ...
    and the Dec-2024 column the read needed sat in the half with no label attached.

    Clustering on the GAP between consecutive baselines has no edges to straddle. Intra-row jitter
    measures ~0.4-1.2pt here and line pitch ~6-12pt, two cleanly separated populations with `ytol`
    between them.
    """
    out, cur, top = [], [], None
    for x0, y0, x1, _y1, w, *_ in sorted(words, key=lambda t: t[1]):
        if top is not None and y0 - top > ytol:
            out.append((top, cur))
            cur, top = [], None
        cur.append((x0, x1, w))
        top = y0 if top is None else max(top, y0)
    if cur:
        out.append((top, cur))
    return out


def lines_of(page, ytol=3.0):
    """-> [(y, label_text, [(x_right, value), ...])] in reading order."""
    words = page.get_text("words")  # (x0, y0, x1, y1, word, block, line, word_no)
    if not words:
        return []
    out = []
    for y, row in band_rows(words, ytol):
        toks = sorted(row, key=lambda t: t[0])
        vals, label = [], []
        for _x0, x1, w in toks:
            v = parse_num(w)
            if v is None:
                if not vals:  # label words precede the figures
                    label.append(w)
            else:
                vals.append((x1, v))
        if vals:
            out.append((y, " ".join(label), vals))
    return out


def at_column(vals, x, tol=XTOL):
    """The value whose right edge sits in the band around x, or None."""
    best = None
    for x1, v in vals:
        d = abs(x1 - x)
        if d <= tol and (best is None or d < best[0]):
            best = (d, v)
    return None if best is None else best[1]


def find(page, anchor, others, pat_pats, rev_pats):
    """-> (revenue, evidence) using geometric columns.

    `anchor`  : our stored PAT for the target quarter+basis (locates the column)
    `others`  : [(name, value)] other stored figures used to CONFIRM a second column
    """
    rows = lines_of(page)
    if not rows:
        return None, None

    def rank(label, pats):
        for i, p in enumerate(pats):
            if p.search(label):
                return i
        return None

    # Collect EVERY valid reading and choose by label specificity, never by page order. First-match
    # is fragile: widening the label sets to unlock CYIENT silently broke BALKRISIND, because a
    # newly-matched but less specific row now came first. Specificity is the stable tiebreak --
    # patterns are ordered most-specific-first in both families.
    pat_rows = [(rank(r[1], pat_pats), r) for r in rows if rank(r[1], pat_pats) is not None]
    rev_rows_r = [(rank(r[1], rev_pats), r) for r in rows if rank(r[1], rev_pats) is not None]
    if not pat_rows or not rev_rows_r:
        return None, None
    [r for _k, r in rev_rows_r]
    best = None
    for prank, (_y, plabel, pvals) in sorted(pat_rows, key=lambda t: t[0]):
        for x1, v in pvals:
            for sc, un in SCALES:
                if abs(v / sc - anchor) > max(0.05, abs(anchor) * 0.004):
                    continue
                # CONFIRM: a different band on this same PAT row must reproduce another stored value
                conf = None
                for name, ov in others:
                    if ov is None or abs(ov - anchor) <= max(0.05, abs(anchor) * 0.004):
                        continue
                    for x2, w in pvals:
                        if abs(x2 - x1) > XTOL and abs(w / sc - ov) <= max(0.05, abs(ov) * 0.004):
                            conf = f"col x={x2:.0f} reproduces {name} {ov:.2f} at the same scale"
                            break
                    if conf:
                        break
                if conf is None:
                    continue
                for rrank, (_y2, rlabel, rvals) in sorted(rev_rows_r, key=lambda t: t[0]):
                    got = at_column(rvals, x1)
                    if got is not None and got > 0:
                        cand = (
                            (prank, rrank),
                            round(got / sc, 2),
                            {
                                "x": round(x1, 1),
                                "scale": un,
                                "rev_row": rlabel[:44],
                                "pat_row": plabel[:44],
                                "anchor": anchor,
                                "confirm": conf,
                                "method": "geometric column (§55b)",
                            },
                        )
                        if best is None or cand[0] < best[0]:
                            best = cand
                        break
    return (None, None) if best is None else (best[1], best[2])
