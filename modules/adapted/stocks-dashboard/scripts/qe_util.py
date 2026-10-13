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
"""Quarter-end date helpers shared by the BSE results readers (fetch_bse_fund, bse_vision_prep,
merge_bse_vision). A quarter end is an int YYYYMMDD on a calendar quarter end (0331/0630/0930/1231).

Nothing here knows which quarter is "current" — callers derive that from the filing itself (its
printed period, else its announcement date), so the readers never go stale at a season change.
"""
import datetime
import re

_ENDS = (331, 630, 930, 1231)
_MON = [
    "",
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]


def is_qe(qe):
    return isinstance(qe, int) and qe % 10000 in _ENDS and 1990 <= qe // 10000 <= 2100


def prevq(qe):
    """20260930 -> 20260630; 20260331 -> 20251231."""
    y, md = qe // 10000, qe % 10000
    return {
        331: (y - 1) * 10000 + 1231,
        630: y * 10000 + 331,
        930: y * 10000 + 630,
        1231: y * 10000 + 930,
    }[md]


def yago(qe):
    """Same quarter one year earlier: 20260930 -> 20250930."""
    return qe - 10000


def label(qe):
    """20260930 -> '30 September 2026' (the wording results tables print)."""
    return "%d %s %d" % (qe % 100, _MON[(qe // 100) % 100], qe // 10000)


def last_qe_before(yyyymmdd):
    """Latest quarter end STRICTLY before a date (int YYYYMMDD or 'YYYY-MM-DD'). A result filed on
    2026-10-20 is for the quarter ended 20260930. Returns 0 for an unparseable date."""
    try:
        s = str(yyyymmdd).replace("-", "")[:8]
        d = datetime.date(int(s[:4]), int(s[4:6]), int(s[6:8]))
    except Exception:
        return 0
    cands = [(d.year - 1) * 10000 + 1231] + [d.year * 10000 + md for md in _ENDS]
    return max(c for c in cands if datetime.date(c // 10000, c // 100 % 100, c % 100) < d)


_QTR_ANCHOR = re.compile(r"\bquarter|\bthree months|\b3 months", re.I)  # \b: not "Headquarter"


def _normalise(text):
    """Undo PDF/OCR text damage that hides a date: line breaks inside it ('30th June,\n2026') and glued
    words ('QUARTERENDED30thJUNE,2026')."""
    s = re.sub(r"\s+", " ", str(text or ""))
    s = re.sub(r"(?i)(end(?:ed|ing))(?=\d)", r"\1 ", s)
    s = re.sub(r"(?i)(\d)(st|nd|rd|th)(?=[a-z])", r"\1\2 ", s)
    s = re.sub(r"(?i)(quarter)(?=ended)", r"\1 ", s)
    s = re.sub(r"(?i)(the)(?=quarter)", r"\1 ", s)  # 'FoRTHEQUARTER' (not 'Headquarter')
    s = re.sub(
        r"(?i)\b(\d{1,2})[\-/]([a-z]{3,9})[\-/](\d{4})\b", r"\1 \2 \3", s
    )  # 30-Sep-2026 / 30/Sep/2026
    return s


def stated_quarter(text):
    """The quarter a results filing says it reports, read ONLY right after a 'quarter' / 'three months'
    phrase — so a balance sheet's 'as at 31 March' or a 'year ended' column can't win. 0 if unstated.
    Uses fetch_announcements.parse_qe for the date forms ('30th June, 2026', '30.09.2026', 'September 30,
    2026', 'half year ended 30TH SEPTEMBER, 2026' …)."""
    import fetch_announcements as FA

    s = _normalise(text)
    for m in _QTR_ANCHOR.finditer(s):
        nxt = _QTR_ANCHOR.search(s, m.end())  # a window never runs into the next 'quarter' phrase
        q = FA.parse_qe(s[m.start() : min(m.start() + 60, nxt.start() if nxt else len(s))])
        if q:
            return q
    return 0
