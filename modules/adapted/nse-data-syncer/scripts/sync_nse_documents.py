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
Sync ALL NSE corporate announcements into nse_documents table.

Fetches every filing for every company (results, presentations, press releases,
concalls, general updates) and stores:
  - seq_id        NSE's own unique filing ID
  - symbol / company_name
  - category      raw NSE category string (ann.desc)
  - description   filing text (ann.attchmntText)
  - attachment_url
  - doc_type      derived: result | presentation | press_release | concall | transcript | general
  - nse_filed_at  exact timestamp NSE recorded the filing (ann.an_dt)
  - fetched_at    when we inserted it

Usage:
  python scripts/sync_nse_documents.py                          # yesterday + today
  python scripts/sync_nse_documents.py --from 2026-04-01       # backfill from date to today
  python scripts/sync_nse_documents.py --from 2026-04-01 --to 2026-08-02
"""


import argparse
import os
import re
import time
from datetime import date, datetime, timedelta, timezone

import psycopg2
import requests

DB_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://postgres:6XC3bmwDse3Bu6f@database-1.cziuywsuc132.ap-south-1.rds.amazonaws.com:5432/nifty_data?sslmode=require",
)

NSE_API = "https://www.nseindia.com/api/corporate-announcements"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
NSE_HEADERS = {
    "User-Agent": UA,
    "Accept": "application/json",
    "Referer": "https://www.nseindia.com/companies-listing/corporate-filings-announcements",
}
IST = timezone(timedelta(hours=5, minutes=30))

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS nse_documents (
    id                SERIAL PRIMARY KEY,
    seq_id            TEXT UNIQUE NOT NULL,
    symbol            TEXT NOT NULL,
    company_name      TEXT,
    category          TEXT,
    description       TEXT,
    attachment_url    TEXT,
    doc_type          TEXT NOT NULL DEFAULT 'general',
    nse_filed_at      TIMESTAMPTZ,
    fetched_at        TIMESTAMPTZ DEFAULT NOW(),
    kw_dispatched_at  TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS ix_nse_docs_symbol     ON nse_documents (symbol);
CREATE INDEX IF NOT EXISTS ix_nse_docs_doc_type   ON nse_documents (doc_type);
CREATE INDEX IF NOT EXISTS ix_nse_docs_filed_at   ON nse_documents (nse_filed_at);
ALTER TABLE nse_documents ADD COLUMN IF NOT EXISTS kw_dispatched_at TIMESTAMPTZ;
"""

# Patterns for classifying doc_type from category + description text
RESULT_KEYWORDS = [
    "financial result",
    "quarterly result",
    "unaudited result",
    "audited result",
    "half yearly result",
    "annual result",
]
PRESENTATION_KEYWORDS = [
    "investor presentation",
    "investors presentation",
    "investor update",
    "investor meet",
    "investor/analyst",
    "analyst meet",
    "investorpresentation",
    "investorupdate",
]
PRESS_RELEASE_KEYWORDS = ["press release"]
CONCALL_KEYWORDS = ["concall", "con call", "conference call", "earnings call"]
TRANSCRIPT_KEYWORDS = ["transcript"]


def classify_doc_type(ann: dict) -> str:
    category = (ann.get("desc") or "").lower()
    text = (ann.get("attchmntText") or "").lower()
    url = (ann.get("attchmntFile") or "").lower().replace("_", " ").replace("-", " ")
    combined = f"{category} {text} {url}"

    if "outcome of board meeting" in category or any(k in combined for k in RESULT_KEYWORDS):
        return "result"
    if any(k in combined for k in PRESENTATION_KEYWORDS):
        return "presentation"
    if any(k in combined for k in TRANSCRIPT_KEYWORDS):
        return "transcript"
    if any(k in combined for k in CONCALL_KEYWORDS):
        return "concall"
    if any(k in combined for k in PRESS_RELEASE_KEYWORDS):
        return "press_release"
    return "general"


def parse_nse_time(s: str) -> datetime | None:
    if not s:
        return None
    for fmt in ("%d-%b-%Y %H:%M:%S", "%d-%m-%Y %H:%M:%S"):
        try:
            return datetime.strptime(s.strip(), fmt).replace(tzinfo=IST)
        except ValueError:
            pass
    return None


def clean_db_url(url: str) -> str:
    return re.sub(r'sslmode=["\']?(\w+)["\']?', r"sslmode=\1", url.strip())


def fetch_nse(date_str: str) -> list[dict]:
    """Fetch all NSE announcements for date_str (DD-MM-YYYY)."""
    try:
        resp = requests.get(
            NSE_API,
            params={"index": "equities", "from_date": date_str, "to_date": date_str},
            headers=NSE_HEADERS,
            timeout=25,
        )
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, list) else []
    except Exception as e:
        print(f"  NSE fetch error {date_str}: {e}")
        return []


def iter_weekdays(start: date, end: date):
    d = start
    while d <= end:
        if True:  # all days including Sunday
            yield d
        d += timedelta(days=1)


def main():
    parser = argparse.ArgumentParser(description="Sync NSE documents to DB")
    parser.add_argument("--from", dest="start", default=None, help="Start date YYYY-MM-DD (default: yesterday)")
    parser.add_argument("--to", dest="end", default=None, help="End date YYYY-MM-DD (default: today)")
    args = parser.parse_args()

    today = date.today()
    start = date.fromisoformat(args.start) if args.start else today - timedelta(days=1)
    end = date.fromisoformat(args.end) if args.end else today

    conn = psycopg2.connect(clean_db_url(DB_URL))
    cur = conn.cursor()

    # Create table if needed
    cur.execute(SCHEMA_SQL)
    conn.commit()

    # Dates already fully ingested (have at least one doc that day)
    cur.execute("""
        SELECT DATE(nse_filed_at AT TIME ZONE 'Asia/Kolkata')
        FROM nse_documents
        GROUP BY 1
    """)
    {r[0] for r in cur.fetchall()}

    total_inserted = 0
    total_updated = 0

    for d in iter_weekdays(start, end):
        nse_date = d.strftime("%d-%m-%Y")
        print(f"{d}  fetching …", end="", flush=True)

        anns = fetch_nse(nse_date)
        if not anns:
            print("  0 announcements")
            time.sleep(1)
            continue

        inserted = updated = 0
        for ann in anns:
            seq_id = str(ann.get("seq_id") or "").strip()
            if not seq_id:
                continue

            symbol = (ann.get("symbol") or "").strip().upper()
            company_name = (ann.get("sm_name") or "").strip()
            category = (ann.get("desc") or "").strip()
            description = (ann.get("attchmntText") or "").strip()
            attach_url = (ann.get("attchmntFile") or "").strip()
            bool(ann.get("hasXbrl"))
            doc_type = classify_doc_type(ann)
            nse_filed_at = parse_nse_time(ann.get("an_dt", "")) or datetime(
                d.year, d.month, d.day, 12, 0, 0, tzinfo=IST
            )

            # Historical rows (not today) get kw_dispatched_at = NOW() so the
            # Lambda never tries to dispatch keyword analysis for old filings.
            is_today = d == date.today()
            cur.execute(
                """
                INSERT INTO nse_documents
                    (seq_id, symbol, company_name, category, description,
                     attachment_url, doc_type, nse_filed_at, kw_dispatched_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (seq_id) DO UPDATE
                    SET company_name   = EXCLUDED.company_name,
                        category       = EXCLUDED.category,
                        description    = EXCLUDED.description,
                        attachment_url = EXCLUDED.attachment_url,
                        doc_type       = EXCLUDED.doc_type
                RETURNING (xmax = 0) AS was_inserted
            """,
                (
                    seq_id,
                    symbol,
                    company_name,
                    category,
                    description,
                    attach_url,
                    doc_type,
                    nse_filed_at,
                    None if is_today else datetime.now(IST),
                ),
            )

            row = cur.fetchone()
            if row and row[0]:
                inserted += 1
            else:
                updated += 1

        conn.commit()
        total_inserted += inserted
        total_updated += updated
        print(f"  {len(anns)} docs  +{inserted} new  ~{updated} updated")
        time.sleep(1.2)

    conn.close()
    print(f"\nDone. Total inserted: {total_inserted}  updated: {total_updated}")


if __name__ == "__main__":
    main()
