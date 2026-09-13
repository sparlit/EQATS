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
Backfill the 'highest' theme keyword column for already-analysed presentations.

Re-downloads each stored presentation PDF (presentation_url already known,
no NSE search needed) and counts \\bhighest\\b occurrences.

Usage:
  python3 scripts/backfill_highest.py
"""


import io
import logging
import re
import time

import psycopg2
import requests

logging.getLogger("pdfminer").setLevel(logging.ERROR)

import pdfplumber
from keyword_analysis import DB, DB_URL, PDF_HEADERS, clean_db_url

HIGHEST_RE = re.compile(r"\bhighest\b")


def main():
    db = DB(clean_db_url(DB_URL))
    db.execute("ALTER TABLE presentation_keyword_analysis ADD COLUMN IF NOT EXISTS highest INT DEFAULT 0")
    db.commit()

    db.execute("""
        SELECT symbol, result_date, presentation_url
        FROM presentation_keyword_analysis
        WHERE has_presentation = TRUE AND presentation_url IS NOT NULL
        ORDER BY symbol
    """)
    rows = db.fetchall()
    print(f'Backfilling "highest" for {len(rows)} presentations\n')

    for i, (symbol, result_date, url) in enumerate(rows, 1):
        print(f"[{i}/{len(rows)}] {symbol}", end=" … ", flush=True)
        try:
            resp = requests.get(url, headers=PDF_HEADERS, timeout=60)
            resp.raise_for_status()
            with pdfplumber.open(io.BytesIO(resp.content)) as pdf:
                text = "\n".join(p.extract_text() or "" for p in pdf.pages)
            count = len(HIGHEST_RE.findall(text.lower()))
            print(f"highest={count}")
        except Exception as e:
            print(f"error: {e}")
            count = 0

        db.execute(
            "UPDATE presentation_keyword_analysis SET highest = %s WHERE symbol = %s AND result_date = %s",
            (count, symbol, result_date),
        )
        db.commit()
        time.sleep(0.5)

    db.close()
    print("\nDone.")


if __name__ == "__main__":
    main()
