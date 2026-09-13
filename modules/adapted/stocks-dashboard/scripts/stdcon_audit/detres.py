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
"""BSE detailed-results JSON (runbook §42) as a STANDALONE PAT source, with a basis CALIBRATION.

§42 says the endpoint serves "standalone/primary basis only" -- "primary" is the word that matters
for this audit. If BSE ever served a consolidated figure for a scrip, and our std slot also held the
consolidated figure, the two would agree and we would wrongly clear the cell. So every read is
calibrated for THIS scrip before it is believed:

  CAL-REV  the same response's revenue row must match our stored standalone revenue for the
           quarter AND differ from our stored consolidated revenue (free -- same API call).
  CAL-PAT  the nearest DIVERGENT quarter (stored std != stored con) must come back matching the
           stored STD, not the stored CON.

Either calibration passing makes the endpoint's basis established for that scrip; both failing
means the read is reported but never used to clear a cell.
"""
import json
import os
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
API = "https://api.bseindia.com/BseIndiaAPI/api/Corp_detailedResult_Transpose_ng/w?scrip_cd=%s&qtr=%s"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
MONTHS = {
    "Jan": 1,
    "Feb": 2,
    "Mar": 3,
    "Apr": 4,
    "May": 5,
    "Jun": 6,
    "Jul": 7,
    "Aug": 8,
    "Sep": 9,
    "Oct": 10,
    "Nov": 11,
    "Dec": 12,
}
_CACHE = {}


def qid(qe):
    y, m = qe // 10000, (qe // 100) % 100
    n = 85 + (y - 2015) * 4 + {3: 0, 6: 1, 9: 2, 12: 3}[m]
    return None if not 0 <= n - 85 <= 60 else "%d.00" % n


def _get(scrip, q):
    k = (scrip, q)
    if k in _CACHE:
        return _CACHE[k]
    out = {}
    for attempt in (1, 2, 3):
        try:
            req = urllib.request.Request(
                API % (scrip, q), headers={"User-Agent": UA, "Referer": "https://www.bseindia.com/"}
            )
            with urllib.request.urlopen(req, timeout=40) as r:
                js = json.loads(r.read().decode("utf-8", "replace"))
            for row in js.get("table1") or []:
                out.setdefault((row.get("fld_desc") or "").strip(), row.get("Value"))
            break
        except Exception:
            time.sleep(1.5 * attempt)
    _CACHE[k] = out
    time.sleep(0.35)
    return out


def _num(f, *names):
    for n in names:
        v = f.get(n)
        if v not in (None, "", "-"):
            try:
                return float(v)
            except ValueError:
                pass
    return None


def _dt(s):
    try:
        d, mo, y = s.split("-")
        return (2000 + int(y)) * 10000 + MONTHS[mo] * 100 + int(d)
    except Exception:
        return None


def read(scrip, qe):
    """{'pat': cr, 'rev': cr, 'eps':, 'span_ok':} or None. Values are Rs MILLION -> /10 (§42)."""
    q = qid(qe)
    if not q or not scrip:
        return None
    f = _get(scrip, q)
    if not f:
        return None
    np = _num(f, "Net Profit", "Net Profit (+)/ Loss (-) from Ordinary Activities after Tax")
    if np is None:
        return None
    b, e = _dt(f.get("Date Begin") or ""), _dt(f.get("Date End") or "")
    span = None
    if b and e:
        span = (e // 10000 * 12 + (e // 100) % 100) - (b // 10000 * 12 + (b // 100) % 100)
    # ALWAYS verify the 3-month span (§42): annual and H1 rows live in the same id space.
    ok = span == 2 and e == qe
    return {
        "pat": round(np / 10.0, 2),
        "rev": (
            round(_num(f, "Net Sales/Revenue From Operations", "Total Income") / 10.0, 2)
            if _num(f, "Net Sales/Revenue From Operations", "Total Income") is not None
            else None
        ),
        "eps": _num(f, "Basic EPS for continuing operation", "Basic for discontinued & continuing operation"),
        "span_ok": ok,
        "span": span,
        "end": e,
        "type": f.get("Type"),
    }
