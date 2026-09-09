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


#!/usr/bin/env python3
"""THE shared row classifier + date extractor for the staleness re-dating campaign.

⚠️ ONE implementation, imported by fetch_and_match.py (matching), apply_redating.py (the
refusal net) and the audit scripts. PLAN_QUANTMAC_FIXES.md §F1 made this structural because a
PARALLEL audit regex is exactly what produced the 2026-08-20 error: the audit flagged 16 genuine
"Board Meeting Outcome for …" results as intimations. Two regexes drift; then the audit stops
measuring what actually ships. Never re-implement these rules anywhere else — import them.

Three classes (PLAN §F1, corrected by §G):
  'result'    — a real disclosure of the numbers. The only class that may set an ann-date freely.
  'secondary' — a re-publication that follows the filing: Reg-47 newspaper ads, "Updates on …".
                Writable ONLY as a last resort (nothing else dates that quarter), provenance-tagged.
                Systematically a few days LATE (measured 472 of 501 later), so it is a bound, not truth.
  'intimation'— a forward-looking notice: board-meeting calls, "to consider/approve", analyst-meet
                intimations, reschedules. NEVER writable: it precedes the results, so writing it
                manufactures LOOK-AHEAD — the exact defect quantmac caught us on (PAGEIND would have
                been stamped ~3 weeks early).

Date extraction (PLAN §G/§F5 — each rule has a live proof case):
  * "ended"/"for" + optional "on"/"as on"/"as at"     — SANWARIA "…Period Ended On 31.12.22"
  * 2-digit years                                      — same row ("22" -> 2022)
  * numeric DD.MM.YYYY (Indian day-month order)        — GEOJITFSL "ended 30.09.2019"
  * finditer, never search (a row can carry 2+ dates)  — ESSAROIL annual+quarterly combo
  * anchor-LESS dates, but ONLY quarter-ends in rows that mention "result" — RANEHOLDIN
    "Results - Financial Results March 31, 2024" extracted NOTHING under the anchor rule, so the
    next-day newspaper ad won by default. Safe by construction: targets are only ever quarter-ends,
    so a stray "Held On May 15, 2024" can never match one.
"""
import datetime
import re

MONTHS = {}
for _i, _m in enumerate(
    [
        "january",
        "february",
        "march",
        "april",
        "may",
        "june",
        "july",
        "august",
        "september",
        "october",
        "november",
        "december",
    ],
    1,
):
    MONTHS[_m] = _i
    MONTHS[_m[:3]] = _i
MONTHS["sept"] = 9

_MON = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*"
# anchor: ended / ending / for / as on / as at / Q.E., then optional "on"/"the"/punctuation
_ANCH = r"(?:end(?:ed|ing)|for|as\s+on|as\s+at|q\.?\s*e\.?)\s*[:\-,]?\s*(?:on\s+|the\s+)?"

DATE_NAMED = re.compile(
    _ANCH + r"(?:(\d{1,2})(?:st|nd|rd|th)?\s+(" + _MON + r")|(" + _MON + r")\.?\s+(\d{1,2})(?:st|nd|rd|th)?)"
    r",?\s*(\d{2,4})",
    re.IGNORECASE,
)
DATE_NUMERIC = re.compile(_ANCH + r"(\d{1,2})[./-](\d{1,2})[./-](\d{2,4})", re.IGNORECASE)
# anchor-less forms (guarded: quarter-ends only, results rows only)
BARE_NAMED = re.compile(
    r"(?:(\d{1,2})(?:st|nd|rd|th)?\s+(" + _MON + r")|(" + _MON + r")\.?\s+(\d{1,2})(?:st|nd|rd|th)?)"
    r",?\s*(\d{4})",
    re.IGNORECASE,
)
BARE_NUMERIC = re.compile(r"(\d{1,2})[./-](\d{1,2})[./-](\d{2,4})")

QUARTER_ENDS = {(3, 31), (6, 30), (9, 30), (12, 31)}

# Re-publications that FOLLOW the filing (Reg 47 newspaper ads, "Updates on …").
SECONDARY_RE = re.compile(
    r"newspaper|news\s*paper|publication of (?:the\s+)?extract|^\s*updates?\s+on\b", re.IGNORECASE
)

# ⚠️ Weak markers ONLY. A real filing routinely BUNDLES its press release and deck —
# "Announces Q2 results, Results Press Release & Limited Review Report for the quarter ended …"
# (JSWSTEEL/MARUTI/PGHH/MASTEK) is the DISCLOSURE, not a re-publication. Demoting those on the
# words "press release" inflated 'secondary' to 2,542 against 512 actually measured (calibration
# gate 3, 2026-08-20). So a weak marker demotes only when NO core results-disclosure phrase is
# present, or when the row LEADS with the accompanying artefact ("Presentation To Analysts On …").
SECONDARY_WEAK = re.compile(r"press\s+release|presentation|media\s+release|analyst\s+meet\s+deck", re.IGNORECASE)
SECONDARY_LEAD = re.compile(
    r"^\s*(?:presentation|press\s+release|media\s+release|investor\s+presentation)", re.IGNORECASE
)
RESULTS_CORE = re.compile(
    r"financial\s+results?|announces?\s+(?:q[1-4]\b|fy\b|its\b|the\b)?\s*\w*\s*results?|"
    r"results?\s*[-:]|(?:un)?audited\s+results?|quarterly\s+results?|\bq[1-4]\s+(?:&\s*fy\w*\s+)?results?",
    re.IGNORECASE,
)

# Forward-looking notices. NEVER writable.
INTIMATION_RE = re.compile(
    r"\bintimation\b|\bnotice\s+of\b|\bprior\s+intimation\b|\bregulation\s*29\b|"
    r"board\s+meeting\s+(?:on|dated|to\b|will\b|is\b|scheduled|shall|for\b)|"
    r"for\s+(?:the\s+)?consideration\s+of|"
    # Clause-41 option election: "has OPTED TO SUBMIT the Audited Financial Results ... WITHIN A
    # PERIOD" is a notice of INTENT to publish later, not the results. v2's phrase list had
    # "opted to submit"; dropping it in the v3 rewrite was a regression that surfaced on the
    # exact cell quantmac's finding 2 is about — OMAXE qe20120331 matched the 2012-04-30
    # election notice instead of the real 2012-05-30 17:50 disclosure (raw-cache re-match,
    # 2026-08-23). "Publish Audited Results" headlines ride the same template.
    r"opted?\s+to\s+(?:submit|publish)|\bpublish\s+audited\s+results\b|"
    r"within\s+a\s+period\s+of|"
    r"\bto\s+(?:be\s+)?consider(?:ed)?\b|\bto\s+approve\b|\bto\s+transact\b|"
    # forward tenses ONLY — 'was/were held' is a PAST meeting, i.e. an outcome statement
    # (PANORAMA qe20191231's real result read 'the Meeting … was held on 14th February'
    # and got refused as an intimation until this narrowed, 2026-08-23).
    r"(?:is|are|will\s+be|shall\s+be|to\s+be)\s+(?:held|scheduled|convened)|"
    # results-TIMING notice: 'FY 09 results BY Jun 30, 2009' promises a future publication
    # date; bare-date extraction reads the deadline as a quarter-end and earliest-wins then
    # beats the real filing, which the lag<0 gate kills — losing the cell (MUNJALSHOW
    # qe20090630 kept its placeholder that way, found post-push 2026-08-23).
    r"\bresults?\s+by\b|"
    r"\bresched|\bpostpone|\bprepone|change\s+in\s+(?:the\s+)?date|"
    r"analyst\s*/?\s*\&?\s*investor|investors?\s+meet|earnings\s+call|conference\s+call|"
    r"\bagenda\b|\bproposed\b",
    re.IGNORECASE,
)

# An OUTCOME override rescues a genuine disclosure that merely CONTAINS notice-ish words.
# BSE's post-2018 template literally prefixes real outcomes with "Board Meeting Outcome for …",
# and those rows often go on to quote the notice text they are answering (§G/F1: VASWANI,
# ARCHIES, SFL, GUJRAFFIA, VLEGOV, CEREBRAINT were all wrongly flagged without this).
OUTCOME_RE = re.compile(
    r"^\s*board\s+meeting\s+outcome\b|"
    r"outcome\s+of\s+(?:the\s+)?(?:\w+\s+){0,3}?(?:board\s+)?meeting|"
    r"board\s+meeting\s+held\b|"
    # NB: "has INFORMED" is deliberately NOT here — every BSE headline reads "X has informed BSE
    # that …", intimations included, so it rescued the OMAXE Clause-41 election notice back to
    # 'result' (calibration fail, 2026-08-23). A genuine disclosure never needs that word: its
    # own title carries the results language.
    r"\bhas\s+(?:approved|posted|announced|submitted|declared)\b|"
    r"\bannounces?\s+|"
    # done-act forms only: bare "submit" also lives inside "opted to SUBMIT …", the Clause-41
    # election notice (the OMAXE cell, 2026-08-23) — rescuing on it re-admits that intimation.
    r"\bsubmission\s+of\b|\bsubmits\b|\bsubmitted\b|"
    r"\bhave\s+been\s+approved\b|\bwere\s+approved\b|\bapproved\s+the\s+(?:audited|unaudited|financial)",
    re.IGNORECASE,
)


def classify_row(sub, head=""):
    """-> 'result' | 'secondary' | 'intimation'. See module docstring for the contract."""
    text = f"{sub or ''} {head or ''}"
    if SECONDARY_RE.search(text) or SECONDARY_LEAD.search(sub or ""):
        return "secondary"
    if INTIMATION_RE.search(text) and not OUTCOME_RE.search(text):
        return "intimation"
    if SECONDARY_WEAK.search(text) and not RESULTS_CORE.search(text):
        return "secondary"
    return "result"


def _year(y):
    y = int(y)
    if y >= 1000:
        return y
    # data spans 2001-2026; "22" -> 2022, "99" -> 1999
    return 2000 + y if y <= 30 else 1900 + y


def _add(out, y, mo, d, quarter_end_only=False):
    if not mo or not (1 <= mo <= 12):
        return
    if quarter_end_only and (mo, d) not in QUARTER_ENDS:
        return
    try:
        datetime.date(y, mo, d)
    except ValueError:
        return
    if not (1990 <= y <= 2100):
        return
    out.add(y * 10000 + mo * 100 + d)


def extract_all_qes(text, allow_bare=False):
    """Every date the text mentions, as YYYYMMDD ints. allow_bare drops the anchor requirement
    but then accepts ONLY quarter-end dates (RANEHOLDIN class — see module docstring)."""
    if not text:
        return set()
    out = set()
    for m in DATE_NAMED.finditer(text):
        if m.group(2):
            d, mon, y = int(m.group(1)), MONTHS.get(m.group(2).lower()), _year(m.group(5))
        else:
            mon, d, y = MONTHS.get(m.group(3).lower()), int(m.group(4)), _year(m.group(5))
        _add(out, y, mon, d)
    for m in DATE_NUMERIC.finditer(text):
        _add(out, _year(m.group(3)), int(m.group(2)), int(m.group(1)))
    if allow_bare:
        for m in BARE_NAMED.finditer(text):
            if m.group(2):
                d, mon, y = int(m.group(1)), MONTHS.get(m.group(2).lower()), _year(m.group(5))
            else:
                mon, d, y = MONTHS.get(m.group(3).lower()), int(m.group(4)), _year(m.group(5))
            _add(out, y, mon, d, quarter_end_only=True)
        for m in BARE_NUMERIC.finditer(text):
            _add(out, _year(m.group(3)), int(m.group(2)), int(m.group(1)), quarter_end_only=True)
    return out


def row_dates(row, cls=None):
    """Every date in a BSE announcement row. Bare dates are allowed only for rows that both
    mention a result and are not forward-looking notices."""
    sub = row.get("NEWSSUB") or ""
    head = row.get("HEADLINE") or ""
    if cls is None:
        cls = classify_row(sub, head)
    text = f"{sub} {head}"
    allow_bare = cls in ("result", "secondary") and "result" in text.lower()
    return extract_all_qes(sub, allow_bare) | extract_all_qes(head, allow_bare)


def is_year_ago_comparative(target_qe, all_dates):
    """True when target_qe is a YEAR-AGO COMPARISON inside a row whose real subject is a later
    quarter — the class that made CESC's four 2003 quarters match 2004 filings ~394 days late
    ("…quarter ended June 30, 2004 as compared to …June 30, 2003"). Signature: another date in
    the SAME row, LATER, exact whole-year multiple apart on the same month/day.

    Deliberately preserves ESSAROIL-style genuine annual+quarterly combos (2010-03-31 with
    2010-06-30 — different month/day, 3 months apart), which are two real disclosures.
    """
    tmd = target_qe % 10000
    ty = target_qe // 10000
    for d in all_dates:
        if d <= target_qe:
            continue
        if d % 10000 == tmd and (d // 10000) > ty:
            return True
    return False
