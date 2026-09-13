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
"""Fetch the NSE event calendar (board meetings) and write docs/results_calendar.json —
the UPCOMING-results calendar for the Quarterly Results page. Reuses build_fundamentals'
CI-proven NSE session (plain urllib + Chrome UA + cookie warmup), same as fetch_announcements.

- Window: RC_BACK days back .. RC_FWD days forward (companies announce meeting dates weeks ahead).
- Keeps only events whose purpose/description mentions financial results.
- Self-healing: refuses to overwrite an existing file with a suspiciously tiny fetch.
- Output: {"updated","from","to","rows":[[symbol, company, "YYYY-MM-DD", purpose], ...]} date-ascending.

Run: python -X utf8 scripts/fetch_results_calendar.py
"""
import datetime
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_fundamentals as B  # _get / nse_jar / UA

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "docs", "results_calendar.json")
RC_BACK, RC_FWD = 3, 75
MIN_ROWS = 5  # a broken/empty fetch must never clobber a good calendar
MON = {
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
RESULT_RE = re.compile(r"financial\s+result|quarterly\s+result|un[- ]?audited.*result|audited.*result", re.IGNORECASE)


def ddmmyyyy(d):
    return "%02d-%02d-%04d" % (d.day, d.month, d.year)


def parse_date(s):
    """'11-Jul-2026' -> '2026-07-11' (also accepts '11-07-2026')."""
    s = str(s or "").strip()
    m = re.match(r"(\d{1,2})-([A-Za-z]{3})-(\d{4})", s)
    if m:
        mo = MON.get(m.group(2).lower())
        if mo:
            return "%s-%02d-%02d" % (m.group(3), mo, int(m.group(1)))
    m = re.match(r"(\d{1,2})-(\d{1,2})-(\d{4})", s)
    if m:
        return "%s-%02d-%02d" % (m.group(3), int(m.group(2)), int(m.group(1)))
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return m.group(0)
    return None


def main():
    today = datetime.date.today()
    lo, hi = today - datetime.timedelta(days=RC_BACK), today + datetime.timedelta(days=RC_FWD)
    jar = B.nse_jar()
    hdr = {
        "User-Agent": B.UA,
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://www.nseindia.com/companies-listing/corporate-filings-event-calendar",
    }
    url = f"https://www.nseindia.com/api/event-calendar?index=equities&from_date={ddmmyyyy(lo)}&to_date={ddmmyyyy(hi)}"
    try:
        j = json.loads(B._get(url, headers=hdr, jar=jar, timeout=90))
    except Exception as ex:
        print("ERR fetch:", ex)
        j = []
    rows = {}
    for rec in j if isinstance(j, list) else []:
        sym = str(rec.get("symbol") or "").strip().upper()
        dt = parse_date(rec.get("date"))
        if not sym or not dt:
            continue
        purpose = re.sub(r"\s+", " ", str(rec.get("purpose") or "")).strip()
        desc = re.sub(r"\s+", " ", str(rec.get("bm_desc") or rec.get("desc") or "")).strip()
        if not (RESULT_RE.search(purpose) or RESULT_RE.search(desc)):
            continue
        co = re.sub(r"\s+", " ", str(rec.get("company") or rec.get("sm_name") or "")).strip()
        p = purpose if RESULT_RE.search(purpose) else "Financial Results"
        if len(p) > 120:
            p = p[:119] + "…"
        rows[sym + "|" + dt] = [sym, co, dt, p]

    allrows = sorted(rows.values(), key=lambda r: (r[2], r[0]))
    if len(allrows) < MIN_ROWS and os.path.exists(OUT):
        print("ABORT: only %d rows — keeping existing calendar" % len(allrows))
        sys.exit(1)

    ist = datetime.datetime.utcnow() + datetime.timedelta(hours=5, minutes=30)
    out = {"updated": ist.strftime("%Y-%m-%d %H:%M IST"), "from": lo.isoformat(), "to": hi.isoformat(), "rows": allrows}
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    print("WROTE %s: %d result events %s..%s" % (os.path.normpath(OUT), len(allrows), lo, hi))


if __name__ == "__main__":
    main()
