#!/usr/bin/env python3
"""THE shared rules for the SHP filing-date campaign (PLAN_SHP_DATES.md phases 1-3).

⚠️ ONE implementation, imported by the fetcher, the calibration harness, the auditor and the
applier — the redating campaign's §F1 lesson: a parallel regex in the audit is what let 16 real
filings be mis-flagged there. Never re-implement these rules elsewhere.

SOURCE (found in Phase 0): api.bseindia.com/BseIndiaAPI/api/SHPQNewFormat/w?scripcode=<code>
carries a real `filing_date_time` per quarter, to the second, from the March-2016 quarter onward
(the SHP XBRL mandate). Pre-2016 rows exist but the field is null — measured, see P0-RESULTS.

ROW SHAPES the API actually returns (measured, not assumed):
  * status "New"     -> filing_date_time set, revised_date_time null. THE original disclosure.
  * status "Revised" -> filing_date_time NULL, revised_date_time set, qtrid = <n>.01.
    Usually accompanies its own "New" row; SOMETIMES it is the only row for the quarter
    (HINDUNILVR March 2020) — then the original filing time is simply not published.
  * qtr strings come in TWO formats: "March 2016" (modern) and "30 Jun 2008" (legacy rows).

VISIBILITY RULE: point-in-time visibility is the FIRST public disclosure, so prefer the New
row's filing_date_time. Fall back to the Revised timestamp only when no New row exists — that is
strictly LATER than the truth, i.e. conservative (it can never manufacture look-ahead), and the
fallback is tagged in provenance so it is never mistaken for an original filing time.

15:30 IST GATE: 56.4% of real filings broadcast after 15:30 (measured, 748 filings) — those are
only actionable the NEXT trading session. Same rule and same source of truth as gate_1530.py /
apply_redating.py: scripts/gate_calendar.json tdays.
"""
import re, json, os, bisect, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
CUTOFF_MIN = 15 * 60 + 30

MONTHS = {'january': 1, 'february': 2, 'march': 3, 'april': 4, 'may': 5, 'june': 6, 'july': 7,
          'august': 8, 'september': 9, 'october': 10, 'november': 11, 'december': 12}
for _k, _v in list(MONTHS.items()):
    MONTHS[_k[:3]] = _v
QEND_DAY = {3: 31, 6: 30, 9: 30, 12: 31}

_MONYEAR = re.compile(r'^\s*([A-Za-z]+)\s+(\d{4})\s*$')
_DDMONYEAR = re.compile(r'^\s*(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})\s*$')


def qtr_to_qe(qtr):
    """'March 2016' | '30 Jun 2008' -> 20160331 | 20080630. None if not a real quarter-end."""
    if not qtr:
        return None
    s = str(qtr).strip()
    m = _MONYEAR.match(s)
    if m:
        mo = MONTHS.get(m.group(1).lower())
        if mo not in QEND_DAY:
            return None
        y = int(m.group(2))
        return y * 10000 + mo * 100 + QEND_DAY[mo]
    m = _DDMONYEAR.match(s)
    if m:
        mo = MONTHS.get(m.group(2).lower())
        if mo not in QEND_DAY:
            return None
        d, y = int(m.group(1)), int(m.group(3))
        if d != QEND_DAY[mo]:          # an as-on date that is not the quarter end: not our cell
            return None
        return y * 10000 + mo * 100 + d
    return None


def ts_parts(ts):
    """'2021-08-10T15:10:26.5' -> (20210810, minutes_after_midnight). (None, None) if unparseable."""
    try:
        d = int(ts[0:4]) * 10000 + int(ts[5:7]) * 100 + int(ts[8:10])
        mins = int(ts[11:13]) * 60 + int(ts[14:16])
        return d, mins
    except Exception:
        return None, None


def resolve_rows(table):
    """API Table -> {qe: {'ts', 'src', 'status'}} keeping the FIRST disclosure per quarter."""
    out = {}
    for x in table or []:
        qe = qtr_to_qe(x.get('qtr'))
        if qe is None:
            continue
        new_ts, rev_ts = x.get('filing_date_time'), x.get('revised_date_time')
        if new_ts:
            cur = out.get(qe)
            # a genuine New row always wins over a revised-only fallback, and if two New rows
            # ever appear for one quarter the EARLIER is the first disclosure.
            if cur is None or cur['src'] != 'new' or new_ts < cur['ts']:
                out[qe] = {'ts': new_ts, 'src': 'new', 'status': x.get('status')}
        elif rev_ts:
            cur = out.get(qe)
            if cur is None:
                out[qe] = {'ts': rev_ts, 'src': 'revised-fallback', 'status': x.get('status')}
    return out


_tdays = None
def tdays():
    global _tdays
    if _tdays is None:
        _tdays = json.load(open(os.path.join(SCRIPTS, 'gate_calendar.json')))['tdays']
    return _tdays


def visible_date(ts, cal=None):
    """Real broadcast timestamp -> the date a screen may first use it (15:30 IST rule).
    Returns (sub_ymd, gated_bool) or (None, False)."""
    cal = cal if cal is not None else tdays()
    d, mins = ts_parts(ts)
    if d is None:
        return None, False
    if mins is not None and mins > CUTOFF_MIN:
        i = bisect.bisect_right(cal, d)
        return (cal[i], True) if i < len(cal) else (None, False)
    return d, False


def is_convention(qe, sub):
    """True when sub is exactly quarter-end + 21 days (the placeholder signature)."""
    if not qe or not sub:
        return False
    try:
        d0 = datetime.date(qe // 10000, (qe // 100) % 100, qe % 100)
        d1 = datetime.date(sub // 10000, (sub // 100) % 100, sub % 100)
    except ValueError:
        return False
    return (d1 - d0).days == 21
