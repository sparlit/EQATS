from __future__ import annotations

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


"""
Backfill pead_announcements from April 8, 2026 (start of Q4 FY26 results season).
The live poller started capturing from May 12, so this fills the gap.

Usage:
  python scripts/backfill_pead.py [--from 2026-04-08] [--to 2026-05-11]
"""


import argparse
import os
import re
import time
from datetime import date, timedelta

import psycopg2
import requests

DB_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://postgres:6XC3bmwDse3Bu6f@database-1.cziuywsuc132.ap-south-1.rds.amazonaws.com:5432/nifty_data?sslmode=require",
)

NSE_API = "https://www.nseindia.com/api/corporate-announcements"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"

RESULT_KEYWORDS = [
    "financial result",
    "quarterly result",
    "unaudited result",
    "audited result",
    "half yearly result",
    "annual result",
]
EXCLUDE_CATEGORIES = [
    "copy of newspaper publication",
    "clarification - financial results",
    "reply to clarification",
    "analysts/institutional investor meet",
    "corporate insolvency",
    "general updates",
]

# Most genuine results outcomes use NSE's generic boilerplate ("X Limited has
# informed the Exchange regarding Outcome of [the] Board Meeting held on
# <date>.") because the actual financial figures live in the XBRL/PDF, not
# this text field. Only treat a board-meeting filing as NOT a result if it
# names something else specific instead of (or in addition to) that phrase.
GENERIC_OUTCOME_RE = re.compile(
    r"^.*\boutcome of (the )?board meeting\b(\s+held on [^.]+)?\.?\s*$",
    re.IGNORECASE,
)


def clean_db_url(url: str) -> str:
    return re.sub(r'sslmode=["\']?(\w+)["\']?', r"sslmode=\1", url.strip())


def is_result(ann: dict) -> bool:
    cat = ann.get("desc", "").lower()
    if any(e in cat for e in EXCLUDE_CATEGORIES):
        return False
    text = (ann.get("desc", "") + " " + ann.get("attchmntText", "")).lower()
    if "outcome of board meeting" in cat:
        attchmnt_text = (ann.get("attchmntText") or "").strip()
        if "result" in text:
            return True
        return attchmnt_text == "" or bool(GENERIC_OUTCOME_RE.match(attchmnt_text))
    return any(kw in text for kw in RESULT_KEYWORDS)


def fetch_nse(date_str: str) -> list[dict]:
    """date_str in DD-MM-YYYY format."""
    try:
        resp = requests.get(
            NSE_API,
            params={"index": "equities", "from_date": date_str, "to_date": date_str},
            headers={
                "User-Agent": UA,
                "Accept": "application/json",
                "Referer": "https://www.nseindia.com/companies-listing/corporate-filings-announcements",
            },
            timeout=25,
        )
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, list) else []
    except Exception as e:
        print(f"  NSE fetch error for {date_str}: {e}")
        return []


def iter_weekdays(start: date, end: date):
    d = start
    while d <= end:
        if d.weekday() < 6:  # Mon–Sat (Indian companies file on Saturdays)
            yield d
        d += timedelta(days=1)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--from", dest="start", default="2026-04-08")
    parser.add_argument("--to", dest="end", default="2026-05-11")
    args = parser.parse_args()

    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)

    conn = psycopg2.connect(clean_db_url(DB_URL))
    cur = conn.cursor()

    # Find dates already fully covered so we can skip them
    cur.execute("SELECT DATE(announced_at AT TIME ZONE 'Asia/Kolkata') FROM pead_announcements GROUP BY 1")
    already_done = {r[0] for r in cur.fetchall()}
    print(f"Dates already in DB: {len(already_done)}")

    total_inserted = 0

    for d in iter_weekdays(start, end):
        if d in already_done:
            print(f"{d}  already covered, skipping")
            continue

        nse_date = d.strftime("%d-%m-%Y")
        print(f"{d}  fetching NSE …", end="", flush=True)

        all_anns = fetch_nse(nse_date)
        result_anns = [a for a in all_anns if is_result(a)]

        if not result_anns:
            print(f"  {len(all_anns)} total, 0 results")
            time.sleep(1)
            continue

        # Cross-reference with board_meetings for that date
        cur.execute("SELECT UPPER(symbol) FROM board_meetings WHERE meeting_date = %s", (d,))
        calendar_syms = {r[0] for r in cur.fetchall()}

        if calendar_syms:
            filtered = [a for a in result_anns if a.get("symbol", "").upper() in calendar_syms]
        else:
            # No board meetings in DB for this date — store all result announcements anyway
            filtered = result_anns

        print(f"  {len(all_anns)} total, {len(result_anns)} results, {len(filtered)} matched calendar", end="")

        inserted = 0
        for ann in filtered:
            seq_id = str(ann.get("seq_id", ""))
            if not seq_id:
                continue

            # Parse announced_at from NSE date string
            an_dt_str = ann.get("an_dt", "")
            announced_at = None
            for fmt in ("%d-%b-%Y %H:%M:%S", "%d-%m-%Y %H:%M:%S"):
                try:
                    from datetime import datetime, timedelta, timezone

                    IST = timezone(timedelta(hours=5, minutes=30))
                    announced_at = datetime.strptime(an_dt_str.strip(), fmt).replace(tzinfo=IST)
                    break
                except (ValueError, AttributeError):
                    pass

            if not announced_at:
                # Fallback: use noon IST on the filing date
                from datetime import datetime, timedelta, timezone

                IST = timezone(timedelta(hours=5, minutes=30))
                announced_at = datetime(d.year, d.month, d.day, 12, 0, 0, tzinfo=IST)

            cur.execute(
                """
                INSERT INTO pead_announcements
                    (seq_id, symbol, company_name, announced_at, latency_sec,
                     subject, attachment_url, has_xbrl, phase1_sent)
                VALUES (%s, %s, %s, %s, 0, %s, %s, %s, FALSE)
                ON CONFLICT (seq_id) DO NOTHING
            """,
                (
                    seq_id,
                    ann.get("symbol", ""),
                    ann.get("sm_name", ""),
                    announced_at,
                    ann.get("desc", ""),
                    ann.get("attchmntFile", ""),
                    bool(ann.get("hasXbrl")),
                ),
            )
            if cur.rowcount:
                inserted += 1

        conn.commit()
        total_inserted += inserted
        print(f"  → inserted {inserted}")
        time.sleep(1.5)  # be polite to NSE

    cur.close()
    conn.close()
    print(f"\nDone. Total new rows inserted: {total_inserted}")


if __name__ == "__main__":
    main()
