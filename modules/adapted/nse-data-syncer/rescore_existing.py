"""
Re-download and rescore all presentations already in the DB.
Uses presentation_url already stored — no NSE API scanning.

Usage:
  python scripts/rescore_existing.py               # all companies with a stored URL
  python scripts/rescore_existing.py --resume-after SYMBOL
"""
from __future__ import annotations

import argparse
import io
import sys
import time

import psycopg2

sys.path.insert(0, '/Users/gurudayal/Desktop/data-syncer/scripts')
from keyword_analysis import (
    clean_db_url, DB_URL, DB,
    download_pdf, extract_text,
    count_theme_keywords, analyse_sentiment,
    THEME_COLUMNS, ALTER_TABLE_SQL,
)

import pdfplumber


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--resume-after', default='')
    args = parser.parse_args()

    db = DB(clean_db_url(DB_URL))

    # Ensure new columns exist
    for stmt in ALTER_TABLE_SQL:
        db.execute(stmt)
    db.commit()

    db.execute("""
        SELECT symbol, company_name, result_date, presentation_url
        FROM presentation_keyword_analysis
        WHERE has_presentation = TRUE AND presentation_url IS NOT NULL AND presentation_url != ''
        ORDER BY symbol
    """)
    rows = db.fetchall()

    if args.resume_after:
        rows = [(s, n, d, u) for s, n, d, u in rows if s.upper() > args.resume_after.upper()]

    print(f'Companies to rescore: {len(rows)}\n')

    update_cols = (
        ['presentation_url', 'pdf_pages', 'pdf_chars']
        + THEME_COLUMNS
        + ['word_count', 'positive_hits', 'negative_hits',
           'positive_density', 'negative_density', 'sentiment_score']
    )
    update_sql = f"""
        UPDATE presentation_keyword_analysis SET
            {', '.join(f'{c} = %s' for c in update_cols)},
            analysed_at = NOW()
        WHERE symbol = %s AND result_date = %s
    """

    for i, (symbol, company_name, result_date, pres_url) in enumerate(rows, 1):
        print(f'[{i}/{len(rows)}] {symbol} ({result_date}) … ', end='', flush=True)

        pdf_bytes = download_pdf(pres_url)
        if not pdf_bytes:
            print('download failed, skipping')
            continue

        text = extract_text(pdf_bytes)
        theme_counts = count_theme_keywords(text)
        sentiment = analyse_sentiment(text)

        try:
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                n_pages = len(pdf.pages)
        except Exception:
            n_pages = 0

        kw_display = ', '.join(f'{k}={v}' for k, v in theme_counts.items() if v > 0) or 'no theme matches'
        print(f"{n_pages}pp → {kw_display}")

        values = [pres_url, n_pages, len(text)]
        values += [theme_counts[c] for c in THEME_COLUMNS]
        values += [
            sentiment['word_count'], sentiment['positive_hits'], sentiment['negative_hits'],
            sentiment['positive_density'], sentiment['negative_density'], sentiment['sentiment_score'],
        ]
        values += [symbol, result_date]

        db.execute(update_sql, values)
        db.commit()

        time.sleep(0.5)

    db.close()
    print('\nDone.')


if __name__ == '__main__':
    main()
