"""
Backfill the 'highest' theme keyword column for already-analysed presentations.

Re-downloads each stored presentation PDF (presentation_url already known,
no NSE search needed) and counts \\bhighest\\b occurrences.

Usage:
  python3 scripts/backfill_highest.py
"""

from __future__ import annotations

import io
import re
import time

import psycopg2
import requests

import logging
logging.getLogger('pdfminer').setLevel(logging.ERROR)

import pdfplumber

from keyword_analysis import clean_db_url, DB_URL, PDF_HEADERS, DB

HIGHEST_RE = re.compile(r'\bhighest\b')


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
        print(f'[{i}/{len(rows)}] {symbol}', end=' … ', flush=True)
        try:
            resp = requests.get(url, headers=PDF_HEADERS, timeout=60)
            resp.raise_for_status()
            with pdfplumber.open(io.BytesIO(resp.content)) as pdf:
                text = '\n'.join(p.extract_text() or '' for p in pdf.pages)
            count = len(HIGHEST_RE.findall(text.lower()))
            print(f'highest={count}')
        except Exception as e:
            print(f'error: {e}')
            count = 0

        db.execute(
            "UPDATE presentation_keyword_analysis SET highest = %s WHERE symbol = %s AND result_date = %s",
            (count, symbol, result_date)
        )
        db.commit()
        time.sleep(0.5)

    db.close()
    print('\nDone.')


if __name__ == '__main__':
    main()
